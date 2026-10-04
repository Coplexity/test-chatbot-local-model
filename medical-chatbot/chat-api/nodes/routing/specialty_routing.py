from core import config
from core.llm_client import get_llm
from core.schemas import RouterState, RouteDecision
from core.prompts import ROUTER_PROMPT
from core.database import DatabaseManager


class SpecialtyRoutingNode:
    """Class đảm nhiệm việc phân tích ý định và định tuyến (Routing)."""

    def __init__(self):
        print("⏳ [Router] Initializing Intent Analyzer...")
        self.llm = get_llm(temperature=0)
        self.db_manager = DatabaseManager()

    def _load_valid_domains(self, guideline_ids=None):
        """Lấy danh sách chuyên khoa từ bảng guidelines, có thể giới hạn theo guideline_ids."""
        if guideline_ids is not None and not guideline_ids:
            return []

        conn = None
        cursor = None
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            guideline_filter_sql = "AND guideline_id = ANY(%s)" if guideline_ids is not None else ""
            params = (guideline_ids,) if guideline_ids is not None else ()
            cursor.execute(
                f"""
                SELECT DISTINCT chuyen_khoa
                FROM guidelines
                WHERE chuyen_khoa IS NOT NULL
                  AND btrim(chuyen_khoa) <> ''
                  {guideline_filter_sql}
                ORDER BY chuyen_khoa;
                """,
                params,
            )
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            print(f"❌ [Router DB Error] Không tải được valid domains: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def process(self, state: RouterState):
        query = state["query"]
        structured_llm = self.llm.with_structured_output(RouteDecision, method=config.LLM_STRUCTURED_OUTPUT_METHOD)

        valid_domains = state.get("filtered_specialties")
        if valid_domains is None:
            valid_domains = self._load_valid_domains(state.get("filtered_guideline_ids"))

        if not valid_domains:
            print("⚠️ [Router] Không tìm thấy chuyên khoa hợp lệ trong guidelines đã lọc.")
            return {"analyzed_specialties": [], "hypothetical_document": ""}

        # Biến danh sách trên thành một chuỗi văn bản (VD: "tim_mach, ho_hap, ...")
        domains_string = ", ".join(valid_domains)

        # GỌI PROMPT TỪ FILE MỚI VÀ TRUYỀN BIẾN VÀO
        prompt = ROUTER_PROMPT.format(
            domains_string=domains_string,
            query=query,
            max_specialties=config.DEEP_MAX_SPECIALTIES,
        )

        decision = structured_llm.invoke(prompt)

        # Bỏ tên trùng trước khi cắt, để một chuyên khoa lặp lại không chiếm chỗ của chuyên khoa khác.
        filtered_domains = [
            {"name": name}
            for name in dict.fromkeys(s.name for s in decision.analyzed_specialties)
            if name in valid_domains
        ]
        if len(filtered_domains) > config.DEEP_MAX_SPECIALTIES:
            # Prompt đã yêu cầu xếp theo mức độ liên quan, nên giữ các chuyên khoa đứng đầu.
            dropped = [s["name"] for s in filtered_domains[config.DEEP_MAX_SPECIALTIES:]]
            print(f"✂️ [Router] Giữ {config.DEEP_MAX_SPECIALTIES} chuyên khoa đầu, bỏ {dropped}.")
            filtered_domains = filtered_domains[: config.DEEP_MAX_SPECIALTIES]

        print(f"🧭 [Router] Điều phối đến các domain: {[s['name'] for s in filtered_domains]}")
        return {"analyzed_specialties": filtered_domains, "hypothetical_document": decision.hypothetical_document}
