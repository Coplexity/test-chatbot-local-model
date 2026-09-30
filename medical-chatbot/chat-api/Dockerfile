FROM python:3.11-slim

# Thư mục làm việc
WORKDIR /app

# Cài một số system deps cơ bản
RUN apt-get update && apt-get install -y \
    build-essential \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code vào container
COPY . .

# Note: Không cần preload model vì đang dùng OpenAI API (không có local model)
# OpenAI embeddings được gọi qua API, không cần cache local

# Expose port (cho docker-compose, optional)
EXPOSE 8000

# Lệnh chạy API
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
