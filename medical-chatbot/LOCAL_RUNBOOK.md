# Local Runbook - Chatbot Local

Tai lieu nay huong dan chay local repo `chatbot_local` gom 2 phan:

- `ai_documents_management`: PostgreSQL/pgvector database va guideline/document backend.
- `medical-chatbot`: frontend, NestJS backend, FastAPI chat-api.

Sau khi clone repo, cau truc can thay la:

```text
chatbot_local/
├── ai_documents_management/
└── medical-chatbot/
    ├── chat-api/
    ├── chat-backend/
    ├── chat-frontend/
    └── deploy/
```

## 1. Clone Va Mo Workspace

Clone repo:

```bash
git clone https://github.com/Coplexity/chatbot_local.git
cd chatbot_local
```

Neu dung VS Code, nen mo file workspace o root repo:

```bash
code chatbot_local.code-workspace
```

Hoac trong VS Code: `File > Open Workspace from File...` va chon `chatbot_local.code-workspace`.

Khi mo bang workspace file nay, Explorer se hien 2 folder chinh:

```text
ai_documents_management
medical-chatbot
```

## 2. Yeu Cau

- Docker Desktop dang chay.
- Docker Compose v2.
- Git.
- OpenAI API key cho embedding (`text-embedding-3-large`).
- Duong mang va API key toi Server A (Qwen3.6-27B qua vLLM) de sinh cau tra loi. Xem muc 4.1.

## 3. Chay Database

Tu root repo `chatbot_local`:

```bash
cd ai_documents_management
cp .env.example .env
docker compose up -d db
docker compose ps
```

Thong tin database local:

```text
Host: localhost
Port: 5436
Database: guideline_management
User: postgres
Password: postgres
```

Kiem tra container DB:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

DB can o trang thai tuong tu:

```text
guideline-db   Up ... (healthy)   0.0.0.0:5436->5432/tcp
```

Quay lai root repo:

```bash
cd ..
```

## 4. Cau Hinh Medical Chatbot

Tu root repo `chatbot_local`:

```bash
cd medical-chatbot
cp deploy/.env.example deploy/.env
```

Mo file `medical-chatbot/deploy/.env` va cau hinh cac bien chinh:

```env
FRONTEND_PORT=8400

VITE_BACKEND_URL=http://chat-backend:3000
VITE_DOCUMENT_FILE_URL_TEMPLATE=http://localhost:8000/api/v1/documents/{documentId}/file
VITE_MAINTENANCE_MESSAGE=

DB_HOST=host.docker.internal
DB_PORT=5436
DB_NAME=guideline_management
DB_USER=postgres
DB_PASS=postgres
DB_SYNCHRONIZE=true
DB_LOGGING=false

JWT_SECRET=change_me_for_local_development

LLM_BASE_URL=http://host.docker.internal:8001/v1
LLM_API_KEY=key_cua_server_a
LLM_MODEL=qwen3.6-27b
LLM_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=0
LLM_CONTEXT_TOKENS=65536
LLM_MAX_TOKENS=4096
LLM_MAX_CONCURRENCY=1
LLM_STRUCTURED_OUTPUT_METHOD=json_schema

OPENAI_API_KEY=your_openai_key_here
EMBEDDING_MODEL=text-embedding-3-large

RETRIEVAL_DEEP_DOCUMENT_LIMIT=4
RETRIEVAL_DEEP_TOP_K=6
```

Giai thich nhanh:

- `host.docker.internal`: cho phep container Docker goi ve database dang expose tren may host.
- `DB_PORT=5436`: port PostgreSQL cua `ai_documents_management`.
- `VITE_BACKEND_URL=http://chat-backend:3000`: frontend nginx proxy den NestJS backend trong Docker network.
- `DB_SYNCHRONIZE=true`: dung cho local de backend tu tao schema/table can thiet. Khi deploy production nen dat `false`.
- `LLM_BASE_URL`, `LLM_API_KEY`: dia chi va key cua Server A. Thieu mot trong hai thi `chat-api` dung ngay luc khoi dong voi loi `Thiếu cấu hình LLM`, khong tu chuyen sang OpenAI.
- `LLM_MAX_TOKENS`: tran output moi lan goi, tinh trong context 65536 cua A.
- `LLM_CONTEXT_TOKENS`: context cua model tren A. Ngan sach input moi lan goi = `LLM_CONTEXT_TOKENS - LLM_MAX_TOKENS - 256` (mac dinh 61184 token). Truoc moi lan goi expert, `chat-api` dem token bang endpoint `/tokenize` cua A; neu vuot ngan sach thi bo bot chunk xep hang thap nhat va ghi log `[Context Budget]`.
- `RETRIEVAL_DEEP_DOCUMENT_LIMIT`, `RETRIEVAL_DEEP_TOP_K`: che do deep lay toi da bao nhieu van ban moi chuyen khoa va bao nhieu chunk moi van ban. Moi van ban la mot lan goi LLM rieng, nen tang hai so nay se lam cau tra loi cham hon. Che do basic khong doi (10 chunk moi chuyen khoa).
- `LLM_MAX_CONCURRENCY`: so request LLM dong thoi tu `chat-api`. A dang chay `MAX_NUM_SEQS=1` nen de `1`.
- `LLM_STRUCTURED_OUTPUT_METHOD`: `json_schema` hoac `function_calling` cho cac node routing/validator.
- `OPENAI_API_KEY`: chi con dung cho embedding. Khong commit file `.env`.

### 4.1. Ket Noi Toi LLM Tren Server A

Server A chi listen `127.0.0.1:8000`, nen tu may local can mo SSH tunnel. Cong 8000 cua may local da dung cho guideline backend, vi vay tunnel dung cong 8001:

```bash
ssh -N -L 8001:127.0.0.1:8000 <user>@<server-a>
```

Giu terminal nay mo trong luc test. Container `chat-api` goi tunnel qua `http://host.docker.internal:8001/v1`.

Neu A da mo IP noi bo/VPN cho may nay thi khong can tunnel, dat `LLM_BASE_URL=http://<IP_NOI_BO_A>:8000/v1`.

`LLM_API_KEY` la noi dung file `.api-key` tren Server A, khong phai key OpenAI.

Chi tiet API: `Tai lieu cho local model mới/API_CONTRACT.md` o root repo.

## 5. Tao Docker Network

Repo dung external network ten `chatbot-db`.

Chay mot lan:

```bash
docker network create chatbot-db
```

Neu bao network da ton tai thi bo qua.

## 6. Chay Medical Chatbot

Tu root repo `chatbot_local`:

```bash
cd medical-chatbot/deploy
```

Lan dau, neu chua co image nao, co the build:

```bash
docker compose up -d --build
```

Luu y: build `chat-api` co the rat lau vi cai Python dependencies nang. Neu may da co image san hoac chi can start lai he thong, dung lenh nhanh hon:

```bash
docker compose up -d --no-build chat-api chat-backend chat-frontend
```

Neu vua sua `.env` va muon container an cau hinh moi:

```bash
docker compose up -d --no-build --force-recreate chat-api chat-backend chat-frontend
```

## 7. Kiem Tra He Thong

Kiem tra container:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Trang thai mong doi:

```text
medical-chatbot-chat-frontend-1   Up ... (healthy)   0.0.0.0:8400->80/tcp
medical-chatbot-chat-backend-1    Up ...
medical-chatbot-chat-api-1        Up ...             8000/tcp
guideline-db                      Up ... (healthy)   0.0.0.0:5436->5432/tcp
```

Kiem tra frontend:

```bash
curl http://localhost:8400/health
```

Ket qua mong doi:

```text
healthy
```

Kiem tra backend qua frontend nginx proxy:

```bash
curl http://localhost:8400/api/health
```

Ket qua mong doi:

```json
{
  "status": "ok",
  "info": {
    "database": {
      "status": "up"
    }
  },
  "error": {},
  "details": {
    "database": {
      "status": "up"
    }
  }
}
```

Kiem tra ket noi `chat-api` toi LLM tren Server A (can tunnel dang mo):

```bash
cd medical-chatbot/deploy
docker compose exec chat-api python -m scripts.check_llm
```

Ket qua mong doi la cac dong `PASS ...` va dong cuoi:

```text
LLM_CHECK_COMPLETE (chỉ request ngắn; chưa test sát context hay chất lượng y khoa)
```

Mo ung dung:

```text
http://localhost:8400
```

## 8. Xem Logs

Tu root repo `chatbot_local`.

Log frontend:

```bash
cd medical-chatbot/deploy
docker compose logs -f chat-frontend
```

Log backend:

```bash
cd medical-chatbot/deploy
docker compose logs -f chat-backend
```

Log chat-api:

```bash
cd medical-chatbot/deploy
docker compose logs -f chat-api
```

Log database:

```bash
cd ai_documents_management
docker compose logs -f db
```

## 9. Chay Guideline Backend Neu Can File Document

Neu frontend can mo file tai lieu qua URL `http://localhost:8000/api/v1/documents/{documentId}/file`, can chay guideline backend trong `ai_documents_management`.

Tu root repo `chatbot_local`:

```bash
cd ai_documents_management
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

Hoac neu da co `.venv` va dependencies:

```bash
cd ai_documents_management
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger guideline backend:

```text
http://localhost:8000/docs
```

## 10. Tat He Thong

Tat medical chatbot:

```bash
cd medical-chatbot/deploy
docker compose down
```

Tat database/guideline services:

```bash
cd ai_documents_management
docker compose down
```

Chi reset sach database local khi chac chan khong can du lieu cu:

```bash
cd ai_documents_management
docker compose down -v
```

## 11. Loi Thuong Gap

### Frontend restart voi loi `host not found in upstream`

Neu log frontend co loi:

```text
host not found in upstream "medical-chatbot-chat-backend-1"
```

Sua `medical-chatbot/deploy/.env`:

```env
VITE_BACKEND_URL=http://chat-backend:3000
```

Sau do recreate:

```bash
cd medical-chatbot/deploy
docker compose up -d --no-build --force-recreate chat-frontend chat-backend
```

### Backend bao `database "db" does not exist`

Nguyen nhan: `DB_NAME` dang sai hoac container chua an `.env` moi.

Sua `medical-chatbot/deploy/.env`:

```env
DB_HOST=host.docker.internal
DB_PORT=5436
DB_NAME=guideline_management
DB_USER=postgres
DB_PASS=postgres
```

Sau do recreate:

```bash
cd medical-chatbot/deploy
docker compose up -d --no-build --force-recreate chat-backend chat-api
```

### `docker compose up -d --build` doi qua lau

Nguyen nhan thuong la `chat-api` dang cai Python dependencies nang.

Neu container/image da co san va chi muon chay lai:

```bash
cd medical-chatbot/deploy
docker compose up -d --no-build chat-api chat-backend chat-frontend
```

### Backend health tra database down

Kiem tra DB co chay khong:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Can thay:

```text
guideline-db   Up ... (healthy)   0.0.0.0:5436->5432/tcp
```

Neu DB chua chay:

```bash
cd ai_documents_management
docker compose up -d db
```

### Chat AI loi khi gui cau hoi

Chay kiem tra ket noi LLM de biet loi nam o dau:

```bash
cd medical-chatbot/deploy
docker compose exec chat-api python -m scripts.check_llm
```

- `Connection refused` / timeout: SSH tunnel toi Server A chua mo hoac vLLM tren A chua chay.
- HTTP 401 o buoc `model alias`: `LLM_API_KEY` sai.
- `không thấy alias`: `LLM_MODEL` khong khop alias A dang phuc vu.
- Cau hoi dung o buoc `Truy xuat` voi loi 401 cua OpenAI: kiem tra `OPENAI_API_KEY` (embedding).

Neu `chat-api` restart lien tuc, xem log:

```bash
docker compose logs --tail 30 chat-api
```

Loi `Thiếu cấu hình LLM: ...` nghia la chua dien `LLM_BASE_URL` hoac `LLM_API_KEY` trong `medical-chatbot/deploy/.env`.

Sau khi sua `.env`:

```bash
cd medical-chatbot/deploy
docker compose up -d --no-build --force-recreate chat-api
```

Sau khi sua code `chat-api` phai build lai image:

```bash
cd medical-chatbot/deploy
docker compose up -d --build chat-api
```

## 12. Lenh Nhanh Hang Ngay

Tu root repo `chatbot_local`.

Start database:

```bash
cd ai_documents_management
docker compose up -d db
cd ..
```

Start medical chatbot:

```bash
cd medical-chatbot/deploy
docker compose up -d --no-build chat-api chat-backend chat-frontend
cd ../..
```

Check health:

```bash
curl http://localhost:8400/health
curl http://localhost:8400/api/health
```

Open app:

```text
http://localhost:8400
```

Stop all:

```bash
cd medical-chatbot/deploy
docker compose down
cd ../..

cd ai_documents_management
docker compose down
cd ..
```