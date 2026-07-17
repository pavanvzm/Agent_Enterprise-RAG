"""Chroma vector store wrapper.

All RBAC enforcement happens here: every read path takes a ``where``
filter derived from the caller's roles, so unauthorized chunks are never
returned by the database in the first place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import chromadb

from ..config import Settings
from .embeddings import Embedder

log = logging.getLogger(__name__)


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict
    score: float  # cosine similarity in [0, 1] (higher = better)


class VectorStore:
    def __init__(self, settings: Settings, embedder: Embedder):
        self._settings = settings
        self._embedder = embedder
        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        self._col = self._client.get_or_create_collection(
            name=settings.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------- writes
    def upsert_chunks(self, chunk_ids: list[str], texts: list[str], metadatas: list[dict]) -> int:
        if not chunk_ids:
            return 0
        embeddings = self._embedder.embed(texts)
        self._col.upsert(ids=chunk_ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
        return len(chunk_ids)

    def delete_document(self, source: str) -> int:
        existing = self._col.get(where={"source": source}, include=[])
        if existing["ids"]:
            self._col.delete(ids=existing["ids"])
        return len(existing["ids"])

    def reset(self) -> None:
        self._client.delete_collection(self._settings.collection_name)
        self._col = self._client.get_or_create_collection(
            name=self._settings.collection_name, metadata={"hnsw:space": "cosine"}
        )

    # -------------------------------------------------------------- reads
    def search(self, query: str, where: dict, top_k: int) -> list[Chunk]:
        """Similarity search restricted by an RBAC metadata filter."""
        if self._col.count() == 0:
            return []
        query_emb = self._embedder.embed([query])
        res = self._col.query(
            query_embeddings=query_emb,
            n_results=min(top_k, self._col.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        chunks: list[Chunk] = []
        for cid, doc, meta, dist in zip(
            res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            chunks.append(Chunk(chunk_id=cid, text=doc, metadata=meta, score=round(1.0 - dist, 4)))
        return chunks

    def list_documents(self, where: dict) -> list[dict]:
        """Aggregate chunk metadata into one entry per source document,
        already restricted to what the caller may see."""
        got = self._col.get(where=where, include=["metadatas"])
        docs: dict[str, dict] = {}
        for meta in got["metadatas"]:
            src = meta["source"]
            entry = docs.setdefault(
                src,
                {
                    "doc_id": src,
                    "title": meta.get("title", src),
                    "department": meta.get("department", ""),
                    "allowed_roles": meta.get("allowed_roles", ""),
                    "chunks": 0,
                    "ingested_at": meta.get("ingested_at", ""),
                    "ingested_by": meta.get("ingested_by", ""),
                },
            )
            entry["chunks"] += 1
        return sorted(docs.values(), key=lambda d: d["doc_id"])

    def count(self) -> int:
        return self._col.count()
