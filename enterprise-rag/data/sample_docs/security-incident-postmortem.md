---
title: Security Incident Postmortem INC-2041
department: security
allowed_roles: [engineering, executive]
---

# Postmortem: INC-2041 Credential Leak (Engineering + Executive)

## Summary
On June 12, a contractor's GitHub personal access token with `repo` scope was
committed to a public mirror of an internal tooling repository. The token was
live for approximately 9 hours before automated scanning revoked it.

## Impact
Audit logs confirm two private repositories were cloned by an unrecognized
IP during the exposure window: `drone-sim-tools` and `ci-scripts`. No
customer data, production credentials, or signing keys were present in
either repository.

## Root Cause
The mirror job excluded `.env` files but not `scripts/legacy/pat_backup.txt`.
Branch protection on the mirror did not require secret-scanning to pass.

## Remediation
1. All mirrors now block push on failed secret-scanning (completed).
2. Contractor tokens are issued with 7-day expiry and fine-grained scope
   (completed).
3. TruffleHog runs nightly over full history (in progress, due July 30).

## Lessons
Secret-scanning must gate the sync path, not just developer pushes. Mirror
pipelines need the same controls as first-party repos.
