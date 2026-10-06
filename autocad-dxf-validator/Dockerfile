# [미검증 · 회사 연결 예정] Cloud Run 이미지 — 로컬에서 빌드해 보지 않았다.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api,gcp]"
ENV PORT=8080 DXFCHECK_JOBS_DIR=/data/jobs
CMD exec uvicorn dxfcheck.api:app --host 0.0.0.0 --port ${PORT}
