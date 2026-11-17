# NovaStore API image (Python 3.11 slim)
# Build:  docker build -t novastore .
# Run:    docker run --env-file .env -p 8000:8000 -v novastore-data:/app/data novastore

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .

# Seed the DB on first boot if the volume is empty, then serve the API.
CMD ["sh", "-c", "python scripts/seed_db.py && uvicorn novastore.api.app:app --host 0.0.0.0 --port 8000"]
