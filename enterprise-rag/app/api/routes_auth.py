"""Authentication routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth.jwt_handler import issue_local_token
from ..auth.rbac import DEV_USERS
from ..config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    username: str
    password: str


@router.post("/token")
def token(body: TokenRequest, request: Request, settings: Settings = Depends(get_settings)):
    """Dev-only local token issuer (mirrors an OAuth2 password grant).
    Disabled in Auth0 mode — clients then get tokens from Auth0 directly."""
    if settings.auth_mode != "local":
        raise HTTPException(403, "Local issuer disabled; obtain tokens from Auth0")
    result = issue_local_token(body.username, body.password, settings)
    request.app.state.audit.log(body.username, DEV_USERS[body.username]["roles"], "auth.token_issued")
    return result


@router.get("/dev-users")
def dev_users(settings: Settings = Depends(get_settings)):
    """List demo identities (local mode only) so the demo console can
    offer a user picker. Never expose something like this in production."""
    if settings.auth_mode != "local":
        raise HTTPException(404, "Not available in Auth0 mode")
    return {
        username: {"name": rec["name"], "roles": rec["roles"], "password": rec["password"]}
        for username, rec in DEV_USERS.items()
    }
