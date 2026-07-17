---
title: Payments Service Engineering Runbook
department: engineering
allowed_roles: [engineering]
---

# Payments Service Runbook (Internal — Engineering Only)

## Architecture
The payments service is a Python/FastAPI microservice deployed to EKS in the
`payments-prod` namespace. It talks to Stripe over a private egress proxy and
stores idempotency keys in Redis (db 3) with a 24h TTL.

## Deploy Process
1. Merge to `main`; CI builds image `ghcr.io/northwind/payments:<sha>`.
2. ArgoCD auto-syncs to staging. Run the smoke suite: `make smoke-staging`.
3. Promote to production with `argocd app promote payments-prod`.
4. Watch the `payments-error-rate` Grafana panel for 15 minutes.

## On-Call
Primary on-call rotates weekly on Mondays 10:00 PT. Escalation order:
primary -> secondary -> Eng Manager. PagerDuty service key is in 1Password
under "Payments PD".

## Known Failure Modes
If Stripe webbacks pile up, check the egress proxy first (75% of past
incidents). Redis OOM presents as idempotency 409s — bump `maxmemory` before
investigating application code.
