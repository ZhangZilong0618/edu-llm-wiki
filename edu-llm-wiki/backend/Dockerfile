# syntax=docker/dockerfile:1.6
# Edu-LLM-Wiki backend
# Dev-friendly image: runs uvicorn with auto-reload off (compose volume
# handles source updates by restarting the container, see docker-compose.yml).

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential: needed for some wheels (e.g. sentence-transformers
# transitive deps). curl: used by the HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached as long as
# requirements.txt is unchanged.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the rest of the source. In dev, ./src and ./data are bind-mounted
# over /app, so this mostly matters for the first build.
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
