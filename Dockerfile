FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Sentence-embedding model for semantic search (~90 MB). Non-fatal: without it search uses keywords + rules.
RUN python -m ml.build_semantic_index --model-only || echo "Embedding model unavailable; semantic search disabled"

# Accounts (SQLite) and the encryption key file live here: mount a volume to keep them across restarts,
#   docker run -p 8000:8000 -v reloc-data:/app/instance -e RELOC_ENCRYPTION_KEY=... relocaitor
RUN mkdir -p /app/instance && useradd --create-home app && chown -R app /app/instance
USER app
VOLUME ["/app/instance"]
ENV PORT=8000 RELOC_SECURE_COOKIES=0
EXPOSE 8000
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 60 app:app"]
