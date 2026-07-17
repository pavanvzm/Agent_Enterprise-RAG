"""JWT issuing and verification.

Two modes:

* ``local`` — a built-in HS256 issuer so the whole system runs offline
  for demos and tests. NOT for production.
* ``auth0`` — RS256 verification against the tenant's JWKS endpoint,
  exactly how the service behaves when fronted by Auth0 in production.
  Roles are read from a namespaced custom claim (injected by an Auth0
  Action), falling back to the ``permissions`` claim.
"""
from __future__ import annotations

import time
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from ..config import Settings, get_settings
from .rbac import DEV_USERS, UserContext, normalize_roles

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing or invalid bearer token",
    headers={"WWW-Authenticate": "Bearer"},
)


# --------------------------------------------------------------------- local
def issue_local_token(username: str, password: str, settings: Settings) -> dict:
    """Dev-only token issuer. Mirrors an OAuth2 password grant so the demo
    works without an Auth0 tenant."""
    record = DEV_USERS.get(username)
    if not record or record["password"] != password:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    now = int(time.time())
    claims = {
        "iss": settings.jwt_issuer,
        "sub": username,
        "name": record["name"],
        "roles": record["roles"],
        "iat": now,
        "exp": now + settings.token_ttl_minutes * 60,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer", "expires_in": settings.token_ttl_minutes * 60}


def _verify_local(token: str, settings: Settings) -> UserContext:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return UserContext(
        sub=claims["sub"],
        name=claims.get("name", claims["sub"]),
        roles=normalize_roles(claims.get("roles", [])),
    )


# --------------------------------------------------------------------- auth0
@lru_cache(maxsize=4)
def _jwks_client(domain: str) -> PyJWKClient:
    return PyJWKClient(f"https://{domain}/.well-known/jwks.json", cache_keys=True, lifespan=300)


def _extract_auth0_roles(claims: dict, settings: Settings) -> list[str]:
    roles = claims.get(settings.auth0_roles_claim)
    if roles is None:
        roles = claims.get("permissions", [])
    if isinstance(roles, str):
        roles = [roles]
    return normalize_roles(list(roles))


def _verify_auth0(token: str, settings: Settings) -> UserContext:
    if not settings.auth0_domain or not settings.auth0_audience:
        raise HTTPException(500, "Auth0 mode requires RAG_AUTH0_DOMAIN and RAG_AUTH0_AUDIENCE")
    try:
        signing_key = _jwks_client(settings.auth0_domain).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return UserContext(
        sub=claims["sub"],
        name=claims.get("name", claims["sub"]),
        roles=_extract_auth0_roles(claims, settings),
    )


# --------------------------------------------------------------- dependency
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    """FastAPI dependency: resolve the bearer token to a UserContext."""
    if credentials is None:
        raise _UNAUTHORIZED
    token = credentials.credentials
    if settings.auth_mode == "auth0":
        return _verify_auth0(token, settings)
    return _verify_local(token, settings)


def require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user
