# ABOUTME: Multi-stage Dockerfile for the FastAPI API service.
# ABOUTME: Uses uv for dependency installation; runs as non-root user in production.

FROM python:3.12.7-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy source
COPY . .

# Non-root user for runtime
RUN addgroup --system app && adduser --system --ingroup app app
USER app

EXPOSE 8000

# Injected at build time by CI: fly deploy --build-arg GIT_SHA=$GITHUB_SHA
ARG GIT_SHA=""
ENV RELEASE=${GIT_SHA}

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
