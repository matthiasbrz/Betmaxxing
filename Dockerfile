FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install -e ".[postgres]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY docs ./docs

# Run as a non-root user.
RUN useradd --create-home --uid 10001 betmaxxing && chown -R betmaxxing:betmaxxing /app
USER betmaxxing

EXPOSE 8000

CMD ["uvicorn", "betmaxxing.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
