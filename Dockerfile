# Build the React frontend.
FROM node:24-alpine AS frontend-build

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Build the production application image.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NETWORK_STATS_DATABASE_URL=sqlite:////data/network_stats.db \
    NETWORK_STATS_FRONTEND_DIR=/app/frontend/dist

RUN apt-get update && \
    apt-get install -y --no-install-recommends iputils-ping gosu && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system app && \
    useradd --system --gid app --home-dir /app app && \
    mkdir -p /app /data && \
    chown -R app:app /app /data

WORKDIR /app/backend

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./

RUN pip install --no-cache-dir .

COPY --from=frontend-build /frontend/dist /app/frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=3)" || exit 1

USER root

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
