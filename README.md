# Chatbot Local Workspace

Repo nay gom 2 folder chinh:

```text
chatbot_local/
├── ai_documents_management/
└── medical-chatbot/
```

- `ai_documents_management`: database PostgreSQL/pgvector va guideline/document backend.
- `medical-chatbot`: frontend, NestJS backend va FastAPI chat-api.

## Ban Giao: LLM Chay Tren Server A

`chat-api` da chuyen phan sinh van ban tu OpenAI `gpt-4.1` sang Qwen3.6-27B tren Server A (vLLM). Embedding van dung OpenAI.

- [BAN_GIAO.md](BAN_GIAO.md): trang thai, thong tin can dien, cach deploy va kiem tra. Doc file nay truoc.
- [Tai lieu cho local model mới/](Tai%20lieu%20cho%20local%20model%20mới/): tai lieu van hanh Server A va API contract.

## Mo Bang VS Code

Nen mo file workspace o root repo:

```bash
code chatbot_local.code-workspace
```

Hoac trong VS Code: `File > Open Workspace from File...` va chon `chatbot_local.code-workspace`.

## Chay Local

Doc runbook tai:

[medical-chatbot/LOCAL_RUNBOOK.md](medical-chatbot/LOCAL_RUNBOOK.md)

Thu tu chay ngan gon:

```bash
cd ai_documents_management
cp .env.example .env
docker compose up -d db
cd ..

cd medical-chatbot
cp deploy/.env.example deploy/.env
# sua deploy/.env theo LOCAL_RUNBOOK.md
cd deploy
docker compose up -d --build
```

Sau lan build dau tien, nhung lan sau nen start nhanh bang:

```bash
cd medical-chatbot/deploy
docker compose up -d --no-build chat-api chat-backend chat-frontend
```

Sau khi chay xong, mo:

```text
http://localhost:8400
```