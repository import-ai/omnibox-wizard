FROM python:3.12 AS builder

RUN wget -O- https://install.python-poetry.org | python3 -
WORKDIR /app

COPY pyproject.toml poetry.lock /app/
RUN /root/.local/bin/poetry config virtualenvs.create false \
    && /root/.local/bin/poetry install --no-interaction --no-root --no-directory --only main

FROM python:3.12

RUN apt-get update && apt-get install ffmpeg libavcodec-extra -y
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
