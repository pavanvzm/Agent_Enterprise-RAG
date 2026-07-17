"""Role-based access control model.

Design notes
------------
* Roles are **flat** — there is no implicit hierarchy. An executive who
  should see everything is simply granted every department role. Flat
  models are easier to audit and reason about than hierarchical ones.
* The special role ``public`` is implicit: every authenticated user can
  read documents whose ``allowed_roles`` contains ``public``.
* ``admin`` is a privilege role: it gates ingestion, deletion and the
  audit-log endpoint. It grants *no* document visibility by itself.
* Document visibility is enforced **at retrieval time** via vector-store
  metadata filters, so an unauthorized chunk never leaves the database —
  it is not "retrieved then hidden". This is the key security property.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PUBLIC_ROLE = "public"
ADMIN_ROLE = "admin"

# ---------------------------------------------------------------------------
# Dev user directory (only used when RAG_AUTH_MODE=local).
# In production these identities live in Auth0; passwords are NEVER stored
# here — this map exists purely so the demo is runnable offline.
# ---------------------------------------------------------------------------
DEV_USERS: dict[str, dict] = {
    "alice": {  # CTO — can see everything, admin of the system
        "password": "alice-pass",
        "name": "Alice (CTO)",
        "roles": ["executive", "engineering", "hr", "finance", "admin"],
    },
    "bob": {  # engineer
        "password": "bob-pass",
        "name": "Bob (Engineer)",
        "roles": ["engineering"],
    },
    "carol": {  # HR business partner
        "password": "carol-pass",
        "name": "Carol (HR)",
        "roles": ["hr"],
    },
    "dave": {  # finance analyst
        "password": "dave-pass",
        "name": "Dave (Finance)",
        "roles": ["finance"],
    },
    "erin": {  # regular employee, public docs only
        "password": "erin-pass",
        "name": "Erin (Employee)",
        "roles": [],
    },
}

_ROLE_RE = re.compile(r"[^a-z0-9_]")


def normalize_role(role: str) -> str:
    """Make a role string safe for use as a metadata key suffix."""
    return _ROLE_RE.sub("_", role.strip().lower())


def normalize_roles(roles: list[str]) -> list[str]:
    return sorted({normalize_role(r) for r in roles if r.strip()})


@dataclass
class UserContext:
    """An authenticated principal."""

    sub: str
    name: str
    roles: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles

    @property
    def visible_roles(self) -> list[str]:
        """Roles used for document-visibility filtering (includes public)."""
        return sorted(set(self.roles) | {PUBLIC_ROLE})


def role_flags(allowed_roles: list[str]) -> dict[str, bool]:
    """Expand a document's allowed roles into boolean metadata flags.

    Chroma metadata values must be scalars, so ``["hr", "executive"]``
    becomes ``{"role_hr": True, "role_executive": True}`` which can be
    matched with ``$or`` equality filters at query time.
    """
    return {f"role_{r}": True for r in normalize_roles(allowed_roles)}


def visibility_filter(user: UserContext) -> dict:
    """Build the Chroma ``where`` clause that restricts a query to chunks
    the given user is allowed to see."""
    clauses = [{f"role_{r}": True} for r in user.visible_roles]
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def can_access(user: UserContext, doc_allowed_roles: list[str]) -> bool:
    """Application-level check (defense in depth, used for doc listings)."""
    return bool(set(user.visible_roles) & set(normalize_roles(doc_allowed_roles)))
