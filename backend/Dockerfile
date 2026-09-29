FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY settlement ./settlement
RUN pip install --no-cache-dir ".[bigquery,iap]" uvicorn
# Cloud Run 은 PORT 를 주입한다
CMD ["sh", "-c", "uvicorn settlement.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
