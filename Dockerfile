FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
RUN adduser --disabled-password --gecos "" --uid 1000 appuser && \
    mkdir -p /data && chown appuser:appuser /data
USER appuser
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')" || exit 1
CMD ["python", "-m", "app.main"]
