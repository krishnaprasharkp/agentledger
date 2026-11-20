ARG NODE_BASE=node:22-bookworm-slim
ARG PYTHON_BASE=python:3.13-slim

FROM ${NODE_BASE} AS dashboard
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_BASE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STATIC_DIR=/dashboard
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app app
COPY backend/*.py ./
COPY backend/invoice_agent ./invoice_agent
COPY --from=dashboard /build/dist /dashboard
USER app
EXPOSE 8000
CMD ["sh", "-ec", "\
    if [ \"${APP_MODE:-local}\" = public_demo ]; then \
        set -- --no-proxy-headers --no-access-log --limit-concurrency 128 --timeout-keep-alive 5; \
    else \
        python -m migrate; \
    fi; \
    exec uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8000}\" \"$@\""]
