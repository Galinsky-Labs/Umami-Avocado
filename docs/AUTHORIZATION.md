# Authorization, research contracts and audit (UA-007)

`services/api/umami_api/policy.py` is a pure, deny-by-default policy engine. It decides
from structured facts only: principal kind (human | agent), membership role, active
research contracts and resource facts (project, author). Text from models, prompts or
request bodies never grants authority.

Evaluation order:

1. **Invariants** — unknown actions are denied; principal kind must match role
   (`agent` ⇔ agent principal); `experiment.submit_physical` is denied to everyone
   while `LAB_LIVE_SUBMISSION_ENABLED` is false (the API refuses to start if it is true);
   agents can never review claims, approve or reserve spend, approve or submit physical
   work, record PHYSICAL measurements, manage members, contracts, budgets or jobs, or read the audit log.
2. **Separation of duties** — `claim.review`, `spend.approve` and
   `experiment.approve_physical` are denied when the actor authored the subject.
3. **Role grants** — owner (all), admin (all except `spend.approve`), scientist (science
   authoring), reviewer (claim review, physical approval, audit), viewer (read).
4. **Research contracts** — an agent's non-read action needs an active, unexpired,
   unrevoked contract granted by a human that lists the action and, if project-scoped,
   the project. Contracts last at most 90 days.

Every denial and every allowed mutating action is written to `audit_events`. Denials use
an independent transaction so the failed request's rollback cannot erase them. A
PostgreSQL trigger rejects `UPDATE`/`DELETE` on the audit table.

| Route | Purpose |
| --- | --- |
| `GET /api/v1/workspaces/{id}/policy/decisions` | Caller's evaluated permissions (no side effects) |
| `GET/POST /api/v1/workspaces/{id}/research-contracts` | List / grant agent contracts |
| `DELETE /api/v1/workspaces/{id}/research-contracts/{cid}` | Revoke a contract |
| `GET /api/v1/workspaces/{id}/audit` | Recent audit events (owner, admin, reviewer) |
