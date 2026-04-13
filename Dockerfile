# Stage 1
FROM python:3.12 AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2
FROM python:3.12

RUN apt-get update && apt-get install ffmpeg libavcodec-extra -y
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app
COPY ./ /app

EXPOSE 8000

ENTRYPOINT ["uv", "run", "--no-sync", "uvicorn", "omnibox_wizard.wizard.api.server:app"]
CMD ["--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD wget -q -O- http://127.0.0.1:8000/api/v1/health || exit 1
