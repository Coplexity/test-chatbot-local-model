import asyncio
from collections import defaultdict
import math
from langchain_openai import OpenAIEmbeddings
from core import config
from core.schemas import RouterState
from core.database import DatabaseManager


class VectorRetrievalNode:
    def __init__(self):
        print("⏳ [Retriever] Loading Embedding Model...")
        self.embedding_backend = "sentence_transformers"
        # Số chunk tối đa mỗi văn bản và số văn bản tối đa mỗi chuyên khoa: chỉnh qua .env.
        self.retrieval_top_k = config.RETRIEVAL_DEEP_TOP_K
        self.retrieval_candidate_k = 30
        self.document_limit_per_specialty = config.RETRIEVAL_DEEP_DOCUMENT_LIMIT
        # Số dòng ứng viên lấy từ DB mỗi chuyên khoa, giữ như bản gốc (10 văn bản x 30) và không gắn với
        # document_limit_per_specialty: lấy ít hơn thì văn bản xếp sau có thể thiếu chunk dù vẫn được chọn.
        self.candidate_row_limit = 10 * self.retrieval_candidate_k
        # Keep only chunks whose vector distance to query is good enough.
        # Lower distance means more relevant.
        self.max_chunk_semantic_distance = 0.65
        # Keep top relative chunk set (per document) after rerank.
        # Example: 0.7 means keep top 70% reranked chunks.
        self.rerank_keep_percentile = 0.7
        # Keep a small minimum from the already distance-filtered set
        # so context is not too sparse for downstream reasoning.
        self.rerank_min_keep = 2
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

        try:
            from FlagEmbedding import FlagReranker

            print(f"⏳ [Retriever] Loading reranker model: {self.rerank_model_name}...")
            self.reranker = FlagReranker(self.rerank_model_name, use_fp16=False)
        except Exception as e:
            print(f"⚠️ [Retriever] Không thể khởi tạo reranker, fallback về vector-only. Error: {e}")

        self.db_manager = DatabaseManager()

    def _embed_query(self, text: str):
        if self.embedding_backend == "openai":
            return self.embed_model.embed_query(text)
        return self.embed_model.encode(text).tolist()

    def _rerank_rows(self, query: str, rows):
        if not rows:
            return []
        if self.reranker is None:
            ranked = sorted(rows, key=lambda x: float(x[3]))
            return [(row, 1.0 / (1.0 + max(0.0, float(row[3])))) for row in ranked]

        pairs = []
        for row in rows:
            _, chunk_text, chunk_abstract, _ = row
            candidate_text = f"{chunk_abstract or ''}\n{chunk_text or ''}".strip()
            pairs.append([query, candidate_text[:3000]])

        try:
            scores = self.reranker.compute_score(pairs)
            ranked = sorted(zip(rows, scores), key=lambda x: float(x[1]), reverse=True)
            return [(row, float(score)) for row, score in ranked]
        except Exception as e:
            print(f"⚠️ [Retriever] Rerank thất bại, fallback vector-only. Error: {e}")
            ranked = sorted(rows, key=lambda x: float(x[3]))
            return [(row, 1.0 / (1.0 + max(0.0, float(row[3])))) for row in ranked]

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
                "document_contexts": [],
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
            disease_values = sorted(disease_filters.get(domain_name, set()))

            conn = None
            cursor = None
            try:
                conn = self.db_manager.get_connection()
                cursor = conn.cursor()

                if disease_values:
                    cursor.execute(
                        """
                        WITH ranked_chunks AS (
                            SELECT
                                c.chunk_id,
                                c.text,
                                c.text_abstract,
                                gv.version_id,
                                g.ten_benh,
                                (c.embedding <=> %s::halfvec(3072)) AS semantic_distance,
                                ROW_NUMBER() OVER (
                                    PARTITION BY gv.version_id
                                    ORDER BY c.embedding <=> %s::halfvec(3072)
                                ) AS rank_in_document
                            FROM chunks c
                            JOIN guideline_versions gv ON gv.version_id = c.version_id
                            JOIN guidelines g ON g.guideline_id = gv.guideline_id
                            WHERE c.version_id = ANY(%s)
                              AND g.chuyen_khoa = %s
                              AND g.ten_benh = ANY(%s)
                              AND c.embedding IS NOT NULL
                        )
                        SELECT
                            chunk_id,
                            text,
                            text_abstract,
                            version_id,
                            ten_benh,
                            semantic_distance
                        FROM ranked_chunks
                        WHERE rank_in_document <= %s
                        ORDER BY semantic_distance
                        LIMIT %s;
                        """,
                        (
                            embedding_literal,
                            embedding_literal,
                            active_version_ids,
                            domain_name,
                            disease_values,
                            self.retrieval_candidate_k,
                            self.candidate_row_limit,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        WITH ranked_chunks AS (
                            SELECT
                                c.chunk_id,
                                c.text,
                                c.text_abstract,
                                gv.version_id,
                                g.ten_benh,
                                (c.embedding <=> %s::halfvec(3072)) AS semantic_distance,
                                ROW_NUMBER() OVER (
                                    PARTITION BY gv.version_id
                                    ORDER BY c.embedding <=> %s::halfvec(3072)
                                ) AS rank_in_document
                            FROM chunks c
                            JOIN guideline_versions gv ON gv.version_id = c.version_id
                            JOIN guidelines g ON g.guideline_id = gv.guideline_id
                            WHERE c.version_id = ANY(%s)
                              AND g.chuyen_khoa = %s
                              AND c.embedding IS NOT NULL
                        )
                        SELECT
                            chunk_id,
                            text,
                            text_abstract,
                            version_id,
                            ten_benh,
                            semantic_distance
                        FROM ranked_chunks
                        WHERE rank_in_document <= %s
                        ORDER BY semantic_distance
                        LIMIT %s;
                        """,
                        (
                            embedding_literal,
                            embedding_literal,
                            active_version_ids,
                            domain_name,
                            self.retrieval_candidate_k,
                            self.candidate_row_limit,
                        ),
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
        document_contexts = []
        for domain_name, rows in results:
            if not rows:
                continue

            rerank_query = (query or "").strip() or hyde_text
            rows_by_document = defaultdict(list)
            for row in rows:
                chunk_id, chunk_text, chunk_abstract, version_id, disease_name, semantic_distance = row
                rows_by_document[(version_id, disease_name)].append(
                    (chunk_id, chunk_text, chunk_abstract, semantic_distance)
                )

            ranked_documents = sorted(
                rows_by_document.items(),
                key=lambda item: min(chunk[-1] for chunk in item[1]),
            )

            for index, ((version_id, disease_name), document_rows) in enumerate(
                ranked_documents[: self.document_limit_per_specialty],
                start=1,
            ):
                # Step 1: hard filter by semantic distance to remove clearly irrelevant chunks.
                distance_filtered_rows = [
                    (chunk_id, chunk_text, chunk_abstract, semantic_distance)
                    for chunk_id, chunk_text, chunk_abstract, semantic_distance in document_rows
                    if float(semantic_distance) <= self.max_chunk_semantic_distance
                ]
                if not distance_filtered_rows:
                    continue

                rerank_input = [
                    (chunk_id, chunk_text, chunk_abstract, semantic_distance)
                    for chunk_id, chunk_text, chunk_abstract, semantic_distance in distance_filtered_rows
                ]
                # Step 2: rerank within the filtered set.
                ranked_rows_with_scores = self._rerank_rows(rerank_query, rerank_input)
                if not ranked_rows_with_scores:
                    continue

                # Step 3: keep top relative set by percentile (no min_keep forcing).
                keep_count = int(math.ceil(len(ranked_rows_with_scores) * self.rerank_keep_percentile))
                keep_count = max(self.rerank_min_keep, keep_count)
                keep_count = min(keep_count, len(ranked_rows_with_scores))
                if keep_count <= 0:
                    continue
                percentile_rows = [row for row, _ in ranked_rows_with_scores[:keep_count]]

                # Final cap to control context size.
                final_rows = percentile_rows[: self.retrieval_top_k]
                if not final_rows:
                    continue

                formatted_chunks = []
                for chunk_id, chunk_text, chunk_abstract, _ in final_rows:
                    # Use stable chunk_id as citation reference so IDs are durable for audit.
                    ref_id = f"[{str(chunk_id)}]"
                    abstract_part = f"\nTÓM TẮT: {chunk_abstract}" if chunk_abstract else ""
                    formatted_chunks.append(f"{ref_id}{abstract_part}\nNỘI DUNG: {chunk_text}")

                context_text = "\n\n".join(formatted_chunks)
                document_id = str(version_id)
                context_key = f"doc:{document_id}:rank:{index}"
                specialty_contexts[context_key] = context_text
                document_contexts.append(
                    {
                        "document_id": document_id,
                        "disease_name": disease_name or "",
                        "specialty": domain_name,
                        "doc_rank": index,
                        "context": context_text,
                    }
                )

        return {
            "specialty_contexts": specialty_contexts,
            "document_contexts": document_contexts,
        }