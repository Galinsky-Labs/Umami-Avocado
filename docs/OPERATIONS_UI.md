# Physical runs, timelines and exception center (UA-017)

* `GET …/runs/{id}/timeline` merges run lifecycle, job retries/dead-letters, outbox events,
  artifacts and QC reports into one ordered timeline with severities.
* `GET /workspaces/{id}/exceptions` lists everything that needs a human: dead jobs, failed
  runs, non-passing QC without disposition, preflight-blocked proposals, CRO work orders
  awaiting approval and unverified agent-added sources (errors first).
* Console: **Runs** tab (per-project run list with origin badges and a timeline) and
  **Exceptions** tab. Today every run is SIMULATED; PHYSICAL runs will appear with a distinct
  badge once a supervised lab exists (UA-027).
