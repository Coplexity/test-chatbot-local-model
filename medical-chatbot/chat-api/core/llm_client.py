import httpx
from langchain_openai import ChatOpenAI

from core import config

_STRUCTURED_OUTPUT_METHODS = {"json_schema", "function_calling"}

_http_client = None
_http_async_client = None
_announced = False


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
