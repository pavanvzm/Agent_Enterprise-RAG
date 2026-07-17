"""Seed the vector store with the sample internal documents.

Usage:
    python scripts/seed.py [--reset]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.rag.embeddings import build_embedder
from app.rag.ingest import IngestionService
from app.rag.store import VectorStore

SAMPLE_DOCS = Path(__file__).resolve().parent.parent / "data" / "sample_docs"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="wipe the collection first")
    args = parser.parse_args()

    settings = get_settings()
    embedder = build_embedder(settings)
    store = VectorStore(settings, embedder)
    if args.reset:
        store.reset()
        print("collection reset")

    service = IngestionService(settings, store)
    results = service.ingest_directory(SAMPLE_DOCS, ingested_by="seed-script")
    print(f"embedder: {embedder.name}")
    for r in results:
        print(f"  + {r['doc_id']:<34} roles={','.join(r['allowed_roles']):<24} chunks={r['chunks']}")
    print(f"total chunks in store: {store.count()}")


if __name__ == "__main__":
    main()
