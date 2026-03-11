# --- builder stage: compile native dependencies ---
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
COPY tools/icmp_probe_helper.c /build/icmp_probe_helper.c
RUN mkdir -p /build/out && \
    gcc -O2 -Wall -o /build/out/docsight-icmp-helper /build/icmp_probe_helper.c

# --- runtime stage: slim final image ---
FROM python:3.12-slim
ARG VERSION=dev
WORKDIR /app
RUN echo "${VERSION}" > /app/VERSION

COPY --from=builder /install /usr/local
COPY --from=builder /build/out/docsight-icmp-helper /usr/local/bin/docsight-icmp-helper

# Keep CAP_NET_RAW scoped to the dedicated ICMP helper.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    libcap2-bin \
    libjpeg62-turbo \
    && setcap cap_net_raw+ep /usr/local/bin/docsight-icmp-helper \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" --uid 1000 appuser && \
    mkdir -p /data && chown appuser:appuser /data
COPY app/ ./app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')" || exit 1
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
