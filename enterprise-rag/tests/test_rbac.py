"""End-to-end tests.

The security-critical suite is here: it proves that retrieval-level RBAC
filtering prevents cross-role data leakage, both through the API and at
the raw vector-store layer.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DOCS = {
    "handbook": ("---\ntitle: Handbook\ndepartment: general\nallowed_roles: [public]\n---\n"
                  "Employees get 20 PTO days per year. The IT helpdesk answers in one business day."),
    "eng-runbook": ("---\ntitle: Runbook\ndepartment: engineering\nallowed_roles: [engineering]\n---\n"
                     "Deploy payments with argocd app promote payments-prod. On-call rotates Mondays."),
    "hr-bands": ("---\ntitle: Comp Bands\ndepartment: hr\nallowed_roles: [hr]\n---\n"
                  "Senior engineer base salary band is 178000 to 215000 USD. 401k match is 4 percent."),
    "fin-forecast": ("---\ntitle: Forecast\ndepartment: finance\nallowed_roles: [finance]\n---\n"
                      "Projected Q3 revenue is 18.2M dollars with 31 months of runway."),
    "exec-memo": ("---\ntitle: Strategy\ndepartment: executive\nallowed_roles: [executive]\n---\n"
                   "Project Falcon is the planned acquisition of Skyline Perception for 30 to 38M."),
    "incident": ("---\ntitle: INC-2041\ndepartment: security\nallowed_roles: [engineering, executive]\n---\n"
                  "A contractor GitHub token leaked for 9 hours; two repos were cloned."),
}

PASSWORDS = {"alice": "alice-pass", "bob": "bob-pass", "carol": "carol-pass",
             "dave": "dave-pass", "erin": "erin-pass"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rag")
    settings = Settings(
        chroma_path=str(tmp / "chroma"),
        audit_db_path=str(tmp / "audit.db"),
        embedding_provider="hashed",
        llm_provider="fallback",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        # seed directly through the ingestion service (admin path tested below)
        for doc_id, text in DOCS.items():
            app.state.ingestion.ingest_text(doc_id, text, ingested_by="test")
        yield c


def token(client: TestClient, username: str) -> dict:
    resp = client.post("/auth/token", json={"username": username, "password": PASSWORDS[username]})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def ask(client: TestClient, username: str, question: str) -> dict:
    resp = client.post("/query", json={"question": question}, headers=token(client, username))
    assert resp.status_code == 200, resp.text
    return resp.json()


def source_docs(result: dict) -> set[str]:
    return {s["doc_id"] for s in result["sources"]}


# --------------------------------------------------------------- auth tests
def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_token_requires_valid_password(client):
    resp = client.post("/auth/token", json={"username": "bob", "password": "wrong"})
    assert resp.status_code == 401


def test_query_requires_token(client):
    assert client.post("/query", json={"question": "anything?"}).status_code == 401


def test_ingest_requires_admin(client):
    files = {"file": ("x.md", b"hello world", "text/markdown")}
    assert client.post("/documents/ingest", files=files).status_code == 401
    resp = client.post("/documents/ingest", files=files, headers=token(client, "bob"))
    assert resp.status_code == 403  # engineer is not an admin
    # alice is an admin; tag the doc HR-only so it doesn't pollute later
    # public-visibility assertions
    resp = client.post("/documents/ingest", files=files, params={"roles": "hr"},
                       headers=token(client, "alice"))
    assert resp.status_code == 200


# ------------------------------------------------------- RBAC leakage tests
def test_public_doc_visible_to_everyone(client):
    for user in PASSWORDS:
        assert "handbook" in source_docs(ask(client, user, "How many PTO days do employees get?"))


def test_engineer_gets_engineering_docs(client):
    docs = source_docs(ask(client, "bob", "How do I deploy the payments service?"))
    assert "eng-runbook" in docs


def test_engineer_cannot_leak_hr_salary_data(client):
    """The critical test: Bob asks point-blank for salary data. The HR doc
    must not appear in sources, and the answer must not quote its content."""
    result = ask(client, "bob", "What is the exact salary band for a senior engineer?")
    assert "hr-bands" not in source_docs(result)
    assert "178000" not in result["answer"] and "215000" not in result["answer"]


def test_hr_user_sees_hr_doc_but_not_finance(client):
    carol = ask(client, "carol", "What is the salary band for a senior engineer?")
    assert "hr-bands" in source_docs(carol)
    fin = ask(client, "carol", "What is the projected Q3 revenue and runway?")
    assert "fin-forecast" not in source_docs(fin)
    assert "18.2" not in fin["answer"]


def test_finance_user_blocked_from_exec_memo(client):
    result = ask(client, "dave", "Tell me about Project Falcon acquisition plans")
    assert "exec-memo" not in source_docs(result)
    assert "Skyline" not in result["answer"]


def test_plain_employee_gets_only_public(client):
    for q in ["salary bands", "Q3 revenue", "Project Falcon", "deploy payments", "token leak"]:
        docs = source_docs(ask(client, "erin", f"What are the {q}?"))
        assert docs <= {"handbook"}, f"erin leaked docs {docs} via '{q}'"


def test_multi_role_doc_visible_to_both_roles_only(client):
    assert "incident" in source_docs(ask(client, "bob", "What happened with the leaked token?"))
    assert "incident" in source_docs(ask(client, "alice", "What happened with the leaked token?"))
    assert "incident" not in source_docs(ask(client, "carol", "What happened with the leaked token?"))
    assert "incident" not in source_docs(ask(client, "dave", "What happened with the leaked token?"))


def test_exec_sees_everything(client):
    docs = set()
    for q in ["PTO days", "deploy payments", "salary band", "Q3 revenue", "Project Falcon", "token leak"]:
        docs |= source_docs(ask(client, "alice", q))
    assert {"handbook", "eng-runbook", "hr-bands", "fin-forecast", "exec-memo", "incident"} <= docs


def test_document_listing_is_access_controlled(client):
    bob_docs = {d["doc_id"] for d in client.get("/documents", headers=token(client, "bob")).json()["documents"]}
    assert bob_docs == {"handbook", "eng-runbook", "incident"}
    erin_docs = {d["doc_id"] for d in client.get("/documents", headers=token(client, "erin")).json()["documents"]}
    assert erin_docs == {"handbook"}


def test_audit_log_records_queries(client):
    ask(client, "bob", "audit probe question")
    events = client.get("/audit", headers=token(client, "alice")).json()["events"]
    assert any(e["action"] == "query" and e["actor"] == "bob" and "audit probe" in e["detail"]["question"]
               for e in events)
    # non-admin cannot read the audit log
    assert client.get("/audit", headers=token(client, "bob")).status_code == 403


# ------------------------------------------- raw store layer (defense proof)
def test_store_level_filter_blocks_unauthorized_chunks(client):
    """Bypass the API entirely: even querying the vector store directly
    with an engineering filter cannot surface HR chunks."""
    from app.auth.rbac import UserContext, visibility_filter

    store = client.app.state.store
    engineer = UserContext(sub="mallory", name="Mallory", roles=["engineering"])
    chunks = store.search("senior engineer salary band compensation", visibility_filter(engineer), top_k=20)
    assert chunks, "expected some chunks (public+engineering)"
    assert all(c.metadata.get("department") in ("general", "engineering", "security") for c in chunks)
    assert not any(c.metadata.get("source") == "hr-bands" for c in chunks)
