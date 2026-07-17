"""Query and audit routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..auth.jwt_handler import get_current_user, require_admin
from ..auth.rbac import UserContext
from ..config import Settings, get_settings
from ..rag.chain import answer_query

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


@router.post("/query")
def query(
    body: QueryRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    result = answer_query(
        body.question, user,
        store=request.app.state.store,
        llm=request.app.state.llm,
        settings=settings,
        top_k=body.top_k,
    )
    request.app.state.audit.log(
        user.sub, user.roles, "query",
        question=body.question[:200],
        chunks_retrieved=result["chunks_retrieved"],
        sources=[s["doc_id"] for s in result["sources"]],
    )
    return result


@router.get("/audit")
def audit(request: Request, limit: int = 100, admin: UserContext = Depends(require_admin)):
    """Admin-only: recent audit events."""
    return {"events": request.app.state.audit.recent(limit=min(limit, 500))}
