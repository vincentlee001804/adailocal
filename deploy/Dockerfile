FROM python:3.11-slim

# Keep Python lean and predictable
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (optional: install only if needed later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first to leverage Docker layer cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Default envs (can be overridden by Fly secrets)
ENV ONE_SHOT=0 \
    USE_AI_SUMMARY=1

# Run the worker
CMD ["python", "adailocal.py"]


