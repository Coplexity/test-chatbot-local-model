import re

from core import config
from core.llm_client import count_tokens

# VectorRetrievalNode ghép context từ các chunk dạng "[<chunk_id>]" + tùy chọn "\nTÓM TẮT: ..."
# + "\nNỘI DUNG: ...", nối bằng một dòng trống, chunk liên quan nhất đứng trước.
_CHUNK_BOUNDARY = re.compile(r"\n\n(?=\[[^\]\n]+\]\n(?:TÓM TẮT|NỘI DUNG): )")
# Chừa lề cho sai khác nhỏ giữa /tokenize và lúc A serialize request thật.
_SAFETY_MARGIN_TOKENS = 256
_MAX_TRUNCATE_ROUNDS = 8


def input_token_budget() -> int:
    """Số token input tối đa của một lần gọi: context của A trừ phần dành cho output."""
    return config.LLM_CONTEXT_TOKENS - config.LLM_MAX_TOKENS - _SAFETY_MARGIN_TOKENS


async def fit_prompt_to_budget(build_prompt, context: str, label: str) -> str:
    """Trả về build_prompt(context) sau khi đã bỏ bớt chunk xếp hạng thấp nếu vượt ngân sách input.

    build_prompt nhận chuỗi context và trả về prompt hoàn chỉnh; label chỉ dùng để ghi log.
    """
    budget = input_token_budget()
    prompt = build_prompt(context)
    tokens = await count_tokens(prompt)
    if tokens <= budget:
        return prompt

    chunks = _CHUNK_BOUNDARY.split(context)
    original_tokens, original_chunks = tokens, len(chunks)
    while tokens > budget and len(chunks) > 1:
        # Ước lượng theo tỉ lệ ký tự phần cần bỏ, bỏ chunk từ cuối (xếp hạng thấp nhất) rồi đếm lại thật.
        excess_chars = len(prompt) * (tokens - budget) / tokens
        dropped_chars = 0
        while len(chunks) > 1 and dropped_chars < excess_chars:
            dropped_chars += len(chunks.pop()) + 2
        prompt = build_prompt("\n\n".join(chunks))
        tokens = await count_tokens(prompt)

    # Chỉ còn một chunk mà vẫn vượt: cắt bớt phần cuối của chính chunk đó.
    rounds = 0
    while tokens > budget and chunks[0] and rounds < _MAX_TRUNCATE_ROUNDS:
        keep_chars = int(len(chunks[0]) * budget / tokens * 0.95)
        chunks[0] = chunks[0][:keep_chars]
        prompt = build_prompt(chunks[0])
        tokens = await count_tokens(prompt)
        rounds += 1

    truncated = " (chunk cuối bị cắt bớt)" if rounds else ""
    print(
        f"✂️ [Context Budget] {label}: {original_tokens} token vượt ngân sách {budget}; "
        f"giữ {len(chunks)}/{original_chunks} chunk{truncated}, còn {tokens} token."
    )
    if tokens > budget:
        print(f"⚠️ [Context Budget] {label}: phần ngoài context đã vượt ngân sách, A sẽ từ chối request này.")
    return prompt
