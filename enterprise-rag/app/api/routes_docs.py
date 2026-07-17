"""Document management routes (ingest / list / delete)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..auth.jwt_handler import require_admin
from ..auth.rbac import UserContext, can_access, visibility_filter
from ..auth.jwt_handler import get_current_user
from ..rag.ingest import slugify

router = APIRouter(prefix="/documents", tags=["documents"])


class IngestResponse(BaseModel):
    doc_id: str
    title: str
    department: str
    allowed_roles: list[str]
    chunks: int


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    request: Request,
    file: UploadFile,
    roles: str | None = None,
    admin: UserContext = Depends(require_admin),
):
    """Ingest a markdown/text document. ``roles`` optionally overrides the
    front-matter ACL (comma-separated). Admin role required."""
    if file.content_type not in (None, "text/markdown", "text/plain", "application/octet-stream"):
        raise HTTPException(415, "Only markdown/plain-text documents are supported")
    text = (await file.read()).decode("utf-8", errors="replace")
    roles_override = [r.strip() for r in roles.split(",")] if roles else None
    service = request.app.state.ingestion
    try:
        result = service.ingest_text(
            slugify(file.filename.rsplit(".", 1)[0]), text, ingested_by=admin.sub,
            roles_override=roles_override,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    request.app.state.audit.log(
        admin.sub, admin.roles, "docs.ingest",
        doc_id=result["doc_id"], allowed_roles=result["allowed_roles"], chunks=result["chunks"],
    )
    return result


@router.get("")
def list_documents(request: Request, user: UserContext = Depends(get_current_user)):
    """List only the documents the caller is allowed to see — the listing
    itself is access-controlled, not just retrieval."""
    store = request.app.state.store
    docs = store.list_documents(where=visibility_filter(user))
    return {"documents": docs, "count": len(docs), "viewer_roles": user.roles}


@router.delete("/{doc_id}")
def delete_document(doc_id: str, request: Request, admin: UserContext = Depends(require_admin)):
    removed = request.app.state.store.delete_document(doc_id)
    if removed == 0:
        raise HTTPException(404, f"No document with id '{doc_id}'")
    request.app.state.audit.log(admin.sub, admin.roles, "docs.delete", doc_id=doc_id, chunks_removed=removed)
    return {"doc_id": doc_id, "chunks_removed": removed}
