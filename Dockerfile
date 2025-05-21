FROM python:3.12 AS builder

RUN wget -O- https://install.python-poetry.org | python3 -
WORKDIR /app

COPY pyproject.toml poetry.lock /app/
RUN /root/.local/bin/poetry config virtualenvs.create false \
    && /root/.local/bin/poetry install --no-interaction --no-root --no-directory --only main

FROM python:3.12

WORKDIR /app
COPY ./ /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

EXPOSE 8000

ENTRYPOINT ["uvicorn", "wizard.api.server:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD wget -q -O- http://127.0.0.1:8000/api/v1/health || exit 1
