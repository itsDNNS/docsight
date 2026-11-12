# --- builder stage: compile native dependencies ---
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder

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
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
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
    mkdir -p /data/modules /modules && \
    chown -R appuser:appuser /data /modules
COPY app/ ./app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
