"""Application configuration, loaded from environment / .env file.

Every setting can be overridden with an environment variable prefixed
with ``RAG_``, e.g. ``RAG_AUTH_MODE=auth0``.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    app_name: str = "Enterprise RAG"
    environment: str = "dev"

    # ------------------------------------------------------------------ auth
    # "local"  -> HS256 tokens minted by the built-in dev issuer (demo only)
    # "auth0"  -> RS256 tokens verified against an Auth0 tenant's JWKS
    auth_mode: str = "local"
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_issuer: str = "enterprise-rag-local"
    token_ttl_minutes: int = 60

    auth0_domain: str = ""            # e.g. "your-tenant.us.auth0.com"
    auth0_audience: str = ""          # API identifier configured in Auth0
    # Custom claim (Action-injected) that carries the user's roles
    auth0_roles_claim: str = "https://enterprise-rag/roles"

    # ----------------------------------------------------------- vector store
    chroma_path: str = "./data/chroma"
    collection_name: str = "internal_docs"

    # -------------------------------------------------------------- embeddings
    # auto | openai | sentence-transformers | hashed
    embedding_provider: str = "auto"
    embedding_model: str = "text-embedding-3-small"
    st_model_name: str = "all-MiniLM-L6-v2"

    # -------------------------------------------------------------------- LLM
    # auto | openai | fallback
    llm_provider: str = "auto"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # -------------------------------------------------------------------- RAG
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 5
    max_top_k: int = 20

    # ------------------------------------------------------------------ audit
    audit_db_path: str = "./data/audit.db"


def get_settings() -> Settings:
    return Settings()
