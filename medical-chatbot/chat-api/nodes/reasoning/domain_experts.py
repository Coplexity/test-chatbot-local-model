import asyncio
from core.llm_client import get_llm
from core.schemas import RouterState
from core.prompts import EXPERT_PROMPT

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

    @staticmethod
    def _fallback_document_contexts(state: RouterState):
        contexts = state.get("specialty_contexts", {})
        fallback_docs = []
        for index, (name, context) in enumerate(contexts.items(), start=1):
            fallback_docs.append(
                {
                    "document_id": f"legacy-{index}",
                    "disease_name": "",
                    "specialty": name,
                    "doc_rank": index,
                    "context": context,
                }
            )
        return fallback_docs

    async def process(self, state: RouterState):
        query = state["query"]
        document_contexts = state.get("document_contexts", [])
        if not document_contexts:
            document_contexts = self._fallback_document_contexts(state)

        async def generate_single_report(doc):
            domain_name = doc.get("specialty", "")
            context = doc.get("context", "")
            prompt = EXPERT_PROMPT.format(
                domain_name=domain_name.upper(),
                context=context,
                query=query,
                FALLBACK_ANSWER="Trong guidelines không có đủ thông tin để mình có thể trả lời câu hỏi này.",
            )

            res = await self.llm.ainvoke(prompt)
            return {
                "document_id": doc.get("document_id", ""),
                "disease_name": doc.get("disease_name", ""),
                "specialty": domain_name,
                "doc_rank": doc.get("doc_rank", 0),
                "report": res.content,
            }

        tasks = [generate_single_report(doc) for doc in document_contexts]
        results = await asyncio.gather(*tasks) if tasks else []
        reports = {
            f"doc:{item['document_id']}:rank:{item['doc_rank']}": item["report"]
            for item in results
        }

        # CHỈ TRẢ VỀ REPORTS ĐỂ TRƯỞNG KHOA LÀM VIỆC TIẾP
        return {
            "specialty_reports": reports,
            "document_reports": results,
        }