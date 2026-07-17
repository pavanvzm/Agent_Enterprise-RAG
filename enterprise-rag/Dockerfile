FROM python:3.12-slim

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data/sample_docs ./data/sample_docs
COPY scripts ./scripts

# Persist Chroma + audit DB outside the image layer in real deployments:
#   docker run -v rag-data:/srv/app/data ...
ENV RAG_CHROMA_PATH=./data/chroma \
    RAG_AUDIT_DB_PATH=./data/audit.db

EXPOSE 8000
CMD ["sh", "-c", "python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
