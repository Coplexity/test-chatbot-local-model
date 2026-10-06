import asyncio
from langchain_openai import OpenAIEmbeddings
from core import config
from basic_mode.core.schemas import RouterState
from core.database import DatabaseManager


class VectorRetrievalNode:
    def __init__(self):
        print("⏳ [Retriever] Loading Embedding Model...")
        self.embedding_backend = "sentence_transformers"
        self.retrieval_top_k = 10
        self.retrieval_candidate_k = 50
        self.rerank_model_name = "namdp-ptit/ViRanker"
        self.reranker = None

        # Use OpenAI embeddings when an OpenAI embedding model is configured.
        if config.EMBEDDING_MODEL.startswith("text-embedding-"):
            self.embed_model = OpenAIEmbeddings(
                model=config.EMBEDDING_MODEL,
                api_key=config.OPENAI_API_KEY,
            )
            self.embedding_backend = "openai"
        else:
            from sentence_transformers import SentenceTransformer

            self.embed_model = SentenceTransformer(config.EMBEDDING_MODEL)

        if config.RERANKER_ENABLED:
            try:
                from FlagEmbedding import FlagReranker

                print(f"⏳ [Retriever] Loading reranker model: {self.rerank_model_name}...")
                self.reranker = FlagReranker(self.rerank_model_name, use_fp16=False)
            except Exception as e:
                print(f"⚠️ [Retriever] Không thể khởi tạo reranker, fallback về vector-only. Error: {e}")
        else:
            print("ℹ️ [Retriever] Reranker tắt (RERANKER_ENABLED=false), dùng vector-only.")

        self.db_manager = DatabaseManager()

    def _embed_query(self, text: str):
        if self.embedding_backend == "openai":
            return self.embed_model.embed_query(text)
        return self.embed_model.encode(text).tolist()

    def _rerank_rows(self, query: str, rows, top_k: int):
        if not rows:
            return []
        if self.reranker is None:
            return rows[:top_k]

        pairs = []
        for row in rows:
            _, chunk_text, chunk_abstract = row
            candidate_text = f"{chunk_abstract or ''}\n{chunk_text or ''}".strip()
            pairs.append([query, candidate_text[:3000]])

        try:
            scores = self.reranker.compute_score(pairs)
            ranked = sorted(zip(rows, scores), key=lambda x: float(x[1]), reverse=True)
            return [row for row, _ in ranked[:top_k]]
        except Exception as e:
            print(f"⚠️ [Retriever] Rerank thất bại, fallback vector-only. Error: {e}")
            return rows[:top_k]

    async def process(self, state: RouterState):
        query = state.get("query", "")
        hyde_text = state.get("hypothetical_document", "")
        active_version_ids = state.get("active_version_ids", [])
        routed_diseases = state.get("routed_diseases", {})
        domains_data = state.get("analyzed_specialties", [])

        if not active_version_ids:
            print("⚠️ [Retriever] Không có active version để truy xuất.")
            return {
                "specialty_contexts": {},
            }

        print(f"🔍 [Retriever] Đang truy xuất trên {len(active_version_ids)} version active...")
        query_vec = self._embed_query(hyde_text)
        embedding_literal = "[" + ",".join(str(x) for x in query_vec) + "]"

        specialty_list = [spec.get("name") for spec in domains_data if spec.get("name")]

        if not specialty_list:
            specialty_list = list(routed_diseases.keys())

        # Build disease filter by specialty (all routed diseases are equal).
        disease_filters = {
            domain: set(disease_names)
            for domain, disease_names in routed_diseases.items()
            if disease_names
        }

        def fetch_from_db(domain_name):
            chunk_limit = self.retrieval_candidate_k
            disease_values = sorted(disease_filters.get(domain_name, set()))

            conn = None
            cursor = None
            try:
                conn = self.db_manager.get_connection()
                cursor = conn.cursor()

                if disease_values:
                    cursor.execute(
                        """
                        SELECT
                            c.chunk_id,
                            c.text,
                            c.text_abstract
                        FROM chunks c
                        JOIN guideline_versions gv ON gv.version_id = c.version_id
                        JOIN guidelines g ON g.guideline_id = gv.guideline_id
                        WHERE c.version_id = ANY(%s)
                          AND g.chuyen_khoa = %s
                          AND g.ten_benh = ANY(%s)
                          AND c.embedding IS NOT NULL
                        ORDER BY c.embedding <=> %s::halfvec(3072)
                        LIMIT %s;
                        """,
                        (active_version_ids, domain_name, disease_values, embedding_literal, chunk_limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            c.chunk_id,
                            c.text,
                            c.text_abstract
                        FROM chunks c
                        JOIN guideline_versions gv ON gv.version_id = c.version_id
                        JOIN guidelines g ON g.guideline_id = gv.guideline_id
                        WHERE c.version_id = ANY(%s)
                          AND g.chuyen_khoa = %s
                          AND c.embedding IS NOT NULL
                        ORDER BY c.embedding <=> %s::halfvec(3072)
                        LIMIT %s;
                        """,
                        (active_version_ids, domain_name, embedding_literal, chunk_limit),
                    )

                return domain_name, cursor.fetchall()
            except Exception as e:
                print(f"❌ [Retriever DB Error] {domain_name}: {e}")
                return domain_name, []
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        tasks = [asyncio.to_thread(fetch_from_db, domain) for domain in specialty_list]
        results = await asyncio.gather(*tasks) if tasks else []

        specialty_contexts = {}
        for domain_name, rows in results:
            if not rows:
                continue

            rerank_query = (query or "").strip() or hyde_text
            # Chạy trong thread để rerank (CPU-bound) không chặn event loop của các request khác.
            selected_rows = await asyncio.to_thread(
                self._rerank_rows, rerank_query, rows, self.retrieval_top_k
            )

            formatted_chunks = []
            for row in selected_rows:
                chunk_id, chunk_text, chunk_abstract = row
                # Use stable chunk_id as citation reference so IDs are durable for audit.
                ref_id = f"[{str(chunk_id)}]"
                abstract_part = f"\nTÓM TẮT: {chunk_abstract}" if chunk_abstract else ""
                formatted_chunks.append(f"{ref_id}{abstract_part}\nNỘI DUNG: {chunk_text}")
            specialty_contexts[domain_name] = "\n\n".join(formatted_chunks)

        return {
            "specialty_contexts": specialty_contexts,
        }
