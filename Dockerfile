# ── Stage 1: build the Vite/React frontend ───────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web-app/package.json web-app/package-lock.json* ./
# npm ci is reproducible (uses the lockfile); falls back to install if no lockfile.
RUN npm ci || npm install
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

# Run as an unprivileged user (never root in the container).
RUN useradd --create-home --uid 10001 svaani && chown -R svaani:svaani /srv
USER svaani

EXPOSE 8000
# Container health: liveness probe against /health (no secrets leaked).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

# DPDPA note: pin SCRIBE_VERTEX_LOCATION + provide creds via env/secrets at run time.
# Production also requires SCRIBE_ENVIRONMENT=production, SCRIBE_AUTH_MODE=jwt,
# SCRIBE_PHI_ENCRYPTION_KEY_B64, and SCRIBE_ADMIN_PASSWORD (the startup guard enforces this).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
