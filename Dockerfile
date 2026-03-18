# Build stage: install dependencies
FROM python:3.14-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.14-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Install Playwright system deps + Chromium browser
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN apt-get update && \
    playwright install --with-deps chromium && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy application and migration files
COPY api/ ./api/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Startup script: run migrations then start server
COPY <<'EOF' /app/start.sh
#!/bin/sh
set -e
echo "Running database migrations..."
python -m alembic upgrade head
echo "Starting SearchClaw API server..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
EOF
RUN chmod +x /app/start.sh

# Non-root user (Playwright needs writable home for browser cache)
RUN useradd -r -m -s /bin/false appuser
USER appuser

EXPOSE 8000

CMD ["/app/start.sh"]
