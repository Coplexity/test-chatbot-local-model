import asyncio
from collections import defaultdict


from core.llm_client import get_llm
from core.prompts import SPECIALTY_AGGREGATOR_PROMPT
from core.schemas import RouterState


class SpecialtyAggregatorNode:
    """Aggregate disease-level reports into specialty-level reports."""

    def __init__(self):
        print("⏳ [Specialty Aggregator] Initializing...")
        self.llm = get_llm(temperature=0.1)

    async def process(self, state: RouterState):
        query = state.get("query", "")
        disease_reports = state.get("disease_reports", [])

        if not disease_reports:
            return {"specialty_reports": {}, "specialty_report_items": []}

        reports_by_specialty = defaultdict(list)
        for item in disease_reports:
            specialty = (item.get("specialty") or "unknown").strip() or "unknown"
            reports_by_specialty[specialty].append(item)

        async def aggregate_single_specialty(specialty, reports):
            ranked_reports = sorted(reports, key=lambda x: (x.get("disease_name") or ""))

            all_disease_reports_text = ""
            disease_names = []
            for index, report in enumerate(ranked_reports, start=1):
                disease_name = report.get("disease_name", "")
                disease_names.append(disease_name)
                all_disease_reports_text += (
                    f"\n--- BÁO CÁO BỆNH {index}"
                    f" | disease_name={disease_name}"
                    f" | source_document_ids={report.get('source_document_ids', [])} ---\n"
                    f"{report.get('report', '')}\n"
                )

            prompt = SPECIALTY_AGGREGATOR_PROMPT.format(
                specialty=specialty.upper(),
                query=query,
                all_disease_reports_text=all_disease_reports_text,
            )
            response = await self.llm.ainvoke(prompt)

            report_item = {
                "specialty": specialty,
                "report": response.content,
                "disease_names": list(dict.fromkeys(disease_names)),
            }
            return specialty, report_item

        tasks = [
            aggregate_single_specialty(specialty, reports)
            for specialty, reports in reports_by_specialty.items()
        ]
        results = await asyncio.gather(*tasks) if tasks else []

        specialty_report_items = [item for _, item in results]

        specialty_reports = {
            item["specialty"]: item["report"]
            for item in specialty_report_items
        }

        print(
            "🏥 [Specialty Aggregator] "
            f"Đã tổng hợp {len(specialty_report_items)} báo cáo chuyên khoa từ {len(disease_reports)} báo cáo bệnh."
        )
        return {
            "specialty_reports": specialty_reports,
            "specialty_report_items": specialty_report_items,
        }
