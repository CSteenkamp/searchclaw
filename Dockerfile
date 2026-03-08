# Build stage: install dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

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

# Non-root user
RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 8000

CMD ["/app/start.sh"]
