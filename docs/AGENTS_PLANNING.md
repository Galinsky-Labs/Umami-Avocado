# Evidence-linked research agents and constrained planning (UA-019)

`POST …/projects/{id}/agent/plan` (`agent.run` + `experiment.draft`; agents need a research
contract) asks a **planning provider** for the next SIMULATED experiment.

* **Context** is structured and bounded: project objective, up to 20 claims and 20 sources (with
  review/verification status) and completed SIMULATED runs with their final biomass.
* **Providers** (`umami_api/agents/providers.py`) return only a strict `PlanDraft` schema:
  * `simulated` — deterministic rule-based local search over a temperature/pH grid, labelled
    `[SIMULATED PLANNER - deterministic rules, not an AI model]`. Used whenever
    `ANTHROPIC_API_KEY` is unset or `AGENT_PROVIDER=simulated`.
  * `claude` — Claude (`claude-opus-5-5`) through the official Anthropic SDK with structured
    outputs (`messages.parse`), medium effort and server-side refusal fallbacks
    (`fallbacks: "default"`). Refusals, truncation and transport failures become
    `provider_error` traces rather than exceptions.
* **Constraints**: every cited evidence ID must be one the platform supplied (hallucinated
  citations ⇒ `rejected`); a workspace with no evidence cannot be planned for. Accepted drafts
  become an immutable protocol version (allow-listed yeast, BSL-1, simulator assays) and a
  SIMULATED proposal that is preflighted. Execution remains a separate authorized step.
* **Traces** (`agent_traces`, append-only) record provider, model, SHA-256 and full JSON of the
  input, the raw draft, the outcome and errors — reviewable via `GET …/agent/traces` and in the
  console's Simulator tab.
