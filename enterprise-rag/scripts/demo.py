"""End-to-end RBAC demo: runs a user x question matrix against the app
in-process and prints which sources each user actually receives.

Usage:  python scripts/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

QUESTIONS = [
    ("How many PTO days do employees get?", "public doc"),
    ("How do I deploy the payments service?", "engineering doc"),
    ("What is the salary band for a senior engineer?", "HR doc"),
    ("What is the projected Q3 revenue?", "finance doc"),
    ("What is Project Falcon?", "executive doc"),
    ("What happened in security incident INC-2041?", "engineering+executive doc"),
]

USERS = ["alice", "bob", "carol", "dave", "erin"]


def main() -> None:
    app = create_app(get_settings())
    client = TestClient(app)
    with client:  # runs lifespan (seeds must already be ingested: scripts/seed.py)
        tokens = {
            u: client.post("/auth/token", json={"username": u, "password": f"{u}-pass"}).json()["access_token"]
            for u in USERS
        }
        for question, label in QUESTIONS:
            print(f"\n{'=' * 88}\nQ: {question}   [{label}]\n{'=' * 88}")
            for u in USERS:
                resp = client.post(
                    "/query",
                    json={"question": question},
                    headers={"Authorization": f"Bearer {tokens[u]}"},
                ).json()
                docs = [s["doc_id"] for s in resp["sources"]]
                status = ", ".join(docs) if docs else "-- ACCESS RESTRICTED / no authorized sources --"
                print(f"  {u:<7} {status}")


if __name__ == "__main__":
    main()
