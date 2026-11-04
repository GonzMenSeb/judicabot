FROM node:24-slim AS frontend

RUN corepack enable

WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend ./
RUN pnpm build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.25 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1001 app && useradd --uid 1001 --gid 1001 --create-home app

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --extra ocr --no-install-project

COPY backend/tutela2 ./tutela2
RUN uv sync --frozen --no-dev --extra ocr
COPY --from=frontend /app/backend/tutela2/static/dist ./tutela2/static/dist

ENV PATH="/app/backend/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    CASOS_DIR=/data/casos \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data/casos /home/app/.cache/tutela2 \
    && chown -R app:app /data /home/app/.cache

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["tutela2-ui"]
