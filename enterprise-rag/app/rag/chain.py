"""RAG chain: RBAC-filtered retrieval -> grounded generation.

Security invariant: the vector-store query carries a metadata filter
built from the caller's roles, so inaccessible chunks are never
retrieved, never enter the prompt, and can never leak into an answer.
"""
from __future__ import annotations

import logging

from ..auth.rbac import UserContext, visibility_filter
from ..config import Settings
from .llm import LLM
from .store import Chunk, VectorStore

log = logging.getLogger(__name__)

NO_ACCESS_MESSAGE = (
    "I couldn't find any documents you're authorized to access that answer "
    "this question. Either the information doesn't exist in the knowledge "
    "base, or it lives in a document your roles don't grant access to."
)


def answer_query(
    question: str,
    user: UserContext,
    store: VectorStore,
    llm: LLM,
    settings: Settings,
    top_k: int | None = None,
) -> dict:
    k = max(1, min(top_k or settings.top_k, settings.max_top_k))
    where = visibility_filter(user)
    chunks: list[Chunk] = store.search(question, where=where, top_k=k)

    log.info(
        "query user=%s roles=%s -> %d/%d chunks (filter=%s)",
        user.sub, user.roles, len(chunks), k, where,
    )
    if not chunks:
        return {
            "answer": NO_ACCESS_MESSAGE,
            "sources": [],
            "user": {"sub": user.sub, "roles": user.roles},
            "llm": llm.name,
            "chunks_retrieved": 0,
        }

    answer = llm.generate(question, chunks)
    sources = [
        {
            "rank": i,
            "doc_id": c.metadata.get("source"),
            "title": c.metadata.get("title"),
            "department": c.metadata.get("department"),
            "score": c.score,
            "snippet": " ".join(c.text.split())[:280],
        }
        for i, c in enumerate(chunks, 1)
    ]
    return {
        "answer": answer,
        "sources": sources,
        "user": {"sub": user.sub, "roles": user.roles},
        "llm": llm.name,
        "chunks_retrieved": len(chunks),
    }
