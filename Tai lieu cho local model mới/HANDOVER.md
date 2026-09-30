# Bàn giao Server A và kế hoạch tích hợp Server B

Cập nhật ngày 2026-09-29. Xem [API contract chi tiết](API_CONTRACT.md).
Các mục “cần làm” trên B là kế hoạch, chưa phải thay đổi đã triển khai.

## 1. Kiến trúc đã chốt

```text
SERVER B                                             SERVER A
Frontend → NestJS → FastAPI chat-api ── HTTP /v1 ──→ vLLM → Qwen3.6-27B
             │           │                              H100 PCIe
             │           ├─ basic/deep, LangGraph
             │           ├─ query rewrite, routing, experts, synthesis
             │           ├─ retrieval + reranker
             └───────────┴─ PostgreSQL, history, usage, guideline data
                         └─ OpenAI embeddings (giữ riêng)
```

A chỉ sinh văn bản/structured output từ messages B gửi. B giữ RAG, prompt,
lịch sử, phân quyền dữ liệu, trích dẫn, điều phối agents, lưu kết quả và SSE
cho frontend. Một lượt chat có thể gọi A nhiều lần. A không tự truy vấn DB,
lấy tài liệu hoặc chạy function mà model đề xuất qua tool calling.

## 2. Những gì đã hoàn thành trên A

| Hạng mục | Kết quả |
| --- | --- |
| Thư mục code | `/home/nvidia-lab/ai4life/nmkhoi/chatbot/medical-chatbot-source-2/llm` |
| Trọng số local | `/home/nvidia-lab/data_mount/nmk/chatbot/Qwen3.6-27B`, người dùng đã tải xong |
| GPU | Một NVIDIA H100 PCIe, tổng 81559 MiB |
| Conda riêng | `llm/.conda`, Python 3.12.14; không cài vào Conda base |
| Serving | vLLM 0.19.0, PyTorch 2.10.0+cu128 |
| Client kiểm thử | langchain-openai 1.6.6 |
| Hệ thống | Giữ nguyên driver 535.309.01 và CUDA hệ thống, không nâng driver |
| Model alias | `qwen3.6-27b` |
| Xác thực | Bearer key riêng trong `.api-key`, không dùng key OpenAI embedding |
| Chạy nền | `serve.sh` trong tmux `qwen-server-a` |
| Logging | `logs/server-<UTC>.log`, smoke log khi dùng `tee` |

`nvidia-smi` báo CUDA 12.2 không có nghĩa PyTorch dùng runtime 12.2.
Môi trường cài PyTorch cu128; GPU probe thực tế đã thành công.
Các dependency trực tiếp đã ghim; chưa có lockfile đầy đủ cho dependency gián tiếp.

### Cấu hình đang dùng

```dotenv
MODEL_PATH=/home/nvidia-lab/data_mount/nmk/chatbot/Qwen3.6-27B
SERVED_MODEL_NAME=qwen3.6-27b
HOST=127.0.0.1
PORT=8000
CUDA_VISIBLE_DEVICES=0
TENSOR_PARALLEL_SIZE=1
DTYPE=bfloat16
MAX_MODEL_LEN=65536
MAX_NUM_SEQS=1
MAX_NUM_BATCHED_TOKENS=2048
GPU_MEMORY_UTILIZATION=0.80
GPU_HEADROOM_MIB=2048
ENABLE_THINKING=false
GDN_PREFILL_BACKEND=triton
CONDA_PREFIX_PATH=.conda
API_KEY_FILE=.api-key
```

Ngân sách vLLM là 80% × 81559 ≈ 65247 MiB, khoảng 63.7 GiB; không phải hard cap
chính xác của toàn bộ tiến trình. Preflight yêu cầu ít nhất 67296 MiB trống,
gồm 2048 MiB dự phòng; kiểm tra không đặt chỗ GPU.
Context hiện tại là **65536**, không phải 262144.
`MAX_NUM_BATCHED_TOKENS=2048` là ngân sách scheduler mỗi iteration, không phải
giới hạn toàn bộ prompt. `MAX_NUM_SEQS=1` không phải HTTP rate limit.

### Vai trò từng file

| File | Chức năng |
| --- | --- |
| `setup.sh`, `requirements.txt` | Tạo/tái sử dụng Conda, cài dependency, tạo cấu hình/key khi thiếu |
| `.env`, `.env.example` | Cấu hình thật và mẫu; file thật không commit |
| `.api-key` | Secret A, quyền 600; bàn giao riêng cho B |
| `runtime.py` | Đọc cấu hình, kiểm tra shard/index/header/size, VRAM, key, executable, cổng |
| `gpu_probe.py` | Kiểm tra BF16 matmul, Triton JIT, vLLM RMSNorm |
| `serve.py` | Preflight rồi chạy vLLM với parser và cấu hình đã chọn |
| `serve.sh` | Khóa chống launcher trùng, ghi log và chạy server |
| `smoke_test.py` | Kiểm tra auth, models, chat, SSE, usage, JSON Schema, LangChain |
| `test_runtime.py` | Các kiểm thử CPU của runtime |
| `.gitignore` | Loại secret, môi trường, log, cache, thư mục tạm khỏi git |

Kiểm tra shard không thay thế checksum toàn bộ trọng số. Preflight không load
model và không xác nhận suy luận. Khi server đang chạy, preflight có thể báo
cổng đang dùng; không dùng preflight làm health check.

### Lỗi đã xử lý

- Cài dependency từng thiếu dung lượng `/tmp`: chuyển vùng tạm sang
  `llm/.install-tmp`, giảm số download đồng thời.
- Lần load trọng số đầu ghi nhận khoảng 39.7 phút, 50.22 GiB bộ nhớ model;
  đây là một lần quan sát, không phải SLA khởi động.
- Chat từng HTTP 500 vì FlashInfer GDN JIT thiếu header `cuda/ptx`.
  Đã chuyển **GDN prefill** sang Triton bằng `GDN_PREFILL_BACKEND=triton`.
  Không chuyển mọi attention backend sang Triton, không nâng driver.
- Smoke test đã thêm đọc error body, giới hạn độ dài và che API key
  để chẩn đoán thay vì chỉ thấy `HTTP Error 500`.

## 3. Bằng chứng kiểm thử và giới hạn

Đã kiểm tra cú pháp Python/shell, 3 test CPU, `pip check` và CLI vLLM.
Người dùng cung cấp kết quả `GPU_PROBE_COMPLETE` và toàn bộ smoke test thành công:

```text
PASS authentication
PASS model alias
PASS non-streaming chat and usage
PASS SSE text, finish reason, usage and [DONE]
PASS JSON schema
PASS LangChain structured output: json_schema
PASS LangChain structured output: function_calling
API_SMOKE_COMPLETE (short requests only; full-context capacity not tested)
```

Người dùng cũng xác nhận gửi prompt và nhận câu trả lời Qwen trực tiếp trên A.
Trong phiên lập tài liệu, kiểm tra live xác nhận:

- `GET /health` không key: HTTP 200, body rỗng.
- `GET /v1/models` không key: HTTP 401, `{"error":"Unauthorized"}`.
- `GET /v1/models` có key: HTTP 200, alias `qwen3.6-27b`, `max_model_len=65536`.

**A đã phục vụ suy luận local với request ngắn.** Chưa nghiệm thu prompt sát
65K, tải đồng thời, chất lượng y khoa, toàn bộ schema RAG, kết nối B→A hoặc
end-to-end frontend. Health/models không thay thế test sinh văn bản.

## 4. Những việc cần làm trên B, theo thứ tự

### Bước 1 — Thiết lập đường mạng tới A

A chỉ listen `127.0.0.1:8000`. Chọn IP nội bộ A và đường mạng B→A, sau đó đổi
HOST sang IP đó và lên lịch restart A. Chỉ cho nguồn B truy cập cổng 8000
theo chính sách mạng. Chưa thay đổi HOST/firewall trong bản bàn giao này.
Dùng mạng riêng/VPN tin cậy hoặc TLS; HTTP thuần không mã hóa key và prompt.

B dùng `http://<IP_NOI_BO_A>:8000/v1`, không dùng `127.0.0.1` hoặc đường dẫn
model trên đĩa. B không khởi chạy thêm Qwen. Với Docker, test từ chính container
`chat-api`, không chỉ từ host B.

### Bước 2 — Tách cấu hình LLM và embedding

Các biến sau là **đề xuất cần bổ sung trên B**, chưa được code B đọc đầy đủ:

```dotenv
LLM_BASE_URL=http://<IP_NOI_BO_A>:8000/v1
LLM_MODEL=qwen3.6-27b
LLM_API_KEY=<SECRET_CUA_A_BAN_GIAO_RIENG>
LLM_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=0
LLM_MAX_CONCURRENCY=1
OPENAI_API_KEY=<KEY_OPENAI_EMBEDDING_HIEN_CO>
EMBEDDING_MODEL=text-embedding-3-large
```

Sửa `medical-chatbot/chat-api/core/config.py` để đọc/validate cấu hình mới;
báo lỗi rõ khi thiếu URL/key thay vì âm thầm gửi LLM sang OpenAI.
Truyền biến mới vào service `chat-api` trong cả
`medical-chatbot/deploy/docker-compose.yml`, `dev-compose.yml`; cập nhật
`medical-chatbot/deploy/.env.example`. Chỉ sửa .env chưa đủ.

Giữ OpenAIEmbeddings và key hiện tại tại
`nodes/retrieval/vector_retrieval.py` và
`basic_mode/nodes/retrieval/vector_retrieval.py` dưới chat-api.
Không đặt `OPENAI_BASE_URL` toàn cục sang A vì A không cung cấp embedding
trong contract này. Không đổi model embedding, dimension hay reindex DB
trong lần chuyển LLM.

### Bước 3 — Tập trung client và thay đủ 13 điểm gọi

Nên thêm factory `core/llm_client.py` dùng URL/key riêng, alias, timeout,
output budget và `enable_thinking=false`. Giữ temperature của từng node.
Các file tương đối dưới `medical-chatbot/chat-api/` đã đối chiếu:

1. `core/query_rewriter.py`
2. `nodes/routing/specialty_routing.py`
3. `nodes/routing/disease_routing.py`
4. `nodes/reasoning/question_validator.py`
5. `nodes/reasoning/domain_experts.py`
6. `nodes/reasoning/disease_aggregator.py`
7. `nodes/reasoning/specialty_aggregator.py`
8. `nodes/reasoning/global_synthesizer.py`
9. `basic_mode/nodes/routing/specialty_routing.py`
10. `basic_mode/nodes/routing/disease_routing.py`
11. `basic_mode/nodes/reasoning/question_validator.py`
12. `basic_mode/nodes/reasoning/domain_experts.py`
13. `basic_mode/nodes/reasoning/global_synthesizer.py`

Chỉ đổi LLM_MODEL chưa chuyển nhà cung cấp: các constructor hiện dùng
config.OPENAI_API_KEY, chưa có base_url. Sau sửa cần tìm lại mọi constructor.
Structured output cần chỉ định method rõ (`json_schema` hoặc `function_calling`),
giữ validation/audit và test schema thật. Schema cộng hai số đã qua không chứng
minh mọi schema nested/union hoạt động.

### Bước 4 — Giới hạn tải, token, timeout và retry

- Bắt đầu tối đa một request LLM đang xử lý từ B. Giới hạn phải có hiệu lực
  trên tổng worker/replica; semaphore mỗi process không tạo giới hạn toàn hệ thống.
- Các nhánh experts song song phải qua giới hạn này; thêm queue limit và timeout.
- Tính input bằng tokenizer Qwen, tính template/history/tools/schema và dành chỗ
  output trong tổng 65536 token. Giới hạn số ký tự hiện tại không đủ.
- Output budget theo node: có thể bắt đầu routing 512–2048, synthesis 2048–4096
  token. Đây là gợi ý cần đo/test, không phải cấu hình đã nghiệm thu.
- 180 giây là timeout đã dùng cho smoke ngắn, không phải SLA deep mode.
  Đồng bộ timeout client, FastAPI, NestJS và reverse proxy.
- Bắt đầu max_retries=0 để thấy lỗi rõ. Retry nếu thêm phải hữu hạn/backoff;
  không retry request sai hoặc nối response mới vào stream đã phát dở.

### Bước 5 — Giữ đúng API ứng dụng, SSE và usage

Không đổi `CHAT_API_URL` của NestJS thành A. NestJS vẫn gọi FastAPI B;
FastAPI mới gọi `/v1/chat/completions` của A. Không đưa key A xuống frontend.
B tiếp tục kiểm tra quyền người dùng và phạm vi tài liệu.

B chuyển chunk vLLM thành sự kiện SSE hiện có, không chuyển nguyên wire protocol
A rồi giả định frontend hiểu. Sự kiện “thinking”/trace workflow B không đồng
nghĩa reasoning nội bộ Qwen.

Lưu usage mỗi lần gọi, tổng hợp rewrite/routing/experts/aggregation/synthesis,
không chỉ lần tổng hợp cuối; không đếm lặp metadata qua các chunk.
Không áp giá GPT-4.1 cho qwen3.6-27b. Chi phí GPU nội bộ là chính sách kế toán riêng,
không suy ra bằng 0 từ usage.

### Bước 6 — Nghiệm thu từ B

1. Từ container/service B: auth sai bị từ chối, alias/context đúng.
2. Prompt thường, streaming, JSON Schema, function calling với dependency B.
3. Schema thật tất cả node, input dài, tiếng Việt, length và lỗi mạng.
4. Basic/deep end-to-end: retrieval, câu trả lời, trích dẫn, history, query rewrite.
5. Usage từng node khớp tổng DB; client hủy stream và A mất kết nối.
6. Đo latency, queue, VRAM ở tải dự kiến; test prompt sát context riêng.
7. Tài liệu đúng quyền, câu trả lời bám nguồn; smoke không thay đánh giá y khoa.

## 5. Vận hành A sau bàn giao

Không chạy thêm instance khi API đang hoạt động. Xem bằng
`tmux attach -t qwen-server-a`; detach Ctrl+B rồi D.
tmux không tự phục hồi sau reboot. Nếu cần uptime liên tục, bổ sung service manager,
health/inference monitoring và rotation log trong một bước riêng.

Chạy lại smoke test từ thư mục llm:

```bash
export PYTHONNOUSERSITE=1
set -o pipefail
.conda/bin/python -u smoke_test.py --base-url http://127.0.0.1:8000/v1 \
  2>&1 | tee logs/smoke-test.log
```

Từ B dùng URL nội bộ đã cấu hình và key A. Nếu copy runner riêng, cần
smoke_test.py, runtime.py, .env.example và dependency client; dùng
`VLLM_API_KEY` cho runner (khác `LLM_API_KEY` đề xuất cho app B).

**Mốc tiếp theo:** nối mạng B→A và thay client trên B. Bản bàn giao chỉ cập nhật
tài liệu, không restart A, sửa firewall hoặc thay code chạy B.
