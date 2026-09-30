# Bàn giao: chatbot y khoa dùng Qwen3.6-27B trên Server A

Cập nhật ngày 2026-09-30. Người nhận: anh Triệu.

## 1. Trạng thái hiện tại

- `medical-chatbot/chat-api` đã được sửa để mọi lời gọi sinh văn bản đi tới Qwen3.6-27B trên Server A (vLLM, API kiểu OpenAI Chat Completions) thay cho `gpt-4.1` của OpenAI.
- Embedding vẫn dùng OpenAI `text-embedding-3-large`, nên vẫn cần `OPENAI_API_KEY` và không phải reindex DB.
- NestJS backend, frontend và giao thức SSE tới trình duyệt không đổi.
- **Chưa chạy với Server A thật.** Code mới chỉ được kiểm chứng với một server giả lập API của vLLM (chi tiết ở mục 6). Hai thứ còn thiếu là key của A và đường mạng tới A.
- Chưa deploy ở đâu ngoài máy local của người bàn giao.

Không có secret nào trong repo. File `medical-chatbot/deploy/.env` bị gitignore, phải tạo lại từ `.env.example`.

## 2. Việc cần làm, theo thứ tự

1. Mở đường mạng từ máy deploy tới Server A (mục 4).
2. Tạo `medical-chatbot/deploy/.env` từ `.env.example` và điền các giá trị ở mục 3.
3. Chuẩn bị database guideline mà web mới sẽ dùng (mục 5.1).
4. Build và chạy stack (mục 5.2).
5. Chạy kiểm tra kết nối LLM, rồi thử basic và deep trên giao diện (mục 6).

## 3. Thông tin cần điền trong `medical-chatbot/deploy/.env`

```bash
cd medical-chatbot
cp deploy/.env.example deploy/.env
```

| Biến | Cần điền gì | Lấy ở đâu |
| --- | --- | --- |
| `LLM_BASE_URL` | URL tới vLLM, kết thúc bằng `/v1`, truy cập được **từ bên trong container `chat-api`** | Tùy đường mạng, xem mục 4 |
| `LLM_API_KEY` | Bearer key của Server A | Nội dung file `.api-key` trong thư mục `llm` trên A, bàn giao riêng |
| `OPENAI_API_KEY` | Key OpenAI, chỉ dùng cho embedding | Tài khoản OpenAI của dự án |
| `JWT_SECRET` | Chuỗi bí mật mới cho web mới | Tự sinh, ví dụ `openssl rand -hex 32` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS` | Kết nối tới database guideline | Xem mục 5.1 |
| `DB_SYNCHRONIZE` | `true` ở lần chạy đầu để NestJS tự tạo bảng, sau đó `false` | Biến này chưa có trong `.env.example`, cần thêm tay |
| `FRONTEND_PORT` | Cổng public của web mới, mặc định `8400` | Chọn cổng chưa dùng trên máy deploy |
| `VITE_DOCUMENT_FILE_URL_TEMPLATE` | URL mở file tài liệu, giữ nguyên `{documentId}` | Địa chỉ public của guideline backend |
| `VITE_BACKEND_URL`, `CHAT_API_URL` | Để trống nếu project compose tên `medical-chatbot`; nếu đổi tên project thì phải điền | Xem mục 5.3 |

Các biến `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_MAX_TOKENS`, `LLM_MAX_CONCURRENCY`, `LLM_STRUCTURED_OUTPUT_METHOD` đã có giá trị mặc định dùng được trong `.env.example`.

Thiếu `LLM_BASE_URL` hoặc `LLM_API_KEY` thì `chat-api` dừng ngay lúc khởi động với lỗi `Thiếu cấu hình LLM: ...` và container restart liên tục. Đây là chủ ý: không có đường fallback sang OpenAI.

## 4. Đường mạng tới Server A

Server A hiện chỉ listen `127.0.0.1:8000` và chưa mở cho máy nào khác. Cần chọn một trong hai cách.

**Cách 1: IP nội bộ hoặc VPN (nên dùng cho bản deploy).** Trên A, đổi `HOST` trong `.env` của thư mục `llm` sang IP nội bộ, mở cổng 8000 cho riêng máy deploy, rồi khởi động lại `serve.sh`. Khi đó:

```dotenv
LLM_BASE_URL=http://<IP_NOI_BO_A>:8000/v1
```

Lần nạp model đầu tiên trên A từng mất khoảng 40 phút, nên cần lên lịch restart. HTTP thuần không mã hóa key và prompt; chỉ dùng trong mạng riêng hoặc VPN tin cậy.

**Cách 2: SSH tunnel (nhanh để thử, không cần sửa gì trên A).** Trên máy deploy:

```bash
ssh -N -L 8001:127.0.0.1:8000 <user>@<server-a>
```

```dotenv
LLM_BASE_URL=http://host.docker.internal:8001/v1
```

Cách này đã thử được trên Docker Desktop (macOS): container gọi tới cổng loopback của máy host qua `host.docker.internal`. Trên Linux thì **chưa thử** và cần thêm hai việc:

- Thêm `extra_hosts: ["host.docker.internal:host-gateway"]` vào service `chat-api` trong compose.
- Cho tunnel listen trên địa chỉ mà container tới được (ví dụ `-L 172.17.0.1:8001:127.0.0.1:8000`), vì `127.0.0.1` của host không truy cập được từ bridge network.

Tunnel không tự phục hồi khi đứt, nên không phù hợp để chạy lâu dài.

## 5. Deploy

### 5.1. Database

`chat-api` và `chat-backend` cùng dùng database `guideline_management` của `ai_documents_management` (PostgreSQL + pgvector). Web mới có hai lựa chọn:

- Dùng chung database đang có: trỏ `DB_*` tới database đó.
- Dựng database mới: chạy `docker compose up -d db` trong `ai_documents_management`, rồi nạp guideline qua guideline backend. Pipeline nạp tài liệu của `ai_documents_management` **vẫn dùng OpenAI** (`gpt-4.1` và embedding), không liên quan tới Server A.

Database trống thì chatbot vẫn chạy nhưng không có tài liệu để trả lời.

### 5.2. Build và chạy

```bash
docker network create chatbot-db
```

```bash
cd medical-chatbot/deploy
docker compose up -d --build
```

Các bước chi tiết và cách xử lý lỗi thường gặp: [medical-chatbot/LOCAL_RUNBOOK.md](medical-chatbot/LOCAL_RUNBOOK.md).

Code `chat-api` được copy vào image, nên mỗi lần sửa code phải build lại (`docker compose up -d --build chat-api`). Chỉ sửa `.env` thì recreate là đủ (`docker compose up -d --no-build --force-recreate chat-api`).

### 5.3. Chạy web mới song song với web cũ trên cùng máy

Phần này là lưu ý từ việc đọc file compose, **chưa chạy thử**.

- File compose đặt sẵn tên project là `medical-chatbot`. Chạy instance thứ hai trên cùng máy phải đổi tên project (`docker compose -p <ten-moi> ...`) và đổi `FRONTEND_PORT`.
- Hai URL nội bộ mặc định chứa tên project cũ. Khi đổi tên project phải điền lại trong `.env`:

```dotenv
CHAT_API_URL=http://<ten-moi>-chat-api-1:8000
VITE_BACKEND_URL=http://<ten-moi>-chat-backend-1:3000
```

- Nên dùng tên container như trên thay vì tên service (`chat-api`, `chat-backend`): cả hai instance cùng gắn vào network ngoài `chatbot-db`, nên tên service có thể phân giải nhầm sang instance kia.

## 6. Kiểm tra sau khi deploy

Kiểm tra kết nối LLM từ bên trong container, dùng chính client của ứng dụng:

```bash
cd medical-chatbot/deploy
docker compose exec chat-api python -m scripts.check_llm
```

Script chạy 9 bước: key sai bị từ chối, alias model, chat thường, trần output, streaming, 3 schema thật của các node routing/validator, và request song song. Kết quả đạt là dòng cuối `LLM_CHECK_COMPLETE`. Cách đọc lỗi:

| Dấu hiệu | Nguyên nhân thường gặp |
| --- | --- |
| `Connection refused` hoặc timeout | Đường mạng tới A chưa thông, hoặc vLLM trên A chưa chạy |
| HTTP 401 ở bước `model alias` | `LLM_API_KEY` sai |
| `không thấy alias` | `LLM_MODEL` không khớp alias A đang phục vụ (`qwen3.6-27b`) |
| Lỗi ở các bước `structured output` | Thử đổi `LLM_STRUCTURED_OUTPUT_METHOD=function_calling` rồi recreate `chat-api` |

Sau đó mở web và hỏi một câu y khoa ở cả hai chế độ basic và deep. Nếu câu hỏi dừng ở bước "Truy xuất" với lỗi 401 của OpenAI thì vấn đề nằm ở `OPENAI_API_KEY`, không phải Server A.

**Đã kiểm chứng với server giả lập:**

- Cả 9 bước của script đều qua, ở cả hai chế độ `json_schema` và `function_calling`.
- Request gửi đi khớp [API contract](Tai%20lieu%20cho%20local%20model%20mới/API_CONTRACT.md): model alias, `chat_template_kwargs.enable_thinking=false` ở top level, `stream_options.include_usage`, `response_format` kiểu `json_schema` với `strict: true`.
- Chế độ basic chạy trọn luồng với database và embedding thật, stream ra đúng định dạng.

**Chưa kiểm chứng:**

- Bất kỳ request nào tới Server A thật.
- Các node experts, aggregator và synthesizer của chế độ deep qua luồng ứng dụng: dữ liệu giả không truy xuất được văn bản nào nên luồng rẽ sang câu trả lời mặc định.
- Chất lượng câu trả lời y khoa, trích dẫn, độ trễ và tải đồng thời.

## 7. Thay đổi trong repo

| File | Thay đổi |
| --- | --- |
| `medical-chatbot/chat-api/core/config.py` | Đọc các biến `LLM_*` mới |
| `medical-chatbot/chat-api/core/llm_client.py` (mới) | Factory `get_llm(temperature)`: trỏ tới A, tắt thinking, timeout, trần output, giới hạn đồng thời, báo lỗi khi thiếu cấu hình |
| 12 file node trong `nodes/` và `basic_mode/nodes/` | Dùng factory thay cho `ChatOpenAI(...)` trực tiếp; 6 chỗ structured output chỉ định rõ method |
| `medical-chatbot/chat-api/scripts/check_llm.py` (mới) | Script kiểm tra ở mục 6 |
| `medical-chatbot/deploy/docker-compose.yml`, `dev-compose.yml` | Truyền biến `LLM_*` vào service `chat-api` |
| `medical-chatbot/deploy/.env.example` | Thêm biến mới, bỏ `LLM_MODEL=gpt-4.1` |
| `medical-chatbot/LOCAL_RUNBOOK.md` | Thêm mục 4.1 (kết nối Server A), bước kiểm tra LLM, xử lý lỗi |
| `medical-chatbot/chat-api/Dockerfile`, `requirements.txt` | Bỏ `streamlit`, `sentence-transformers`, `FlagEmbedding` để image nhẹ |
| `ai_documents_management/web/src/lib/api.ts`, `pages/InsertPage.tsx` | Sửa nhỏ ở web quản lý guideline: không redirect khi đăng nhập sai, thêm lựa chọn trống cho ô tài khoản sở hữu |

## 8. Chưa làm và rủi ro đã biết

Các mục dưới đây nằm trong kế hoạch tích hợp của [HANDOVER.md](Tai%20lieu%20cho%20local%20model%20mới/HANDOVER.md) nhưng chưa thực hiện.

- **Chưa đếm token bằng tokenizer Qwen.** Không có bước cắt bớt context trước khi gọi A. Ở một câu hỏi thử, prompt của node expert dài khoảng 66.000 ký tự; chưa đo xem nó chiếm bao nhiêu trong context 65536 token (trừ 4096 token output). Nếu A trả lỗi 400 về context thì đây là chỗ cần xem đầu tiên.
- **Timeout 180 giây** là con số của smoke test ngắn trên A, chưa phải mức phù hợp cho chế độ deep. Tăng bằng `LLM_TIMEOUT_SECONDS`.
- **Giới hạn đồng thời chỉ có hiệu lực trong một process** và chỉ với các lời gọi async (experts, aggregator, synthesizer). Validator và router gọi kiểu sync, nên khi có nhiều người dùng cùng lúc A vẫn có thể nhận hơn 1 request và tự xếp hàng.
- **Chưa lưu usage theo từng node** và chưa xử lý riêng trường hợp `finish_reason=length` cho các câu trả lời dạng văn bản (câu trả lời có thể bị cắt ở 4096 token mà không báo).
- **Reranker không có trong image.** `FlagEmbedding` đã bị bỏ khỏi `requirements.txt`, nên retrieval chỉ xếp hạng theo khoảng cách vector. Log khởi động có dòng cảnh báo tương ứng.
- **Dependency không ghim phiên bản.** Image dùng để kiểm chứng có `langchain-openai 1.6.6` và `openai 3.22.1`; build lại sau này có thể kéo bản mới hơn.
- **Thiếu `core/query_rewriter.py`.** HANDOVER liệt kê 13 điểm gọi LLM, repo này chỉ có 12. Bản source trên máy Server A có thể mới hơn repo này.
- **Pipeline nạp tài liệu** trong `ai_documents_management` vẫn dùng OpenAI.

## 9. Tài liệu liên quan

- [Tai lieu cho local model mới/README.md](Tai%20lieu%20cho%20local%20model%20mới/README.md): cách vận hành vLLM trên Server A.
- [Tai lieu cho local model mới/HANDOVER.md](Tai%20lieu%20cho%20local%20model%20mới/HANDOVER.md): những gì đã xong trên A và kế hoạch tích hợp đầy đủ trên B.
- [Tai lieu cho local model mới/API_CONTRACT.md](Tai%20lieu%20cho%20local%20model%20mới/API_CONTRACT.md): hợp đồng API B → A.
- [medical-chatbot/LOCAL_RUNBOOK.md](medical-chatbot/LOCAL_RUNBOOK.md): chạy local từng bước.
