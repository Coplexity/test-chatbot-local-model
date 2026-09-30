# Server A: Qwen3.6-27B qua vLLM

Server A cung cấp API tương thích Chat Completions. RAG, DB, embedding,
history và điều phối agents vẫn thuộc Server B.

## Bàn giao và trạng thái ngày 2026-09-29

- [Tổng kết Server A và các bước cần làm trên B](HANDOVER.md).
- [API contract chi tiết B → A](API_CONTRACT.md).
- Conda riêng: Python 3.12.14, vLLM 0.19.0, PyTorch 2.10.0+cu128,
  langchain-openai 1.6.6; pip check, test CPU và kiểm tra cú pháp đã qua.
- Người dùng đã tải xong model, chạy GPU probe và toàn bộ smoke test thành công:
  chat, SSE/usage, JSON Schema và LangChain function calling.
- Người dùng đã gửi prompt và xác nhận Qwen trả lời trên A.
- Kiểm tra live: health 200, models có key 200/thiếu key 401;
  alias qwen3.6-27b, context công bố 65536.
- Chưa nối Server B, chưa test sát context hoặc đánh giá chất lượng y khoa.
- Giữ nguyên driver 535.309.01, CUDA hệ thống, firewall và các job khác.

Đây là snapshot bàn giao, không phải giám sát health liên tục.

## 1. Môi trường

Từ thư mục dự án:

```bash
cd /home/nvidia-lab/ai4life/nmkhoi/chatbot/medical-chatbot-source-2/llm
bash setup.sh
```

Script dùng lại Conda nếu đã tồn tại; chỉ tạo mới khi chưa có. API key và
`.env` được tạo với quyền 600 nếu chưa có, không ghi đè cấu hình cũ.
Thư mục tạm cài đặt nằm trong `.install-tmp` vì `/tmp` có dung lượng hạn chế.
Không dùng sudo, không cài vào Conda base. File requirements ghim các dependency
trực tiếp; dependency gián tiếp chưa có lockfile đầy đủ.

Không cần activate để dùng các lệnh bên dưới. Nếu muốn activate:

```bash
conda activate /home/nvidia-lab/ai4life/nmkhoi/chatbot/medical-chatbot-source-2/llm/.conda
```

## 2. Cấu hình

Sửa `.env` (mẫu trong `.env.example`):

- `MODEL_PATH=/home/nvidia-lab/data_mount/nmk/chatbot/Qwen3.6-27B`
- `HOST=127.0.0.1`, `PORT=8000`
- `SERVED_MODEL_NAME=qwen3.6-27b`
- `CUDA_VISIBLE_DEVICES=0`, `TENSOR_PARALLEL_SIZE=1`
- `MAX_MODEL_LEN=65536`, `DTYPE=bfloat16`
- `MAX_NUM_SEQS=1`, `GPU_MEMORY_UTILIZATION=0.80`
- `MAX_NUM_BATCHED_TOKENS=2048`, `GPU_HEADROOM_MIB=2048`
- `GDN_PREFILL_BACKEND=triton`: tránh lỗi FlashInfer GDN JIT đã quan sát.
- `ENABLE_THINKING=false`: mặc định ban đầu cho độ trễ/JSON; request có thể
  ghi đè qua `chat_template_kwargs.enable_thinking`.

API key nằm trong `.api-key`, không commit hoặc đưa vào log. Đây là key của A,
không phải key OpenAI dành cho embedding ở B.

Với GPU 81559 MiB và cấu hình trên, preflight yêu cầu ít nhất 67296 MiB trống
(80% tổng VRAM cộng 2048 MiB dự phòng). Ngân sách vLLM khoảng 63.7 GiB,
không phải hard cap của toàn bộ tiến trình. Không tự chờ, không chiếm GPU khi chưa
đủ điều kiện và không dừng tiến trình khác. Kiểm tra này không đặt chỗ GPU;
cần phối hợp sử dụng GPU để tránh job khác khởi động ngay sau preflight.

## 3. Kiểm tra trước khi chạy

```bash
.conda/bin/python runtime.py
```

Preflight kiểm tra model local, shard header/kích thước/tensor index, VRAM,
API key, executable và địa chỉ listen. Không download model và không load
trọng số. Kiểm tra shard không thay thế checksum SHA256 của toàn bộ file.

Sau khi được phép dùng GPU, kiểm tra nhỏ (không load Qwen):

```bash
PYTHONNOUSERSITE=1 .conda/bin/python gpu_probe.py
```

Kết quả mong đợi: `GPU_PROBE_COMPLETE`. Kiểm tra này xác nhận các kernel nhỏ,
chưa chứng minh toàn bộ model chạy được. Nếu lỗi driver/PTX, giữ nguyên hệ
thống và lưu lỗi để chọn giải pháp tương thích; không tự nâng driver.

## 4. Khởi chạy

```bash
tmux new -s qwen-server-a
cd /home/nvidia-lab/ai4life/nmkhoi/chatbot/medical-chatbot-source-2/llm
bash serve.sh
```

Ctrl+B rồi D để detach. `tmux attach -t qwen-server-a` để quay lại; Ctrl+C
trong cửa sổ này để dừng. tmux không tự khởi động lại sau reboot.

Script từ chối chạy nếu preflight chưa qua. Dùng model local với
`HF_HUB_OFFLINE=1`, tắt vision encoder, hỗ trợ reasoning parser và tool-call
parser. API key truyền qua environment, không qua tham số dòng lệnh.
Log ở `logs/server-<UTC>.log`. Chỉ cho một launcher của folder chạy cùng lúc.

Context hiện tại là 65536 token. Nếu thay đổi phải kiểm tra KV cache,
chạy lại kiểm thử và công bố đúng giới hạn thực tế cho B.

## 5. Kiểm thử API

Sau khi vLLM báo sẵn sàng:

```bash
.conda/bin/python smoke_test.py
```

Kiểm tra API key đúng/sai/thiếu, model alias, chat thường, SSE, usage,
JSON Schema và LangChain structured output với cả JSON Schema và tool calling.
Chỉ khi mọi kiểm tra thành công mới in `API_SMOKE_COMPLETE`.
Đây là test request ngắn, không chứng minh tải sát context 65K hoặc chất lượng y khoa.

## 6. Kết nối Server B

Sau khi cho phép IP của B qua firewall, đổi `HOST` sang IP nội bộ của A rồi
khởi động lại dịch vụ. Không dùng `127.0.0.1` làm địa chỉ B gọi tới A.
Không mở dịch vụ Internet trực tiếp; dùng mạng riêng/VPN hoặc HTTPS khi cần.

Thông tin bàn giao:

```text
LLM_BASE_URL=http://<IP_A>:8000/v1
LLM_MODEL=qwen3.6-27b
LLM_API_KEY=<nội dung .api-key, bàn giao riêng>
```

B phải cập nhật các client sinh văn bản với `base_url` và key này; chỉ thêm
biến môi trường chưa đủ nếu code chưa đọc chúng. Giữ cấu hình embedding riêng.
Kiểm thử lại với chính phiên bản LangChain và schema đang triển khai ở B.
Chạy smoke test từ B với key qua `VLLM_API_KEY` và `--base-url` tương ứng;
copy `smoke_test.py`, `runtime.py`, `.env.example` nếu B không có folder này.

## Kiểm tra code không cần GPU

```bash
.conda/bin/python -m unittest discover -s . -p 'test_*.py' -v
bash -n setup.sh serve.sh
```

Nguồn tham khảo:
- https://huggingface.co/Qwen/Qwen3.6-27B
- https://docs.vllm.ai/en/v0.19.0/getting_started/installation/gpu/
- https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html

## Sửa lỗi HTTP 500 do FlashInfer GDN (2026-09-29)

Log chạy thực tế đã ghi nhận:
- Model nạp xong, dùng 50.22 GiB; lần nạp đầu mất khoảng 39.7 phút.
- GPU probe BF16/Triton/vLLM RMSNorm đã qua.
- API khởi động nhưng request sinh câu trả lời lỗi build FlashInfer GDN:
  `fatal error: cuda/ptx: No such file or directory`.
- EngineCore và API server đã thoát sau lỗi.

Launcher hiện truyền `--gdn-prefill-backend triton`, cấu hình bằng
`GDN_PREFILL_BACKEND=triton` trong `.env`. Thay đổi này tránh nhánh biên dịch
FlashInfer GDN đang thiếu header; không thay đổi driver/CUDA hệ thống.
Giữ context 65536 và ngân sách VRAM 0.80 đang được người dùng chọn.

Khởi động lại bằng `bash serve.sh`. Log cần có
`Using Triton/FLA GDN prefill kernel`. Khi API sẵn sàng, chạy lại
`.conda/bin/python -u smoke_test.py`.
Smoke test giờ hiển thị cả response body của lỗi HTTP để hỗ trợ chẩn đoán.
Chỉ coi sửa lỗi end-to-end thành công khi có `API_SMOKE_COMPLETE`.
