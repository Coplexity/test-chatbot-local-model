"""Kiểm tra kết nối chat-api (Server B) → vLLM (Server A) bằng chính client của ứng dụng.

Chạy từ bên trong container để dùng đúng mạng và dependency đang triển khai:

    docker compose exec chat-api python -m scripts.check_llm

Chỉ gửi request ngắn; không thay cho test basic/deep end-to-end hay đánh giá chất lượng y khoa.
"""

import asyncio
import json
import sys
import time
import urllib.error
import urllib.request

from core import config
from core.context_budget import fit_prompt_to_budget, input_token_budget
from core.llm_client import count_tokens, get_llm
from core.prompts import DISEASE_ROUTING_PROMPT, QUESTION_VALIDATION_PROMPT, ROUTER_PROMPT
from core.schemas import RouteDecision, SpecialtyDiseaseDecision, ValidationResult

SAMPLE_QUERY = "Trẻ 5 tuổi sốt cao 39 độ ngày thứ 3, kèm phát ban và đau bụng thì xử trí thế nào?"
SAMPLE_DOMAINS = ["Truyền nhiễm", "Tim mạch", "Hô hấp"]
SAMPLE_DISEASES = ["Sốt xuất huyết Dengue", "Sởi", "Tay chân miệng"]


def _redact(text) -> str:
    text = str(text)
    if config.LLM_API_KEY:
        text = text.replace(config.LLM_API_KEY, "[REDACTED]")
    return text[:2000]


def _get_models(api_key: str):
    request = urllib.request.Request(
        config.LLM_BASE_URL + "/models",
        headers={"Authorization": "Bearer " + api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096).decode("utf-8", errors="replace")


def check_auth():
    status, _ = _get_models("wrong-key-for-check")
    assert status in (401, 403), f"key sai phải bị từ chối, nhận HTTP {status}"
    return f"key sai bị từ chối (HTTP {status})"


def check_model_alias():
    status, body = _get_models(config.LLM_API_KEY)
    assert status == 200, f"GET /models trả HTTP {status}: {body}"
    models = {item.get("id"): item for item in body.get("data", [])}
    assert config.LLM_MODEL in models, f"không thấy alias {config.LLM_MODEL!r}, A đang có: {sorted(models)}"
    return f"alias {config.LLM_MODEL}, max_model_len={models[config.LLM_MODEL].get('max_model_len')}"


def check_chat():
    response = get_llm(temperature=0).invoke("Tính 2 + 3, trả lời ngắn bằng tiếng Việt.")
    finish_reason = response.response_metadata.get("finish_reason")
    assert response.content.strip(), "content rỗng"
    assert finish_reason == "stop", f"finish_reason={finish_reason!r}"
    assert response.usage_metadata, "thiếu usage"
    return f"{response.content.strip()!r} | usage={dict(response.usage_metadata)}"


def check_output_budget():
    # Xác nhận A áp dụng trần output theo đúng field mà langchain-openai gửi đi.
    response = get_llm(temperature=0).invoke("Viết một đoạn văn 200 từ về bệnh sốt xuất huyết.", max_tokens=8)
    finish_reason = response.response_metadata.get("finish_reason")
    output_tokens = (response.usage_metadata or {}).get("output_tokens")
    assert finish_reason == "length", f"max_tokens=8 nhưng finish_reason={finish_reason!r}"
    assert output_tokens is not None and output_tokens <= 8, f"output_tokens={output_tokens}"
    return f"finish_reason=length, output_tokens={output_tokens}"


async def check_stream():
    text, chunks, usage = "", 0, None
    async for chunk in get_llm(temperature=0.1).astream("Nêu 3 dấu hiệu cảnh báo của sốt xuất huyết, mỗi ý một dòng."):
        if chunk.content:
            text += chunk.content
            chunks += 1
        usage = chunk.usage_metadata or usage
    assert text.strip(), "stream không có nội dung"
    assert chunks > 1, f"chỉ nhận {chunks} chunk, có thể không stream thật"
    assert usage, "stream thiếu usage"
    return f"{chunks} chunk, {len(text)} ký tự | usage={dict(usage)}"


def _structured(schema, prompt):
    llm = get_llm(temperature=0)
    return llm.with_structured_output(schema, method=config.LLM_STRUCTURED_OUTPUT_METHOD).invoke(prompt)


def check_validation_schema():
    result = _structured(ValidationResult, QUESTION_VALIDATION_PROMPT.format(query=SAMPLE_QUERY))
    assert result.category in {"greeting", "medical", "off_topic"}, f"category lạ: {result.category!r}"
    assert result.category == "medical", f"câu hỏi y khoa bị phân loại thành {result.category!r}"
    return f"category={result.category}"


def check_route_schema():
    prompt = ROUTER_PROMPT.format(
        domains_string=", ".join(SAMPLE_DOMAINS),
        query=SAMPLE_QUERY,
        max_specialties=config.DEEP_MAX_SPECIALTIES,
    )
    result = _structured(RouteDecision, prompt)
    names = [item.name for item in result.analyzed_specialties]
    assert names, "không chọn chuyên khoa nào"
    assert set(names) <= set(SAMPLE_DOMAINS), f"chuyên khoa ngoài danh sách: {names}"
    assert result.hypothetical_document.strip(), "hypothetical_document rỗng"
    return f"intent={result.detected_intent} specialties={names} hyde={len(result.hypothetical_document)} ký tự"


def check_disease_schema():
    specialty = SAMPLE_DOMAINS[0]
    prompt = DISEASE_ROUTING_PROMPT.format(
        specialties_string=specialty,
        candidates_string="\n".join(f"- {specialty}: {disease}" for disease in SAMPLE_DISEASES),
        query=SAMPLE_QUERY,
    )
    result = _structured(SpecialtyDiseaseDecision, prompt)
    assert result.ten_benh, "không chọn bệnh nào"
    # Cùng cách chuẩn hóa với DiseaseRoutingNode: bỏ tiền tố "<chuyên khoa>: " nếu model chép cả dòng.
    names = [name.removeprefix(f"{specialty}: ").strip() for name in result.ten_benh]
    assert set(names) <= set(SAMPLE_DISEASES), f"bệnh ngoài danh sách: {result.ten_benh}"
    prefixed = " (model trả kèm tiền tố chuyên khoa, đã chuẩn hóa)" if names != result.ten_benh else ""
    return f"ten_benh={names}{prefixed}"


async def check_parallel():
    # Các node experts gọi song song; request phải xếp hàng qua LLM_MAX_CONCURRENCY thay vì lỗi.
    llm = get_llm(temperature=0)
    prompts = [f"Trả lời đúng một số: {n} + {n} bằng bao nhiêu?" for n in (1, 2, 3)]
    responses = await asyncio.gather(*(llm.ainvoke(prompt) for prompt in prompts))
    assert all(response.content.strip() for response in responses), "có response rỗng"
    return f"{len(responses)} request song song đều có kết quả"


async def check_token_count():
    # /tokenize phải khớp đúng số prompt_tokens mà A tính cho request thật; lệch nghĩa là đang ước lượng.
    prompt = "Nêu 3 dấu hiệu cảnh báo của sốt xuất huyết, mỗi ý một dòng."
    counted = await count_tokens(prompt)
    response = await get_llm(temperature=0).ainvoke(prompt, max_tokens=1)
    actual = (response.usage_metadata or {}).get("input_tokens")
    assert counted == actual, f"/tokenize đếm {counted} nhưng A tính {actual} token input"
    return f"/tokenize={counted} khớp prompt_tokens={actual}; ngân sách input={input_token_budget()}"


async def check_context_budget():
    # Context cố tình vượt ngân sách: phải bị bỏ chunk từ cuối (xếp hạng thấp) cho tới khi vừa.
    budget = input_token_budget()
    sentence = "Người bệnh cần được theo dõi sát dấu hiệu sinh tồn và đánh giá lại sau mỗi 6 giờ điều trị. "
    chunk_body = sentence * 160
    chunk_tokens = await count_tokens(chunk_body)
    total = budget // chunk_tokens + 4
    context = "\n\n".join(
        f"[check-{index}]\nTÓM TẮT: đoạn kiểm tra {index}\nNỘI DUNG: {chunk_body}" for index in range(1, total + 1)
    )

    def build_prompt(text):
        return f"Tài liệu:\n{text}\n\nCâu hỏi: {SAMPLE_QUERY}"

    before = await count_tokens(build_prompt(context))
    assert before > budget, f"context thử chỉ có {before} token, chưa vượt ngân sách {budget}"
    prompt = await fit_prompt_to_budget(build_prompt, context, "check_llm")
    after = await count_tokens(prompt)
    kept = prompt.count("\nNỘI DUNG: ")
    assert after <= budget, f"sau khi cắt vẫn còn {after} token, vượt ngân sách {budget}"
    assert 0 < kept < total, f"giữ {kept}/{total} chunk"
    assert "[check-1]\n" in prompt and f"[check-{total}]\n" not in prompt, "phải giữ chunk đầu và bỏ chunk cuối"
    return f"{before} -> {after} token (ngân sách {budget}), giữ {kept}/{total} chunk"


CHECKS = [
    ("authentication", check_auth),
    ("model alias", check_model_alias),
    ("non-streaming chat and usage", check_chat),
    ("output budget", check_output_budget),
    ("streaming chat and usage", check_stream),
    ("structured output: ValidationResult", check_validation_schema),
    ("structured output: RouteDecision", check_route_schema),
    ("structured output: SpecialtyDiseaseDecision", check_disease_schema),
    ("parallel requests", check_parallel),
    ("token counting via /tokenize", check_token_count),
    ("context budget trimming", check_context_budget),
]


async def main() -> int:
    print(
        f"LLM_BASE_URL={config.LLM_BASE_URL or '<trống>'} LLM_MODEL={config.LLM_MODEL} "
        f"LLM_API_KEY={'<đã đặt>' if config.LLM_API_KEY else '<trống>'} "
        f"structured_output={config.LLM_STRUCTURED_OUTPUT_METHOD}"
    )
    failed = 0
    # Một event loop duy nhất: client async dùng chung connection pool giữa các kiểm tra.
    for name, check in CHECKS:
        started = time.monotonic()
        try:
            detail = await check() if asyncio.iscoroutinefunction(check) else check()
            print(f"PASS {name} ({time.monotonic() - started:.1f}s): {_redact(detail)}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name} ({time.monotonic() - started:.1f}s): {type(exc).__name__}: {_redact(exc)}")

    if failed:
        print(f"LLM_CHECK_FAILED ({failed}/{len(CHECKS)} kiểm tra lỗi)")
        return 1
    print("LLM_CHECK_COMPLETE (chỉ request ngắn; chưa test sát context hay chất lượng y khoa)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
