"""FastAPI application assembly.

Run:  uvicorn app.main:app --reload
Then: open http://localhost:8000  (demo console)  |  /docs  (OpenAPI UI)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import routes_auth, routes_docs, routes_query
from .audit import AuditLog
from .config import Settings, get_settings
from .rag.embeddings import build_embedder
from .rag.ingest import IngestionService
from .rag.llm import build_llm
from .rag.store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("enterprise-rag")

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        embedder = build_embedder(settings)
        llm = build_llm(settings)
        store = VectorStore(settings, embedder)
        app.state.settings = settings
        app.state.embedder = embedder
        app.state.llm = llm
        app.state.store = store
        app.state.ingestion = IngestionService(settings, store)
        app.state.audit = AuditLog(settings.audit_db_path)
        log.info(
            "%s ready | auth=%s | embeddings=%s | llm=%s | chunks=%d",
            settings.app_name, settings.auth_mode, embedder.name, llm.name, store.count(),
        )
        yield
        app.state.audit.close()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Retrieval-Augmented Generation over internal documents with role-based access control.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.environment == "dev" else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(routes_auth.router)
    app.include_router(routes_docs.router)
    app.include_router(routes_query.router)

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "auth_mode": settings.auth_mode}

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
