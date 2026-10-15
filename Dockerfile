FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY cinemate ./cinemate
COPY migrations ./migrations
RUN pip install --no-cache-dir ".[postgres]"

RUN useradd --create-home --uid 10001 cinemate \
    && mkdir -p /app/data \
    && chown cinemate:cinemate /app/data
USER cinemate

ENTRYPOINT ["cinemate"]
