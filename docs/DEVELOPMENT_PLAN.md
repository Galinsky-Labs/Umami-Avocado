# Umami Avocado — 30 planned PRs

The canonical machine-readable work-unit registry is [registry/prs.json](../registry/prs.json). Detailed original issue-ready specifications are in the project planning package. The original architecture defines five build waves; biological progress is separately measured.

**UA-001 (this PR):** executable modular-monolith foundation, React SPA shell, FastAPI health, no-op worker, PostgreSQL/MinIO local Compose, test/lint scripts, ADRs, governance documentation and canonical PR registry.

**UA-002–UA-010:** API schemas, workspace persistence, scientific claims/units, research UI, authorization, budgets, durable jobs and simulator.

UA-002 implementation and review evidence: [canonical API contract](API_CONTRACT.md).
The versioned FastAPI models, deterministic OpenAPI export, generated TypeScript
and Python clients and drift/negative-path tests cover the existing inert health
and readiness boundary. Database persistence, authentication and physical execution
remain later units; generated contract artifacts are not deployment or scientific
acceptance. Actual PR/merge observations remain in the canonical registry.

Implemented units and their reference docs (actual merge state is in the registry):
UA-003 [database & identities](DATABASE.md), UA-007 [authorization](AUTHORIZATION.md),
UA-005 [measurements](MEASUREMENTS.md), UA-004 [evidence & claim review](EVIDENCE.md).

**UA-011–UA-018:** experiment studio, lineage, adapter framework, supervised lab workflow, immutable artifacts, QC, run/status UI and results explorer.

**UA-019–UA-025:** bounded research agents, next-round optimization, agent/provider/approval UI, yeast research modules and avocado growth tracking.

**UA-026–UA-030:** provider contract tests, one verified real-lab integration, two validated physical rounds and production operational hardening.

The first external-lab milestone requires genuine experiment results and written approval. **No unit is complete merely because it appears in this plan.**

UA-006 research console: the React console (`apps/web`) signs in with a `ua_` API token
(or performs the one-time owner bootstrap), switches workspaces, shows the project
portfolio (create, status changes, per-program counts), claims and the caller's live
policy decisions. In production the FastAPI service serves the built console at `/`
with a strict CSP; `/api/*` never falls back to the console.
