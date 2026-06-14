# ── Stage 1: build the Vite/React frontend ───────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web-app/package.json web-app/package-lock.json* ./
RUN npm install
COPY web-app/ ./
RUN npm run build

# ── Stage 2: Python backend (serves API + built SPA) ──────────────────────────
FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app/ ./app/
COPY docs/ ./docs/
COPY web/ ./web/
COPY --from=web /web/dist ./web-app/dist

EXPOSE 8000
# DPDPA note: pin SCRIBE_VERTEX_LOCATION + provide creds via env/secrets at run time.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
