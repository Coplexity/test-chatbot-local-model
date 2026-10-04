import asyncio
from core import config
from core.llm_client import get_llm
from core.schemas import RouterState, SpecialtyDiseaseDecision
from core.prompts import DISEASE_ROUTING_PROMPT
from core.database import DatabaseManager


class DiseaseRoutingNode:
    """Node định tuyến bệnh theo ten_benh từ database."""

    def __init__(self):
        print("⏳ [Disease Router] Initializing...")
        self.llm = get_llm(temperature=0)
        self.db_manager = DatabaseManager()

    def _load_disease_candidates(self, specialty_name: str, guideline_ids=None):
        conn = None
        cursor = None
        try:
            if not specialty_name:
                return []
            if guideline_ids is not None and not guideline_ids:
                return []

            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            guideline_filter_sql = "AND guideline_id = ANY(%s)" if guideline_ids is not None else ""
            params = [specialty_name]
            if guideline_ids is not None:
                params.append(guideline_ids)
            cursor.execute(
                f"""
                SELECT DISTINCT ten_benh
                FROM guidelines
                WHERE chuyen_khoa = %s
                  AND ten_benh IS NOT NULL
                  AND btrim(ten_benh) <> ''
                  {guideline_filter_sql}
                ORDER BY ten_benh;
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            print(f"❌ [Disease Router DB Error] {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    async def process(self, state: RouterState):
        query = state.get("query", "")
        analyzed_specialties = state.get("analyzed_specialties", [])
        filtered_guideline_ids = state.get("filtered_guideline_ids")

        specialty_names = [item.get("name") for item in analyzed_specialties if item.get("name")]
        specialty_names = list(dict.fromkeys(specialty_names))

        if not specialty_names:
            return {
                "routed_diseases": {},
            }

        async def route_single_specialty(specialty_name: str):
            candidates = self._load_disease_candidates(specialty_name, filtered_guideline_ids)
            if not candidates:
                print(f"⚠️ [Disease Router] Không có ứng viên bệnh cho khoa {specialty_name}.")
                return specialty_name, []

            candidates_string = "\n".join([f"- {specialty_name}: {disease}" for disease in candidates])
            prompt = DISEASE_ROUTING_PROMPT.format(
                specialties_string=specialty_name,
                candidates_string=candidates_string,
                query=query,
            )

            structured_llm = self.llm.with_structured_output(SpecialtyDiseaseDecision, method=config.LLM_STRUCTURED_OUTPUT_METHOD)
            try:
                decision = await structured_llm.ainvoke(prompt)
                # So khớp sau khi bỏ khoảng trắng hai đầu, nhưng trả về đúng giá trị trong DB
                # vì retrieval lọc bằng ten_benh = ANY(...) chính xác từng ký tự.
                valid_diseases = {disease.strip(): disease for disease in candidates}
                selected = []
                seen = set()

                for raw_name in decision.ten_benh:
                    # Qwen có thể chép cả dòng ứng viên dạng "- <chuyên khoa>: <bệnh>"
                    disease_name = (raw_name or "").strip().removeprefix("- ").strip()
                    disease_name = disease_name.removeprefix(f"{specialty_name}:").strip()
                    db_name = valid_diseases.get(disease_name)
                    if db_name is not None and db_name not in seen:
                        seen.add(db_name)
                        selected.append(db_name)

                if not selected:
                    print(f"⚠️ [Disease Router] {specialty_name}: LLM không trả bệnh hợp lệ, fallback về candidates DB.")
                    return specialty_name, candidates

                return specialty_name, selected
            except Exception as e:
                print(f"❌ [Disease Router Error] {specialty_name}: {e}")
                return specialty_name, candidates

        tasks = [route_single_specialty(name) for name in specialty_names]
        results = await asyncio.gather(*tasks) if tasks else []

        grouped_diseases = {specialty: diseases for specialty, diseases in results if diseases}

        if not grouped_diseases:
            print("⚠️ [Disease Router] Không route được bệnh hợp lệ từ tất cả chuyên khoa.")
            return {"routed_diseases": {}}

        total_diseases = sum(len(diseases) for diseases in grouped_diseases.values())
        print(f"🎯 [Disease Router] Tổng số bệnh route được: {total_diseases}")
        return {
            "routed_diseases": grouped_diseases,
        }
