# syntax=docker/dockerfile:1.7

# ==========================================
# Stage 1: Builder Stage (Compile Wheels)
# ==========================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Install build dependencies for C-extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Pre-compile wheels to speed up final runtime installation
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ==========================================
# Stage 2: Runtime Stage (Lightweight Production)
# ==========================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    # Prevent BLAS/OpenMP thread storms on small containers
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

WORKDIR /app

# Install runtime libraries required by LiveKit & audio codecs
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

# Install wheels generated in the builder stage
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* \
    && rm -rf /wheels

# Copy application source code and schema
COPY app ./app
COPY schema.prisma ./schema.prisma
COPY requirements.txt ./requirements.txt

# Generate Prisma Python client
RUN python -m prisma generate --schema schema.prisma

# Prepare local volume directory and set up permissions for Prisma cache
RUN mkdir -p /app/data \
    && chmod 755 /root /root/.cache /root/.cache/prisma-python \
    && chmod -R a+rX /root/.cache/prisma-python \
    && chown -R appuser:appuser /app

# Switch to non-root user for security
USER appuser

EXPOSE 8000

# Default command runs the API; worker overrides this in compose
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
