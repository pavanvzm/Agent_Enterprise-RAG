"""Embedding providers.

Resolution order in ``auto`` mode:
1. OpenAI-compatible API, when ``RAG_OPENAI_API_KEY`` is set.
2. ``sentence-transformers``, when the package is installed.
3. A deterministic **hashed n-gram** embedder — pure Python, fully
   offline. It is only lexical (no semantics), but keeps every code path
   exercisable in CI / demos without network access or model downloads.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Protocol

import httpx

from ..config import Settings

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# ------------------------------------------------------------------- hashed
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class HashedEmbedder:
    """Deterministic bag-of-ngrams embedding via feature hashing."""

    name = "hashed-ngram (offline dev fallback)"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        tokens = _TOKEN_RE.findall(text.lower())
        feats = list(tokens)
        feats += [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]  # bigrams
        return feats

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            for feat in self._features(text):
                digest = hashlib.md5(feat.encode()).digest()
                idx = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


# --------------------------------------------------------- sentence-transformers
class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        self._model = SentenceTransformer(model_name)
        self.name = f"sentence-transformers/{model_name}"
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.encode(texts, normalize_embeddings=True)]


# ------------------------------------------------------------------- openai
class OpenAIEmbedder:
    """Works with any OpenAI-compatible /embeddings endpoint."""

    def __init__(self, api_key: str, model: str, base_url: str):
        self._key, self._model, self._base = api_key, model, base_url.rstrip("/")
        self.name = f"openai/{model}"
        self.dim = 0  # discovered on first call

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{self._base}/embeddings",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self._model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        vectors = [d["embedding"] for d in data]
        if vectors and not self.dim:
            self.dim = len(vectors[0])
        return vectors


# ------------------------------------------------------------------ factory
def build_embedder(settings: Settings) -> Embedder:
    provider = settings.embedding_provider.lower()
    if provider in ("auto", "openai") and settings.openai_api_key:
        log.info("embeddings: OpenAI-compatible provider (%s)", settings.embedding_model)
        return OpenAIEmbedder(settings.openai_api_key, settings.embedding_model, settings.openai_base_url)
    if provider in ("auto", "sentence-transformers", "st"):
        try:
            emb = SentenceTransformerEmbedder(settings.st_model_name)
            log.info("embeddings: sentence-transformers (%s)", settings.st_model_name)
            return emb
        except Exception as exc:  # package missing or model unavailable
            if provider != "auto":
                raise
            log.warning("sentence-transformers unavailable (%s); using hashed fallback", exc)
    log.warning("embeddings: using hashed n-gram fallback — lexical only, dev/demo use")
    return HashedEmbedder()
