import os
from dotenv import load_dotenv

# Load .env nhưng KHÔNG ghi đè environment variables từ Docker/system
load_dotenv(override=False)


def _env(name: str, default: str = "") -> str:
    # Docker compose truyền biến chưa khai báo thành chuỗi rỗng, coi như chưa đặt.
    return (os.getenv(name) or "").strip() or default


# 1. API KEY OPENAI: chỉ còn dùng cho embedding (đọc từ môi trường/.env, không hardcode)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    print("⚠️ CẢNH BÁO: Chưa tìm thấy OPENAI_API_KEY trong file .env hoặc hệ thống!")

# 2. CẤU HÌNH AI MODELS
# LLM sinh văn bản chạy trên Server A (vLLM, OpenAI-compatible). Không fallback sang OpenAI;
# thiếu URL/key sẽ báo lỗi khi tạo client ở core/llm_client.py.
LLM_BASE_URL = _env("LLM_BASE_URL").rstrip("/")
LLM_API_KEY = _env("LLM_API_KEY")
LLM_MODEL = _env("LLM_MODEL", "qwen3.6-27b")
LLM_TIMEOUT_SECONDS = float(_env("LLM_TIMEOUT_SECONDS", "180"))
LLM_MAX_RETRIES = int(_env("LLM_MAX_RETRIES", "0"))
# Context A công bố (input đã serialize + output); dùng để tính ngân sách input.
LLM_CONTEXT_TOKENS = int(_env("LLM_CONTEXT_TOKENS", "65536"))
# Trần output mỗi lần gọi, tính trong context của A.
LLM_MAX_TOKENS = int(_env("LLM_MAX_TOKENS", "4096"))
# Số request LLM đồng thời từ process này; <= 0 là không giới hạn.
LLM_MAX_CONCURRENCY = int(_env("LLM_MAX_CONCURRENCY", "1"))
# "json_schema" hoặc "function_calling"
LLM_STRUCTURED_OUTPUT_METHOD = _env("LLM_STRUCTURED_OUTPUT_METHOD", "json_schema")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

# Retrieval của deep mode: số văn bản tối đa mỗi chuyên khoa và số chunk tối đa mỗi văn bản.
# Mỗi văn bản là một lần gọi LLM riêng, nên hai số này quyết định cả kích thước prompt lẫn thời gian chờ.
RETRIEVAL_DEEP_DOCUMENT_LIMIT = int(_env("RETRIEVAL_DEEP_DOCUMENT_LIMIT", "4"))
RETRIEVAL_DEEP_TOP_K = int(_env("RETRIEVAL_DEEP_TOP_K", "6"))

# 3. DATABASE
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5436"))
DB_NAME = os.getenv("DB_NAME", "guideline_management")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
