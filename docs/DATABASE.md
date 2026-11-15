# Database, migrations and workspace scoping (UA-003)

PostgreSQL is the system of record. SQLAlchemy 2 models live in
`services/api/umami_api/models.py`; every schema change is an Alembic revision in
`services/api/umami_api/migrations/versions` (hand-reviewed, never generated at
deploy time). A test asserts the migrated schema equals the models exactly.

```sh
# apply migrations (DATABASE_MIGRATION_URL, else DATABASE_URL)
PYTHONPATH=services/api uv run --project services/api python -m umami_api.migrate
# run the PostgreSQL integration tests against a disposable database
TEST_DATABASE_URL=postgresql://umami:umami_local_only@localhost:5432/umami \
  uv run --project services/api pytest services/api/tests
```

`umami_api.migrate` takes a PostgreSQL advisory lock so concurrent starts cannot
race. In production the API start command migrates first; Neon's direct host is
used for migrations and the `-pooler` host for runtime (`prepare_threshold=None`
keeps psycopg compatible with transaction pooling). Without `DATABASE_URL` the API
runs in foundation-only mode: `/api/readiness` reports `foundation-only` and every
`/api/v1` route returns `503 unavailable` rather than pretending to succeed.

## Identities

| Table | Purpose |
| --- | --- |
| `principals` | Human or **agent** identities. `kind` is immutable and never inferred from text. |
| `workspaces` | The tenancy boundary. |
| `memberships` | One role per principal per workspace: owner, admin, scientist, reviewer, viewer, agent. Agent principals hold exactly the `agent` role. |
| `api_tokens` | Bearer tokens (`ua_…`). Only a SHA-256 digest and a short display prefix are stored; the secret is shown once. Agent tokens expire within 90 days. |
| `projects` | Workspace-scoped research projects (M1, M2, A1, OTHER). |

## Scoping rules

* Every research record carries `workspace_id`; route handlers resolve the caller's
  membership first (`security.resolve_workspace`) and query only within it.
* Non-members receive `404 not_found`, so workspace and record existence is not disclosed.
* The first human owner is created once through `POST /api/v1/bootstrap` with the
  `X-Bootstrap-Token` header equal to `UMAMI_BOOTSTRAP_TOKEN`; afterwards it returns `409`.
* Agents cannot create workspaces or principals. Only owners appoint owners.

Detailed authorization policy (separation of duties, research contracts, audit) is UA-007.
