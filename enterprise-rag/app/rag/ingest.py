"""Document ingestion pipeline.

Markdown/text files carry YAML front matter declaring their access
control list::

    ---
    title: Q3 Revenue Forecast
    department: finance
    allowed_roles: [finance, executive]
    ---

The pipeline parses metadata, splits with LangChain's recursive
character splitter, expands roles into boolean metadata flags, and
upserts into the vector store. Re-ingesting the same ``doc_id`` first
removes its old chunks (idempotent).
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import yaml
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import Settings
from ..auth.rbac import normalize_roles, role_flags
from .store import VectorStore

log = logging.getLogger(__name__)

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_document(text: str, fallback_title: str) -> tuple[dict, str]:
    """Split YAML front matter from the body. Missing front matter =>
    defaults: public visibility, no department."""
    meta: dict = {}
    match = _FRONT_MATTER_RE.match(text)
    body = text
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        body = text[match.end():]
    roles = meta.get("allowed_roles", ["public"])
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(",")]
    meta["allowed_roles"] = normalize_roles(roles) or ["public"]
    meta.setdefault("title", fallback_title)
    meta.setdefault("department", "general")
    return meta, body.strip()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "doc"


class IngestionService:
    def __init__(self, settings: Settings, store: VectorStore):
        self._settings = settings
        self._store = store
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
        )

    def ingest_text(self, doc_id: str, text: str, ingested_by: str, roles_override: list[str] | None = None) -> dict:
        meta, body = parse_document(text, fallback_title=doc_id)
        if roles_override is not None:
            meta["allowed_roles"] = normalize_roles(roles_override) or ["public"]
        if not body:
            raise ValueError("Document body is empty")

        self._store.delete_document(doc_id)  # idempotent re-ingest
        chunks = self._splitter.split_text(body)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        base_meta = {
            "source": doc_id,
            "title": meta["title"],
            "department": str(meta["department"]).lower(),
            "allowed_roles": ",".join(meta["allowed_roles"]),
            "ingested_at": now,
            "ingested_by": ingested_by,
            **role_flags(meta["allowed_roles"]),
        }
        ids = [f"{doc_id}#{i}" for i in range(len(chunks))]
        metadatas = [dict(base_meta, chunk_index=i) for i in range(len(chunks))]
        n = self._store.upsert_chunks(ids, chunks, metadatas)
        log.info("ingested %s -> %d chunks (roles=%s)", doc_id, n, meta["allowed_roles"])
        return {
            "doc_id": doc_id,
            "title": meta["title"],
            "department": base_meta["department"],
            "allowed_roles": meta["allowed_roles"],
            "chunks": n,
        }

    def ingest_directory(self, path: str | Path, ingested_by: str) -> list[dict]:
        results = []
        for file in sorted(Path(path).glob("*.md")):
            results.append(self.ingest_text(slugify(file.stem), file.read_text(encoding="utf-8"), ingested_by))
        return results
