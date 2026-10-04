import asyncio
import re

import httpx
from langchain_openai import ChatOpenAI

from core import config

_STRUCTURED_OUTPUT_METHODS = {"json_schema", "function_calling"}
# Chỗ kết thúc một ý trọn vẹn: dấu chấm câu, xuống dòng hoặc thẻ trích dẫn đã đóng.
_COMPLETE_UNIT_END = re.compile(r"[.!?…](?=\s|$)|\n|</source>")

# Dùng khi không gọi được /tokenize. Đo thật trên prompt tiếng Việt của expert là ~3.07 ký tự/token;
# lấy thấp hơn để ước lượng dư token, thà cắt thừa còn hơn vượt context.
_FALLBACK_CHARS_PER_TOKEN = 2.5

_http_client = None
_http_async_client = None
_announced = False
_tokenize_warned = False


def _validate_config():
    missing = [
        name
        for name, value in (
            ("LLM_BASE_URL", config.LLM_BASE_URL),
            ("LLM_API_KEY", config.LLM_API_KEY),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Thiếu cấu hình LLM: {', '.join(missing)}. "
            "chat-api chỉ gọi LLM trên Server A (vLLM) và không fallback sang OpenAI. "
            "Hãy khai báo trong medical-chatbot/deploy/.env rồi recreate container chat-api."
        )
    if config.LLM_STRUCTURED_OUTPUT_METHOD not in _STRUCTURED_OUTPUT_METHODS:
        raise RuntimeError(
            f"LLM_STRUCTURED_OUTPUT_METHOD={config.LLM_STRUCTURED_OUTPUT_METHOD!r} không hợp lệ, "
            f"chỉ nhận: {', '.join(sorted(_STRUCTURED_OUTPUT_METHODS))}."
        )


def _shared_http_clients():
    """Dùng chung một connection pool cho mọi node để giới hạn số request đồng thời tới A."""
    global _http_client, _http_async_client
    if config.LLM_MAX_CONCURRENCY <= 0:
        return None, None
    if _http_client is None:
        limits = httpx.Limits(
            max_connections=config.LLM_MAX_CONCURRENCY,
            max_keepalive_connections=config.LLM_MAX_CONCURRENCY,
        )
        _http_client = httpx.Client(limits=limits)
        _http_async_client = httpx.AsyncClient(limits=limits)
    return _http_client, _http_async_client


def get_llm(temperature: float) -> ChatOpenAI:
    """Tạo client sinh văn bản trỏ tới Server A theo API contract B → A."""
    global _announced
    _validate_config()
    if not _announced:
        print(
            f"🤖 [LLM] model={config.LLM_MODEL} base_url={config.LLM_BASE_URL} "
            f"max_tokens={config.LLM_MAX_TOKENS} timeout={config.LLM_TIMEOUT_SECONDS}s "
            f"max_concurrency={config.LLM_MAX_CONCURRENCY} "
            f"structured_output={config.LLM_STRUCTURED_OUTPUT_METHOD}"
        )
        _announced = True

    http_client, http_async_client = _shared_http_clients()
    return ChatOpenAI(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        api_key=config.LLM_API_KEY,
        temperature=temperature,
        max_tokens=config.LLM_MAX_TOKENS,
        # pool=None: request xếp hàng chờ slot không bị tính vào timeout.
        timeout=httpx.Timeout(config.LLM_TIMEOUT_SECONDS, pool=None),
        max_retries=config.LLM_MAX_RETRIES,
        stream_usage=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        http_client=http_client,
        http_async_client=http_async_client,
    )


def _drop_unclosed_source(text: str) -> str:
    start = text.rfind("<source")
    if start != -1 and "</source>" not in text[start:]:
        return text[:start]
    return text


def trim_truncated_tail(text: str) -> str:
    """Bỏ phần đuôi dở của báo cáo bị cắt: thẻ <source> chưa đóng và nửa câu cuối.

    Thẻ <source> dở mà lọt xuống bước tổng hợp thì CitationStreamTransformer sẽ giữ lại
    mọi chữ phía sau để chờ thẻ đóng, làm câu trả lời đứng hình hoặc gộp sai trích dẫn.
    """
    text = _drop_unclosed_source(text)
    # Đuôi bị cắt ngay giữa tên thẻ, ví dụ "<sour" hoặc "</sou".
    last_lt = text.rfind("<")
    if last_lt != -1:
        tail = text[last_lt:]
        if "<source".startswith(tail) or "</source>".startswith(tail):
            text = text[:last_lt]
    # Cắt về cuối câu, cuối dòng hoặc cuối thẻ trích dẫn gần nhất.
    ends = [m.end() for m in _COMPLETE_UNIT_END.finditer(text)]
    if ends:
        text = text[: ends[-1]]
    # Điểm cắt có thể nằm giữa một thẻ <source> đã đóng, nên kiểm tra lại.
    return _drop_unclosed_source(text).rstrip()


def report_text(response, label: str) -> str:
    """Lấy nội dung báo cáo trung gian; bị cắt vì chạm trần max_tokens thì bỏ phần đuôi dở."""
    content = response.content or ""
    if (getattr(response, "response_metadata", None) or {}).get("finish_reason") != "length":
        return content
    trimmed = trim_truncated_tail(content)
    print(
        f"⚠️ [LLM] {label}: báo cáo bị cắt vì chạm trần max_tokens, "
        f"bỏ {len(content) - len(trimmed)} ký tự đuôi dở."
    )
    return trimmed


async def gather_skipping_failures(coros):
    """Chạy song song các lời gọi; lời gọi nào lỗi thì bỏ, chỉ báo lỗi khi tất cả đều lỗi.

    Mỗi lời gọi tự in log lỗi kèm nhãn của nó trước khi raise.
    """
    outcomes = await asyncio.gather(*coros, return_exceptions=True)
    for item in outcomes:
        # Bị hủy (người dùng ngắt kết nối...) thì dừng luôn, không coi là một báo cáo lỗi.
        if isinstance(item, BaseException) and not isinstance(item, Exception):
            raise item
    successes = [item for item in outcomes if not isinstance(item, Exception)]
    if outcomes and not successes:
        # Không còn báo cáo nào để trả lời: báo lỗi như trước, thay vì trả câu "chưa đủ thông tin".
        raise next(item for item in outcomes if isinstance(item, Exception))
    return successes


async def count_tokens(prompt: str) -> int:
    """Đếm token input của một prompt đúng như A sẽ nhận (đã qua chat template của Qwen)."""
    global _tokenize_warned
    _validate_config()
    # /tokenize của vLLM nằm ở gốc server, không nằm dưới /v1.
    url = config.LLM_BASE_URL.removesuffix("/v1") + "/tokenize"
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "add_generation_prompt": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        # Client riêng: đếm token không chiếm slot sinh văn bản của LLM_MAX_CONCURRENCY.
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            )
            response.raise_for_status()
            return int(response.json()["count"])
    except Exception as exc:
        if not _tokenize_warned:
            print(
                f"⚠️ [LLM] Không đếm được token qua {url} ({type(exc).__name__}); "
                f"tạm ước lượng {_FALLBACK_CHARS_PER_TOKEN} ký tự/token."
            )
            _tokenize_warned = True
        return int(len(prompt) / _FALLBACK_CHARS_PER_TOKEN) + 1
