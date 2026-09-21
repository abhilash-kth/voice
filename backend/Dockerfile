# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATABASE_URL=""

WORKDIR /app

# Runtime libraries used by LiveKit, audio codecs, Google/Sarvam plugins and
# Prisma's generated client. Build tools are kept only in the builder stage.
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Do not upgrade pip here: it adds an unnecessary network dependency and can
# fail when the builder has restricted DNS/egress. The pip bundled in the
# official Python image is sufficient for installing the requirements.
RUN pip wheel --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    # Prevent BLAS/OpenMP thread storms on small containers.
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* \
    && rm -rf /wheels

# Copy source and Prisma schema only. Do not bake .env files or credentials into
# the image; provide secrets through the platform's environment/secret store.
COPY app ./app
COPY schema.prisma ./schema.prisma
COPY requirements.txt ./requirements.txt

# Generate the Prisma Python client during the image build. DATABASE_URL is not
# contacted by generate; migrations/db push should be run separately against the
# externally hosted Postgres instance.
RUN python -m prisma generate --schema schema.prisma

# The app writes local JSON memory/campaign data under data/ in this codebase.
# Mount a volume if that state must survive container replacement.
RUN mkdir -p /app/data \
    # Prisma generated its query engine as root during the build. The runtime
    # process is non-root, so make the engine cache traversable/readable.
    && chmod 755 /root /root/.cache /root/.cache/prisma-python \
    && chmod -R a+rX /root/.cache/prisma-python \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# API is the default process. For a separate LiveKit worker service, override
# the command with: python -m app.agents.worker
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
