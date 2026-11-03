FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so Docker caches this layer until requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only what the web service needs at runtime
COPY app.py model.sav ./
COPY templates ./templates

# Run as a non-root user (numeric UID so Kubernetes runAsNonRoot can verify it)
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

# 1 worker + 4 threads: prometheus_client keeps counters in process memory, so a single
# worker process keeps /metrics accurate. Scale out with more containers/pods instead.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "60", "app:app"]
