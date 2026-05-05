# syntax=docker/dockerfile:1.7

# ── Builder stage ────────────────────────────────────────────────────────────
# Installs Python deps into a self-contained venv that the runtime stage copies.
# Using uv (faster than pip) but the resulting venv is plain Python — no uv at runtime.
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Copy only dependency manifests first to leverage Docker layer cache
COPY pyproject.toml uv.lock* README.md ./

# Create venv + install runtime deps (no dev extras)
RUN uv venv /opt/venv \
    && uv pip install --no-cache --python /opt/venv/bin/python -e .

# Copy source last so code edits don't bust the deps layer
COPY src/ ./src/
COPY catalog.yaml ./

RUN uv pip install --no-cache --python /opt/venv/bin/python -e .


# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# DuckDB needs libstdc++ at runtime; everything else is pure Python wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy venv and source from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

# Data directory is a volume mount point — image stays slim
RUN mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000

# Health check hits the FastAPI root
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(f'http://localhost:{__import__(\"os\").environ.get(\"PORT\", 8000)}/').read()" || exit 1

# Default: serve the REST API. Override CMD to run na-mcp or na-etl instead.
#   docker run ...                         → REST API on $PORT
#   docker run ... na-mcp                  → MCP server (stdio)
#   docker run ... na-etl daily            → run ETL once
CMD ["sh", "-c", "uvicorn noticiasagricolas_etl.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
