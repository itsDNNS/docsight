# --- builder stage: compile native dependencies ---
FROM python:3.14-slim@sha256:fb83750094b46fd6b8adaa80f66e2302ecbe45d513f6cece637a841e1025b4ca AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt
COPY tools/icmp_probe_helper.c /build/icmp_probe_helper.c
COPY tools/traceroute_helper.c /build/traceroute_helper.c
RUN mkdir -p /build/out && \
    gcc -O2 -Wall -o /build/out/docsight-icmp-helper /build/icmp_probe_helper.c && \
    gcc -O2 -Wall -o /build/out/docsight-traceroute-helper /build/traceroute_helper.c

# --- runtime stage: slim final image ---
FROM python:3.14-slim@sha256:fb83750094b46fd6b8adaa80f66e2302ecbe45d513f6cece637a841e1025b4ca
ARG VERSION=dev
WORKDIR /app
RUN echo "${VERSION}" > /app/VERSION

COPY --from=builder /install /usr/local
COPY --from=builder /build/out/docsight-icmp-helper /usr/local/bin/docsight-icmp-helper
COPY --from=builder /build/out/docsight-traceroute-helper /usr/local/bin/docsight-traceroute-helper

# Keep elevated privileges scoped to the dedicated ICMP helper.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gosu \
    libjpeg62-turbo \
    && chown root:root /usr/local/bin/docsight-icmp-helper \
    && chmod 4755 /usr/local/bin/docsight-icmp-helper \
    && chown root:root /usr/local/bin/docsight-traceroute-helper \
    && chmod 4755 /usr/local/bin/docsight-traceroute-helper \
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
