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
# Số request LLM đồng thời từ process này; <= 0 là không giới hạn. Đặt bằng MAX_NUM_SEQS của vLLM trên A
# (hiện là 16): để 1 thì các báo cáo expert phải chờ nhau và câu nhiều chuyên khoa vượt 120 giây.
LLM_MAX_CONCURRENCY = int(_env("LLM_MAX_CONCURRENCY", "16"))
# "json_schema" hoặc "function_calling"
LLM_STRUCTURED_OUTPUT_METHOD = _env("LLM_STRUCTURED_OUTPUT_METHOD", "json_schema")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")

# Retrieval của deep mode: số văn bản tối đa mỗi chuyên khoa và số chunk tối đa mỗi văn bản.
# Mỗi văn bản là một lần gọi LLM riêng, nên hai số này quyết định cả kích thước prompt lẫn thời gian chờ.
RETRIEVAL_DEEP_DOCUMENT_LIMIT = max(1, int(_env("RETRIEVAL_DEEP_DOCUMENT_LIMIT", "4")))
RETRIEVAL_DEEP_TOP_K = max(1, int(_env("RETRIEVAL_DEEP_TOP_K", "6")))
# Số chuyên khoa tối đa router của deep mode được chọn. Mỗi chuyên khoa thêm tới
# RETRIEVAL_DEEP_DOCUMENT_LIMIT báo cáo expert, nên đây là con số chính quyết định thời gian tới chữ đầu tiên.
DEEP_MAX_SPECIALTIES = max(1, int(_env("DEEP_MAX_SPECIALTIES", "3")))

# Báo cáo trung gian (expert, tổng hợp bệnh, tổng hợp chuyên khoa) chỉ là đầu vào cho bước sau.
# Prompt yêu cầu tối đa khoảng ngần này từ; trần token = số từ x 4 chỉ để chặn khi model viết quá dài.
INTERMEDIATE_REPORT_MAX_WORDS = max(1, int(_env("INTERMEDIATE_REPORT_MAX_WORDS", "300")))
# Không vượt LLM_MAX_TOKENS: ngân sách input chỉ chừa chỗ cho chừng ấy token output.
INTERMEDIATE_REPORT_MAX_TOKENS = min(INTERMEDIATE_REPORT_MAX_WORDS * 4, LLM_MAX_TOKENS)

# 3. DATABASE
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5436"))
DB_NAME = os.getenv("DB_NAME", "guideline_management")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
