FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app
RUN mkdir -p /data && chown app:app /data

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install ".[operation]"

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts/start_api.sh ./scripts/start_api.sh

USER app

EXPOSE 8000

CMD ["sh", "scripts/start_api.sh"]
