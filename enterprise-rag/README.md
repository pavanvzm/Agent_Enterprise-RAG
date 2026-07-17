# Enterprise RAG with Role-Based Access Control

A retrieval-augmented generation (RAG) service that wraps an internal
knowledge base in a secure Q&A API. The defining property: **access
control is enforced at retrieval time inside the vector database**, so a
chunk a user isn't entitled to never enters the prompt — there is nothing
to "hide" from the LLM afterwards.

**Stack:** Python · FastAPI · LangChain (splitters + prompt chains) ·
Chroma (embedded vector DB) · JWT (local HS256 dev issuer *or* Auth0
RS256/JWKS) · SQLite audit log

---

## Architecture

```
            ┌──────────────────────────────────────────────────────────┐
            │                        FastAPI                            │
            │                                                           │
  POST /auth/token ──► Local dev issuer (HS256)   ── or ──  Auth0 JWKS  │
                          (mirrors OAuth2               verification    │
                           password grant)               (RS256)        │
            │                                                           │
  POST /query ──► JWT ──► UserContext{sub, roles}                       │
                              │                                         │
                              ▼                                         │
                  visibility_filter(roles)                              │
                  = {$or: [{role_eng: true}, {role_public: true}, ...]} │
                              │                                         │
                              ▼                                         │
              Chroma vector search  ◄──  RBAC metadata filter           │
              (only authorized chunks are ever returned)                │
                              │                                         │
                              ▼                                         │
              LangChain prompt chain ──► LLM (OpenAI-compatible)        │
                              │            or offline extractive mode   │
                              ▼                                         │
              grounded answer + cited sources                           │
            │                                                           │
  POST /documents/ingest (admin) ──► front-matter ACL ──► chunk ──►     │
      role flags in metadata ──► upsert into Chroma                     │
            │                                                           │
  All security events ──► SQLite audit log ──► GET /audit (admin)       │
            └──────────────────────────────────────────────────────────┘
```

## Security model

| Decision | Rationale |
|---|---|
| **Retrieval-time filtering** | Unauthorized chunks never leave the DB, never enter the prompt, and cannot leak via prompt-injection or LLM error. Post-hoc filtering of LLM output is *not* used as a control. |
| **Flat roles, no hierarchy** | An executive is simply granted every department role. Flat models are auditable; implicit hierarchies surprise auditors. |
| **Role flags in metadata** | Chroma metadata is scalar-only, so `allowed_roles: [hr, executive]` is expanded to `{role_hr: true, role_executive: true}` and matched with `$or` equality filters — no substring hacks. |
| **`public` is an explicit role** | Every authenticated user gets `role_public`; company-wide docs declare it in their ACL. |
| **`admin` grants no visibility** | Admin gates ingestion/deletion/audit only. Privilege and visibility are separate axes. |
| **Access-controlled listings** | `GET /documents` is filtered too — metadata (titles, departments) is itself sensitive. |
| **Everything audited** | Token issuance, ingestion, deletion, and every query (actor, roles, retrieved sources) land in an append-only log. |
| **Same answer shape for "no results"** | "No accessible documents" is indistinguishable from "no such document" — the API doesn't confirm privileged content exists. |

## Quickstart

```bash
pip install -r requirements.txt

# 1. load the sample corpus (6 docs across 5 departments with ACLs)
python scripts/seed.py --reset

# 2. run the API
uvicorn app.main:app --reload

# 3a. demo console  → http://localhost:8000
# 3b. OpenAPI docs  → http://localhost:8000/docs
# 3c. RBAC matrix demo (no server needed, runs in-process)
python scripts/demo.py
```

Demo identities (local mode only):

| User | Persona | Roles |
|---|---|---|
| `alice` / `alice-pass` | CTO | executive, engineering, hr, finance, **admin** |
| `bob` / `bob-pass` | Engineer | engineering |
| `carol` / `carol-pass` | HR | hr |
| `dave` / `dave-pass` | Finance | finance |
| `erin` / `erin-pass` | Employee | — (public docs only) |

Try it: sign in as Bob and ask *"What is the salary band for a senior
engineer?"* — he gets only engineering/public sources. Sign in as Carol
and the HR document appears. Sign in as Alice and everything appears.

### cURL

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"bob","password":"bob-pass"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST localhost:8000/query \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"How do I deploy the payments service?"}'
```

## API

| Endpoint | Auth | Description |
|---|---|---|
| `POST /auth/token` | — (local mode) | Issue a demo JWT |
| `GET /auth/dev-users` | — (local mode) | List demo identities |
| `POST /query` | any user | RBAC-filtered RAG answer + sources |
| `GET /documents` | any user | List docs visible to the caller |
| `POST /documents/ingest` | admin | Upload a doc (`?roles=` overrides front-matter ACL) |
| `DELETE /documents/{id}` | admin | Remove a document's chunks |
| `GET /audit` | admin | Recent audit events |

## Document ACLs

Documents declare their access list in YAML front matter:

```markdown
---
title: Q3 Financial Forecast
department: finance
allowed_roles: [finance]        # comma-separated string also accepted
---
...
```

Omitting the front matter defaults to `public`. Ingestion is idempotent:
re-ingesting the same `doc_id` replaces its chunks.

## Running with Auth0

1. Create an **API** in Auth0, note its identifier (→ `RAG_AUTH0_AUDIENCE`).
2. Create roles (`engineering`, `hr`, `finance`, `executive`, `admin`) and
   assign them to users.
3. Add a **post-login Action** to inject the namespaced roles claim:

   ```js
   exports.onExecutePostLogin = async (event, api) => {
     const ns = "https://enterprise-rag/roles";
     api.accessToken.setCustomClaim(ns, event.authorization?.roles ?? []);
   };
   ```

4. Configure the service:

   ```bash
   RAG_AUTH_MODE=auth0 \
   RAG_AUTH0_DOMAIN=your-tenant.us.auth0.com \
   RAG_AUTH0_AUDIENCE=https://enterprise-rag-api \
   uvicorn app.main:app
   ```

   The local issuer and `/auth/dev-users` are automatically disabled; clients
   obtain tokens from Auth0 (ROPG or SPA + PKCE) and the service verifies
   RS256 signatures against the tenant JWKS with audience/issuer checks.

## Models: offline by default, production-ready when keyed

The system runs **fully offline** out of the box so CI and demos never
depend on external services:

- *Embeddings:* deterministic hashed n-gram vectors (lexical only).
- *Answers:* extractive composer that quotes retrieved passages with
  citations, clearly labelled.

Set `RAG_OPENAI_API_KEY` (works with any OpenAI-compatible endpoint via
`RAG_OPENAI_BASE_URL`) to switch to real embeddings
(`text-embedding-3-small`) and generative answers (`gpt-4o-mini` by
default). `pip install sentence-transformers` enables a third, local
embedding option (`all-MiniLM-L6-v2`). Provider selection:
`RAG_EMBEDDING_PROVIDER` / `RAG_LLM_PROVIDER` = `auto | openai |
sentence-transformers | hashed` / `auto | openai | fallback`.

## Tests

```bash
pytest -q        # 15 tests
```

The suite is security-first. Beyond auth (401/403) coverage, it proves:

- an engineer asking **point-blank** for salary data receives no HR
  chunks and the answer contains no salary figures;
- an HR user can't surface finance data; finance can't surface the exec
  memo; a role-less employee can *only* ever receive public chunks;
- multi-role docs (engineering + executive) are visible to exactly those
  two roles;
- document *listings* are filtered per caller;
- **raw store layer**: querying Chroma directly with an engineering
  filter can never return HR chunks (the control holds below the API).

## Production hardening roadmap

- Replace dev user directory with Auth0/Okta exclusively; rotate
  `RAG_JWT_SECRET` into a secrets manager.
- Move the audit log to your SIEM; add tamper-evident chaining (hash
  each event with its predecessor).
- Rate-limit `/query` and `/auth/token`; add per-user cost quotas.
- Encryption at rest for the Chroma volume; TLS everywhere (terminate at
  ingress or sidecar).
- Prompt-injection defense-in-depth: content sanitization on ingest,
  output filtering for credential-shaped strings.
- Document-level versioning + ACL-change re-indexing pipeline; periodic
  access reviews against the audit log.
- Scale-out: swap embedded Chroma for Qdrant/pgvector behind the same
  `VectorStore` interface (two classes change, nothing else).

## Project layout

```
app/
  config.py            settings (env-driven, RAG_ prefix)
  auth/jwt_handler.py  local issuer + Auth0 JWKS verification
  auth/rbac.py         role model, visibility filters, dev users
  rag/embeddings.py    openai / sentence-transformers / hashed providers
  rag/store.py         Chroma wrapper — every read takes an RBAC filter
  rag/ingest.py        front-matter parsing, LangChain chunking, upsert
  rag/llm.py           OpenAI-compatible + offline extractive providers
  rag/chain.py         retrieval → grounded generation
  api/                 auth / documents / query / audit routes
  audit.py             append-only SQLite audit log
  static/index.html    demo console
data/sample_docs/      6 sample internal docs with ACLs
scripts/seed.py        load the sample corpus
scripts/demo.py        user × question RBAC matrix demo
tests/test_rbac.py     15 tests incl. cross-role leakage proofs
```
