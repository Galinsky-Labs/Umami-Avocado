# Experiment studio, protocol versions and preflight (UA-011)

* **Protocol versions** are immutable (trigger-enforced). Posting an existing key creates the
  next version. Content is structured: organism (allow-listed BSL-1 food yeasts only:
  *S. cerevisiae*, *Cyberlindnera jadinii*, *Kluyveromyces marxianus*), medium, culture
  parameters, replicate design, assay keys, steps and an estimated cost.
* **Proposals** bind a protocol version to a project with a hypothesis, rationale, cited claims
  and/or sources and a target origin (`SIMULATED` or `PHYSICAL`). Agents can draft proposals
  under a project-scoped research contract; protocol authoring is workspace-level, so it needs a
  human or an unscoped contract.
* **Preflight** (`science/preflight.py`) is deterministic code over structured fields:
  organism allow-list, evidence linked and present, assays defined, an out-of-scope text screen
  (e.g. toxins, pathogens, gain-of-function — blocks for human redesign; not a substitute for
  institutional biosafety review), replication warning, and the target gate. `PHYSICAL`
  proposals always fail preflight while live submission is disabled, and their execution is
  denied by policy (`live_submission_disabled`).
* **Execute** re-evaluates preflight, then creates a SIMULATED run (UA-010) with a deterministic
  seed and an idempotency key per proposal; the proposal becomes `executed` when the run completes.
