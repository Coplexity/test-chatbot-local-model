# API contract Server B → Server A

Phiên bản bàn giao **1.0 — 2026-09-29**. Runtime vLLM 0.19.0, model alias
`qwen3.6-27b`. Xem [cấu hình và bằng chứng kiểm thử](HANDOVER.md).
Contract bao phủ phần API ứng dụng cần dùng, không cam kết toàn bộ OpenAI API.
Thay model/runtime/context/parser cần chạy lại acceptance tests.

## 1. Kết nối và phạm vi

| Thuộc tính | Giá trị / quy ước |
| --- | --- |
| Base URL hiện tại trên A | `http://127.0.0.1:8000/v1` |
| Base URL B sẽ dùng | `http://<IP_NOI_BO_A>:8000/v1`, chưa mở listen/mạng tới B |
| Encoding | UTF-8, request JSON |
| Authentication | `Authorization: Bearer <A_API_KEY>` cho /v1/* |
| Model | `qwen3.6-27b`, không phải đường dẫn trọng số |
| Modality cấu hình | Văn bản, launcher bật --language-model-only |
| Context | 65536 token: input đã serialize + ngân sách generation |
| Thinking mặc định | Tắt; B gửi rõ chat_template_kwargs.enable_thinking=false |
| State | Stateless ở mức hội thoại; B gửi messages cần thiết mỗi request |
| Đồng thời | MAX_NUM_SEQS=1 của scheduler, không phải HTTP rate limit |

Key A là secret giữa server, không phải JWT người dùng hoặc key OpenAI embedding.
Không đưa key vào URL, frontend, git hoặc log. HTTP không mã hóa dữ liệu; dùng
mạng riêng/VPN tin cậy hoặc TLS ở lớp triển khai.

Ngoài phạm vi: embeddings, ảnh/audio, Responses API, persistence hội thoại,
retrieval, chạy tool thực tế, kiểm tra quyền tài liệu. Không suy ra được hỗ trợ
chỉ vì runtime có thể công bố các route khác.

## 2. Endpoints

| Method/path | Auth | Thành công | Ý nghĩa |
| --- | --- | --- | --- |
| GET /health (ngoài /v1) | Hiện không yêu cầu | 200, body rỗng | Health, không chứng minh generation thành công |
| GET /v1/models | Bearer | 200 JSON | Alias và metadata |
| POST /v1/chat/completions | Bearer | 200 JSON hoặc SSE | Sinh text, structured output, tool calls |

Live check lúc bàn giao: health 200, models không key 401, models có key 200.
Smoke generation/stream/schema đã qua theo output người dùng cung cấp.

Ví dụ models rút gọn từ các trường quan sát được; runtime có thể thêm field:

```json
{
  "object": "list",
  "data": [
    {"id": "qwen3.6-27b", "object": "model", "owned_by": "vllm", "max_model_len": 65536}
  ]
}
```

B tìm alias trong data, không phụ thuộc thứ tự hoặc field bổ sung.

## 3. Request Chat Completions

Header `Content-Type: application/json`, thêm Bearer key.

| Field | Kiểu | Quy ước B |
| --- | --- | --- |
| model | string | Bắt buộc, qwen3.6-27b |
| messages | array object | Bắt buộc, không rỗng; system/history/user theo thứ tự |
| messages[].role | string | Text chat: system, user, assistant; tool flow thêm tool |
| messages[].content | string | Baseline dùng chuỗi; assistant tool-call có thể không có text |
| temperature | number | Đặt rõ theo node; smoke dùng 0, không cam kết tuyệt đối deterministic |
| max_tokens | integer > 0 | B đặt rõ trần output, tính trong context 65536 |
| stream | boolean | false cho JSON response, true cho SSE |
| stream_options.include_usage | boolean | true khi stream để nhận usage |
| chat_template_kwargs | object | Extension vLLM, baseline {"enable_thinking":false} |
| response_format | object | Tùy chọn, JSON Schema như mục 6 |
| tools, tool_choice | array, string/object | Chỉ dùng flow tool calling như mục 7 |

Contract dùng một completion/request; không yêu cầu n>1. Sampling parameter khác
không thuộc baseline đã test. Không gửi đồng thời response schema và tools
trong lần tích hợp đầu; tổ hợp chưa được nghiệm thu.

Input tính cả template, system, history, RAG context và tools/schema khi
serializer đưa vào prompt. Không đo bằng ký tự hoặc tokenizer GPT.
Output budget 2048 cần dành ít nhất phần đó trong context; B trim/summarize
input trước khi gọi nếu vượt budget.

Request text tối thiểu cùng shape smoke test:

```json
{
  "model": "qwen3.6-27b",
  "messages": [{"role": "user", "content": "Tính 2 + 3, trả lời ngắn bằng tiếng Việt."}],
  "temperature": 0,
  "max_tokens": 128,
  "stream": false,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

## 4. Response không streaming

Ví dụ minh họa; ID/thời gian/token count không phải số đo của lần kiểm thử:

```json
{
  "id": "chatcmpl-example",
  "object": "chat.completion",
  "created": 1790700000,
  "model": "qwen3.6-27b",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "2 + 3 = 5."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40}
}
```

B đọc choices[0].message.content và kiểm tra finish_reason:

| Giá trị | Xử lý |
| --- | --- |
| stop | Kết thúc bình thường; vẫn validate nội dung/schema |
| length | Chạm giới hạn; không coi JSON/câu trả lời là hoàn chỉnh |
| tool_calls | Model đề xuất gọi tool; chuyển tool flow |
| Khác / thiếu | Không mặc định thành công; lưu trạng thái, xử lý có kiểm soát |

Text có thể null/rỗng trong response tool calls. Bỏ qua field chưa biết để tránh
hỏng khi thêm metadata. Không dùng response id như ID hội thoại bền vững.

Usage mapping: prompt_tokens → input, completion_tokens → output, total_tokens
→ tổng của **một lần gọi**. Không tự hiểu là tiền hoặc tổng token workflow.
Thiếu usage thì đánh dấu unknown/estimate riêng, không ghi 0 như đã được đo.

## 5. Streaming SSE

Giữ request text, đổi/thêm:

```json
{"stream": true, "stream_options": {"include_usage": true}}
```

Response Content-Type: text/event-stream. Ví dụ event rút gọn minh họa:

```text
data: {"id":"chatcmpl-example","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-example","choices":[{"index":0,"delta":{"content":"2 + 3 = 5."},"finish_reason":null}]}

data: {"id":"chatcmpl-example","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: {"id":"chatcmpl-example","choices":[],"usage":{"prompt_tokens":30,"completion_tokens":10,"total_tokens":40}}

data: [DONE]
```

Parser B phải:

1. Dùng SSE parser/SDK, không giả định một TCP chunk là một JSON hoàn chỉnh.
   UTF-8 có thể bị tách giữa network chunk.
2. Nối delta.content khi có; delta có thể chỉ chứa role/metadata.
3. Đọc usage cả ở event choices rỗng; không dừng ngay khi thấy finish_reason.
4. Chờ [DONE] và kiểm tra finish reason/nội dung/lỗi. Thiếu [DONE] là incomplete.
5. Khi error event, mất mạng hoặc timeout sau HTTP 200: đánh dấu incomplete,
   không lưu text dở như câu trả lời hoàn chỉnh, không nối một retry mới vào stream.
6. Hủy upstream khi client hủy; phải kiểm thử cancellation trên B.

B tiếp tục phát giao thức SSE ứng dụng cho frontend. Thinking=false là baseline.
Bật reasoning chưa thuộc test này; không phụ thuộc tên field reasoning của model
để dựng trace workflow.

## 6. Structured output — JSON Schema

Request đã smoke test với schema đơn giản:

```json
{
  "model": "qwen3.6-27b",
  "messages": [{"role": "user", "content": "Return JSON with answer equal to 2 + 3."}],
  "temperature": 0,
  "max_tokens": 128,
  "chat_template_kwargs": {"enable_thinking": false},
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "sum_result",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": false
      }
    }
  }
}
```

choices[0].message.content vẫn là **chuỗi JSON**, ví dụ {"answer":5};
B parse và validate schema/Pydantic, kiểm tra finish reason trước.
Schema đúng không đảm bảo đúng y khoa hoặc trích dẫn đúng.
Chưa cam kết mọi JSON Schema keyword/recursive schema; test từng schema thật.

## 7. Tool calling / LangChain function calling

Launcher bật auto tool choice, parser qwen3_coder. Smoke đã qua
with_structured_output(..., method="function_calling") với schema đơn giản.
Vòng nhiều tool, auto selection và streaming arguments cần kiểm thử riêng.

Request dưới đây là mẫu tích hợp, chưa phải kết quả test tool execution:

```json
{
  "model": "qwen3.6-27b",
  "messages": [{"role": "user", "content": "Return the result of 2 + 3 using sum_result."}],
  "temperature": 0,
  "max_tokens": 128,
  "chat_template_kwargs": {"enable_thinking": false},
  "tools": [{
    "type": "function",
    "function": {
      "name": "sum_result",
      "description": "Return an integer result.",
      "parameters": {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
        "additionalProperties": false
      }
    }
  }],
  "tool_choice": {"type": "function", "function": {"name": "sum_result"}}
}
```

Response message shape minh họa:

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [{
    "id": "call_example",
    "type": "function",
    "function": {"name": "sum_result", "arguments": "{\"answer\":5}"}
  }]
}
```

function.arguments là chuỗi JSON. B parse/validate tên và arguments, chỉ cho
phép function trong allowlist. Structured output chỉ lấy object, không cần chạy tool.
Tool thực sự do B thực thi theo quyền ứng dụng: append assistant tool_calls và
message role=tool, tool_call_id tương ứng, content là chuỗi kết quả; gọi A tiếp nếu cần.
Streaming tool calls cần ghép delta theo index/id, chỉ parse arguments khi hoàn tất.

## 8. Client LangChain trên B

Mẫu tương ứng cấu hình **cần bổ sung B**, chưa phải file đã triển khai.
max_tokens=2048 là output budget ví dụ, khác smoke budget 128:

```python
import os
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

llm = ChatOpenAI(
    model=os.environ["LLM_MODEL"],
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
    temperature=0,
    max_tokens=2048,
    timeout=180,
    max_retries=0,
    stream_usage=True,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)

class SumResult(BaseModel):
    answer: int

result = llm.with_structured_output(
    SumResult, method="json_schema"
).invoke("Compute 2 + 3 and put the integer in answer.")
print(result.answer)
```

SDK Python nhận extension vLLM qua extra_body. Trên wire JSON,
chat_template_kwargs nằm ở top level; không gửi field JSON tên extra_body.
Smoke xác nhận langchain-openai 1.6.6 tại A; phải test lại dependency B.
Không mặc định nâng toàn bộ dependency B khi chưa kiểm tra LangGraph/Pydantic.

## 9. Lệnh thử từ B

Sau khi đường mạng đã mở, đặt LLM_BASE_URL và LLM_API_KEY bằng cấu hình/secret
của service B. Đoạn này chỉ dùng thư viện chuẩn Python, không cần GPU:

```python
import json
import os
import urllib.error
import urllib.request

base = os.environ["LLM_BASE_URL"].rstrip("/")
key = os.environ["LLM_API_KEY"]
payload = {
    "model": os.environ.get("LLM_MODEL", "qwen3.6-27b"),
    "messages": [{"role": "user", "content": "Xin chào, hãy trả lời ngắn bằng tiếng Việt."}],
    "max_tokens": 128,
    "temperature": 0,
    "chat_template_kwargs": {"enable_thinking": False},
}
request = urllib.request.Request(
    base + "/chat/completions",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
)
try:
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
except urllib.error.HTTPError as exc:
    detail = exc.read(16384).decode("utf-8", errors="replace").replace(key, "[REDACTED]")
    raise SystemExit(f"HTTP {exc.code}: {detail}") from None
print(result["choices"][0]["message"]["content"])
print("finish_reason:", result["choices"][0]["finish_reason"])
print("usage:", result.get("usage"))
```

Test một prompt này không thay thế full smoke hoặc end-to-end basic/deep.

## 10. Lỗi, timeout và retry

Không phụ thuộc duy nhất một error envelope. Thiếu key đã quan sát:

```json
{"error": "Unauthorized"}
```

Lỗi khác có thể là error object, detail hoặc text từ proxy. B lưu status và
message đã giới hạn độ dài/che secret, xử lý body theo content type.

| Trường hợp | Hành vi B |
| --- | --- |
| 400/422: request/schema/context không hợp lệ | Sửa payload/budget; không retry y nguyên |
| 401/403: key thiếu/sai hoặc policy từ chối | Báo lỗi cấu hình/xác thực; không retry |
| 404: URL/alias sai | Kiểm tra base URL và models; không retry mù |
| 429 nếu proxy/server trả | Backoff hữu hạn, tôn trọng Retry-After nếu có |
| 5xx | Thu thập lỗi/log; retry hữu hạn chỉ trước khi phát nội dung cho người dùng |
| Connection refused/timeout | Kiểm tra service, mạng, queue; báo unavailable |
| HTTP 200 nhưng stream đứt/error | Đánh dấu incomplete, không coi thành công |
| finish_reason=length | Điều chỉnh budget/task/context; không coi câu trả lời đã đủ |

Ngoài auth đã test và HTTP500 đã quan sát, đây là chính sách xử lý B,
không phải báo cáo fault-inject tất cả status.
Chưa có rate-limit SLA, idempotency contract, retry guarantee hoặc uptime SLA.
Retry có thể tạo thêm lần inference; B quản lý correlation và idempotency nghiệp vụ.
Timeout 180 giây mới dùng cho request ngắn, chưa là SLA deep mode.

## 11. Tiêu chí chấp nhận tích hợp

| Nhóm | Đã xác nhận A | Còn cần xác nhận B |
| --- | --- | --- |
| Auth/model | Key sai/thiếu bị từ chối, alias đúng | Kết nối từ container/service B |
| Text/usage | Text ngắn, token usage | Prompt thật, history, accounting từng node |
| SSE | Text, finish reason, usage, DONE | Mapping frontend, cancel/disconnect, proxy timeout |
| JSON Schema | Schema integer đơn giản | Tất cả schema routing/reasoning thực tế |
| Function calling | LangChain structured output đơn giản | Tool flow cần dùng, validation/quyền thực thi |
| Context/load | Công bố 65536, request ngắn thành công | Prompt sát context, concurrency, queue, latency, VRAM |
| RAG/chất lượng | Không nằm trong smoke A | Basic/deep, retrieval, trích dẫn, bám nguồn |

Tài liệu runtime đã ghim:
[vLLM 0.19.0 OpenAI-compatible server](https://docs.vllm.ai/en/v0.19.0/serving/openai_compatible_server/),
[vLLM 0.19.0 structured outputs](https://docs.vllm.ai/en/v0.19.0/features/structured_outputs/).
Nguồn nghiệm thu dự án: serve.py, runtime.py, smoke_test.py, cấu hình A và
bằng chứng trong [HANDOVER.md](HANDOVER.md).
