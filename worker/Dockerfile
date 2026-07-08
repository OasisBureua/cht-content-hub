# contenthub-worker — placeholder until EventBridge/Lambda sync (see worker/README.md)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY healthcheck.py main.py ./
COPY utils/ ./utils/

RUN useradd -m -u 1000 worker && chown -R worker:worker /app
USER worker

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python /app/healthcheck.py

CMD ["python", "main.py"]
