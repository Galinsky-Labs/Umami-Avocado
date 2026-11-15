# Umami Avocado

A general-purpose platform for AI-directed scientific research using real laboratories. The first targets are savory food-yeast biomass (M1), yeast extract (M2), and eventually avocado cultivation (A1).

> **Foundation only.** This repository contains software scaffolding, not functional physical-lab integrations. Live lab orders are disabled, no biological experiments have occurred, and no food ingredient has been approved for human consumption.

## Requirements

- Node.js 22, pnpm 9 (via Corepack)
- Python 3.12–3.13, uv
- Docker with Compose plugin (for PostgreSQL and MinIO locally)

## Local development

```sh
corepack enable
corepack pnpm install --no-frozen-lockfile
corepack pnpm dev
# In another terminal
uv run --project services/api uvicorn umami_api.main:app --app-dir services/api --host 127.0.0.1 --port 8000
# In another terminal: inert worker
PYTHONPATH=services/worker uv run --project services/api python -m umami_worker.main
# Local infrastructure
# docker compose -f infra/compose/docker-compose.yml up -d
```

PostgreSQL is wired into the API (UA-003, see [docs/DATABASE.md](docs/DATABASE.md)): set `DATABASE_URL`, run `PYTHONPATH=services/api uv run --project services/api python -m umami_api.migrate`, and set `UMAMI_BOOTSTRAP_TOKEN` to create the first owner via `POST /api/v1/bootstrap`. MinIO artifact storage is not yet wired (UA-015). Never use these development credentials outside a local machine.

## What exists today (digital only)

Authenticated, workspace-scoped research API and console: identities and tokens (UA-003),
policy engine with agent research contracts and audit (UA-007), evidence registry and human
claim review (UA-004), measurement ontology (UA-005), console (UA-006), spending ledger with a
default $0 cap (UA-008), durable jobs/outbox (UA-009), deterministic SIMULATED lab simulator and
digital milestone (UA-010), experiment studio with preflight (UA-011) and evidence-linked
planning agents with a labelled simulated provider or Claude when `ANTHROPIC_API_KEY` is set
(UA-019). See `docs/*.md`. No physical laboratory is connected and live submission cannot be enabled.

## Quality gates

```sh
node scripts/validate-pr-registry.mjs
corepack pnpm -r typecheck
corepack pnpm -r test
corepack pnpm -r lint
corepack pnpm -r build
TEST_DATABASE_URL=postgresql://umami:umami_local_only@localhost:5432/umami \
  uv run --project services/api pytest services/api/tests services/worker/tests
uv run --project services/api ruff check services
```

## Roadmap and boundaries

The single canonical source is [registry/prs.json](registry/prs.json), comprising 30 work units. Read [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md), [AGENTS.md](AGENTS.md) and [docs/SECURITY.md](docs/SECURITY.md). UI design reference and detailed PR specifications are in the previous architecture package. Vendor APIs and science outcomes are never presumed implemented.
