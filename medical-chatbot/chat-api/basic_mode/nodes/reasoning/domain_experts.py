import asyncio
from core.context_budget import fit_prompt_to_budget
from core import config
from core.llm_client import get_llm, warn_if_truncated
from basic_mode.core.schemas import RouterState
from basic_mode.core.prompts import EXPERT_PROMPT
from core.prompts import INTERMEDIATE_LENGTH_RULE


class DomainExpertsNode:


    def __init__(self):
        print("⏳ [Experts] Initializing Expert Agents...")
        self.llm = get_llm(temperature=0.1)

    @staticmethod
    async def _build_prompt(query: str, domain_name: str, context: str, label: str, length_rule: str = "") -> str:
        """Dựng prompt cho một chuyên gia; bỏ bớt chunk xếp hạng thấp nếu vượt ngân sách token của A."""

        def build_prompt(context_text: str) -> str:
            return EXPERT_PROMPT.format(
                domain_name=domain_name.upper(),
                context=context_text,
                query=query,
                FALLBACK_ANSWER="Trong guidelines không có đủ thông tin để mình có thể trả lời câu hỏi này.",
                length_rule=length_rule,
            )

        return await fit_prompt_to_budget(build_prompt, context, label)

    async def stream_single_report(self, query: str, domain_name: str, context: str):
        """Stream one specialty report token-by-token for low-latency terminal/UI output."""
        prompt = await self._build_prompt(query, domain_name, context, domain_name)

        async for chunk in self.llm.astream(prompt):
            chunk_text = getattr(chunk, "content", "") or ""
            if chunk_text:
                yield chunk_text

    async def process(self, state: RouterState):
        query = state["query"]
        contexts = state.get("specialty_contexts", {})

        async def generate_single_report(domain_name, context):
            length_rule = INTERMEDIATE_LENGTH_RULE.format(max_words=config.INTERMEDIATE_REPORT_MAX_WORDS)
            prompt = await self._build_prompt(query, domain_name, context, domain_name, length_rule)

            res = await self.llm.ainvoke(prompt, max_tokens=config.INTERMEDIATE_REPORT_MAX_TOKENS)
            warn_if_truncated(res, domain_name)
            return domain_name, res.content

        tasks = [generate_single_report(name, ctx) for name, ctx in contexts.items()]
        results = await asyncio.gather(*tasks) if tasks else []
        reports = {name: content for name, content in results}

        # CHỈ TRẢ VỀ REPORTS ĐỂ TRƯỞNG KHOA LÀM VIỆC TIẾP
        return {"specialty_reports": reports}
