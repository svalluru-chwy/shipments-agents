# ------------------------------------------------------------------
# Shipments Agency Platform -- FastAPI Gateway
# Multi-stage build: builder (deps) -> runtime (minimal image)
# ------------------------------------------------------------------

# ---- Stage 1: builder ----
FROM python:3.10-slim AS builder

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e ".[snowflake]"

COPY packages/ packages/
COPY config.yaml ./
COPY skills/ skills/
COPY README.md ./

RUN pip install --no-cache-dir -e ".[snowflake]"


# ---- Stage 2: runtime ----
FROM python:3.10-slim AS runtime

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --from=builder /build/packages/ packages/
COPY --from=builder /build/config.yaml config.yaml
COPY --from=builder /build/skills/ skills/
COPY --from=builder /build/pyproject.toml pyproject.toml
COPY --from=builder /build/README.md README.md

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

ENTRYPOINT ["shipments-gateway"]
