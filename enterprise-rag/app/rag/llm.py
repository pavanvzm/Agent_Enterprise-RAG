"""LLM providers for answer generation.

* ``OpenAILLM`` — any OpenAI-compatible chat-completions endpoint.
* ``FallbackLLM`` — deterministic extractive composer used when no API
  key is configured, so the system is fully demonstrable offline. Its
  output is clearly labelled and still cites retrieved sources.
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx
from langchain_core.prompts import ChatPromptTemplate

from ..config import Settings
from .store import Chunk

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an internal knowledge assistant for an enterprise.
Answer the user's question using ONLY the context passages below, which were
retrieved from documents the user is authorized to access under role-based
access control.

Rules:
- Cite sources inline as [1], [2], ... matching the passage numbers.
- If the context does not contain the answer, say so plainly — never
  speculate or use outside knowledge, and never mention that other
  documents might exist but be inaccessible.
- Be concise and professional.

Context:
{context}"""


class LLM(Protocol):
    name: str

    def generate(self, question: str, chunks: list[Chunk]) -> str: ...


def _format_context(chunks: list[Chunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[{i}] (source: {c.metadata.get('title', c.metadata.get('source'))})\n{c.text}")
    return "\n\n".join(parts)


class OpenAILLM:
    def __init__(self, api_key: str, model: str, base_url: str):
        self._key, self._model, self._base = api_key, model, base_url.rstrip("/")
        self.name = f"openai/{model}"
        self._prompt = ChatPromptTemplate.from_messages(
            [("system", SYSTEM_PROMPT), ("human", "{question}")]
        )

    def generate(self, question: str, chunks: list[Chunk]) -> str:
        messages = self._prompt.format_messages(
            context=_format_context(chunks), question=question
        )
        resp = httpx.post(
            f"{self._base}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json={
                "model": self._model,
                "messages": [{"role": m.type if m.type != "human" else "user", "content": m.content} for m in messages],
                "temperature": 0.1,
            },
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


class FallbackLLM:
    """Extractive answer composer for offline demos/CI."""

    name = "fallback-extractive (offline dev fallback)"

    def generate(self, question: str, chunks: list[Chunk]) -> str:
        lines = [
            "**[offline extractive mode — no LLM API key configured]**",
            "",
            f"Based on the {len(chunks)} passage(s) you are authorized to access:",
            "",
        ]
        for i, c in enumerate(chunks, 1):
            snippet = " ".join(c.text.split())
            if len(snippet) > 350:
                snippet = snippet[:347].rsplit(" ", 1)[0] + "..."
            title = c.metadata.get("title", c.metadata.get("source"))
            lines.append(f"{i}. {snippet}  — *{title}* [{i}]")
        lines.append("")
        lines.append("Set `RAG_OPENAI_API_KEY` to enable generative answers.")
        return "\n".join(lines)


def build_llm(settings: Settings) -> LLM:
    provider = settings.llm_provider.lower()
    if provider in ("auto", "openai") and settings.openai_api_key:
        log.info("llm: OpenAI-compatible provider (%s)", settings.llm_model)
        return OpenAILLM(settings.openai_api_key, settings.llm_model, settings.openai_base_url)
    if provider == "openai":
        raise RuntimeError("RAG_LLM_PROVIDER=openai requires RAG_OPENAI_API_KEY")
    log.warning("llm: using extractive fallback — set RAG_OPENAI_API_KEY for generative answers")
    return FallbackLLM()
