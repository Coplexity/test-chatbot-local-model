import asyncio
from core.llm_client import get_llm
from basic_mode.core.schemas import RouterState
from basic_mode.core.prompts import EXPERT_PROMPT


class DomainExpertsNode:


    def __init__(self):
        print("⏳ [Experts] Initializing Expert Agents...")
        self.llm = get_llm(temperature=0.1)

    async def stream_single_report(self, query: str, domain_name: str, context: str):
        """Stream one specialty report token-by-token for low-latency terminal/UI output."""
        prompt = EXPERT_PROMPT.format(
            domain_name=domain_name.upper(),
            context=context,
            query=query,
            FALLBACK_ANSWER="Trong guidelines không có đủ thông tin để mình có thể trả lời câu hỏi này.",
        )

        async for chunk in self.llm.astream(prompt):
            chunk_text = getattr(chunk, "content", "") or ""
            if chunk_text:
                yield chunk_text

    async def process(self, state: RouterState):
        query = state["query"]
        contexts = state.get("specialty_contexts", {})

        async def generate_single_report(domain_name, context):
            prompt = EXPERT_PROMPT.format(
                domain_name=domain_name.upper(),
                context=context,
                query=query,
                FALLBACK_ANSWER="Trong guidelines không có đủ thông tin để mình có thể trả lời câu hỏi này.",
            )

            res = await self.llm.ainvoke(prompt)
            return domain_name, res.content

        tasks = [generate_single_report(name, ctx) for name, ctx in contexts.items()]
        results = await asyncio.gather(*tasks) if tasks else []
        reports = {name: content for name, content in results}

        # CHỈ TRẢ VỀ REPORTS ĐỂ TRƯỞNG KHOA LÀM VIỆC TIẾP
        return {"specialty_reports": reports}
