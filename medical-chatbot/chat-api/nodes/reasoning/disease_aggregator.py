import asyncio
from collections import defaultdict


from core import config
from core.llm_client import get_llm, warn_if_truncated
from core.prompts import DISEASE_AGGREGATOR_PROMPT, INTERMEDIATE_LENGTH_RULE
from core.schemas import RouterState


class DiseaseAggregatorNode:
    """Aggregate document-level reports into disease-level reports."""

    def __init__(self):
        print("⏳ [Disease Aggregator] Initializing...")
        self.llm = get_llm(temperature=0.1)

    async def process(self, state: RouterState):
        query = state.get("query", "")
        document_reports = state.get("document_reports", [])

        if not document_reports:
            return {"disease_reports": []}

        reports_by_disease = defaultdict(list)
        for item in document_reports:
            specialty = (item.get("specialty") or "unknown").strip() or "unknown"
            # Keep exact disease_name from DB as requested (no normalization).
            disease_name = item.get("disease_name") or "khong_xac_dinh"
            reports_by_disease[(specialty, disease_name)].append(item)

        async def aggregate_single_group(group_key, reports):
            specialty, disease_name = group_key
            ranked_reports = sorted(reports, key=lambda x: int(x.get("doc_rank", 0)))
            if len(ranked_reports) == 1:
                # Chỉ một văn bản thì không có gì để gộp: dùng luôn báo cáo văn bản, khỏi gọi LLM viết lại.
                only = ranked_reports[0]
                return {
                    "disease_name": disease_name,
                    "specialty": specialty,
                    "report": only.get("report", ""),
                    "source_document_ids": [str(only.get("document_id", ""))],
                }

            all_reports_text = ""
            source_document_ids = []
            for index, report in enumerate(ranked_reports, start=1):
                document_id = report.get("document_id", "")
                source_document_ids.append(str(document_id))
                all_reports_text += (
                    f"\n--- BÁO CÁO VĂN BẢN {index}"
                    f" | document_id={document_id}"
                    f" | doc_rank={report.get('doc_rank', 0)}"
                    f" ---\n"
                    f"{report.get('report', '')}\n"
                )

            prompt = DISEASE_AGGREGATOR_PROMPT.format(
                disease_name=disease_name,
                specialty=specialty.upper(),
                query=query,
                all_reports_text=all_reports_text,
                length_rule=INTERMEDIATE_LENGTH_RULE.format(max_words=config.INTERMEDIATE_REPORT_MAX_WORDS),
            )

            response = await self.llm.ainvoke(prompt, max_tokens=config.INTERMEDIATE_REPORT_MAX_TOKENS)
            warn_if_truncated(response, f"tổng hợp bệnh {disease_name}")

            return {
                "disease_name": disease_name,
                "specialty": specialty,
                "report": response.content,
                "source_document_ids": source_document_ids,
            }

        tasks = [
            aggregate_single_group(group_key, reports)
            for group_key, reports in reports_by_disease.items()
        ]
        disease_reports = await asyncio.gather(*tasks) if tasks else []

        print(
            "🧩 [Disease Aggregator] "
            f"Đã tổng hợp {len(disease_reports)} báo cáo bệnh từ {len(document_reports)} báo cáo văn bản."
        )
        return {"disease_reports": disease_reports}
