import re
from core.llm_client import get_llm
from core.schemas import RouterState
from core.prompts import SYNTHESIZER_PROMPT
from nodes.reasoning.citation_transformer import CitationStreamTransformer


class GlobalSynthesizerNode:
    """Class tổng hợp dữ liệu, tích hợp cơ chế Smart Bypass để tối ưu chi phí"""

    def __init__(self):
        print("⏳ [Synthesizer] Initializing Global Synthesizer...")
        self.llm = get_llm(temperature=0.1)

    @staticmethod
    def _stream_tokens(text):
        tokens = re.findall(r"\S+\s*", text or "")
        return tokens if tokens else [text or ""]

    async def stream_process(self, state: RouterState):
        """Stream final response chunks, transforming source tags incrementally."""
        query = state["query"]
        reports = state.get("specialty_reports", {})
        specialty_report_items = state.get("specialty_report_items", [])
        disease_reports = state.get("disease_reports", [])
        document_reports = state.get("document_reports", [])
        transformer = CitationStreamTransformer()

        if not reports and not specialty_report_items and not disease_reports and not document_reports:
            fallback = (
                "### Kết luận sơ bộ\n"
                "- Tôi chưa đủ thông tin để định vị chính xác vấn đề của bạn.\n"
                "\n"
                "### Bạn có thể bổ sung\n"
                "- Triệu chứng chính (đau ở đâu, mức độ, thời gian kéo dài).\n"
                "- Dấu hiệu đi kèm (sốt, nôn, khó thở, phát ban...).\n"
                "- Tiền sử bệnh và thuốc đang dùng (nếu có)."
            )
            for token in self._stream_tokens(fallback):
                delta = transformer.feed(token)
                if delta:
                    yield delta
            tail = transformer.flush()
            if tail:
                yield tail
            return

        stream_count = (
            len(specialty_report_items)
            or len(reports)
            or len(disease_reports)
            or len(document_reports)
        )
        print(f"🧬 [Global Synthesizer] Merging {stream_count} data streams...")
        all_reports_text = ""
        # Nhóm chỉ có một báo cáo được chuyển thẳng lên tầng trên, nên cùng một nội dung có thể xuất hiện
        # ở cả tầng chuyên khoa, bệnh và văn bản. Chỉ đưa mỗi nội dung vào prompt một lần.
        seen_contents = set()

        def is_new(content):
            key = (content or "").strip()
            if not key or key in seen_contents:
                return False
            seen_contents.add(key)
            return True

        if specialty_report_items:
            for item in specialty_report_items:
                specialty = (item.get("specialty") or "unknown").upper()
                disease_names = item.get("disease_names") or []
                content = item.get("report") or ""
                if not is_new(content):
                    continue
                all_reports_text += (
                    f"\n=== TỔNG HỢP CHUYÊN KHOA {specialty}"
                    f" | diseases={disease_names} ===\n{content}\n"
                )

        if disease_reports:
            for item in disease_reports:
                specialty = (item.get("specialty") or "unknown").upper()
                disease_name = item.get("disease_name") or "không rõ"
                source_document_ids = item.get("source_document_ids") or []
                content = item.get("report") or ""
                if not is_new(content):
                    continue
                all_reports_text += (
                    f"\n--- TỔNG HỢP BỆNH | specialty={specialty}"
                    f" | disease_name={disease_name}"
                    f" | source_document_ids={source_document_ids} ---\n{content}\n"
                )

        if document_reports:
            for item in document_reports:
                specialty = (item.get("specialty") or "unknown").upper()
                document_id = item.get("document_id") or "unknown"
                disease_name = item.get("disease_name") or "không rõ"
                doc_rank = item.get("doc_rank")
                content = item.get("report") or ""
                if not is_new(content):
                    continue
                all_reports_text += (
                    f"\n--- BÁO CÁO TỪ KHOA {specialty} | document_id={document_id}"
                    f" | benh={disease_name} | doc_rank={doc_rank}"
                    f" ---\n{content}\n"
                )

        if reports and not specialty_report_items:
            for domain, content in reports.items():
                if not is_new(content):
                    continue
                all_reports_text += f"\n--- BÁO CÁO TỪ KHOA {domain.upper()} ---\n{content}\n"

        prompt = SYNTHESIZER_PROMPT.format(
            all_reports_text=all_reports_text,
            query=query,
        )

        async for chunk in self.llm.astream(prompt):
            chunk_text = getattr(chunk, "content", "") or ""
            if not chunk_text:
                continue
            delta = transformer.feed(chunk_text)
            if delta:
                yield delta

        tail = transformer.flush()
        if tail:
            yield tail

    def process(self, state: RouterState):
        raise RuntimeError(
            "Non-stream mode has been disabled. Use stream_process(...) instead."
        )