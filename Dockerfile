FROM python:3.12-slim

# PORT 默认 7860：Hugging Face Docker Spaces 固定监听该端口；
# Render 会在运行时注入自己的 PORT，覆盖此默认值，因此两边都能直接用。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    TOOL_BACKEND=mock

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config
COPY knowledge ./knowledge
COPY static ./static
COPY eval ./eval
COPY docs ./docs
COPY .env.example ./

# HF Spaces 以 uid 1000 运行、Render 以 root 运行，日志与缓存目录需对两者都可写
RUN mkdir -p logs data && chmod -R 777 /app/logs /app/data

EXPOSE 7860

CMD ["python", "-m", "app.main"]
