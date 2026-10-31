# syntax=docker/dockerfile:1
# Wisselweer: multi-stage image, draait als non-root gebruiker.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Eerst alleen de afhankelijkheden (betere laagcaching), daarna het project zelf.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
# openssh-client is alleen nodig voor SFTP-publicatie (`sftp`).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 wisselweer \
    && useradd --system --uid 10001 --gid 10001 --home-dir /home/wisselweer --create-home \
       --shell /usr/sbin/nologin wisselweer \
    && mkdir /data && chown wisselweer:wisselweer /data

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/wisselweer \
    WISSELWEER_HOST=0.0.0.0 \
    WISSELWEER_PORT=8000 \
    WISSELWEER_DATA_DIR=/data

WORKDIR /app
USER 10001:10001
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"]

# Migraties draaien automatisch bij het opstarten van de app.
CMD ["wisselweer", "serve"]
