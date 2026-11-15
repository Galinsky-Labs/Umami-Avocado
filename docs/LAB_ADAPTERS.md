# Laboratory adapter SDK and capability/contract registry (UA-013)

* `umami_api/labs/sdk.py` defines `LabAdapter` (capabilities, quote, submit, status,
  fetch_results, cancel) with typed `WorkOrder`, `Quote`, `Submission`, `ResultFile`
  (SHA-256 computed on construction) and `SubmissionState`. Each adapter declares a fixed
  result `origin`; results are never relabelled downstream.
* `dispatch_guard` must precede anything that could start physical work: any non-SIMULATED
  adapter raises `LiveSubmissionDisabled` while `LAB_LIVE_SUBMISSION_ENABLED` is false
  (which the API refuses to start with today).
* Built-ins (`labs/builtin.py`): `simulator` (deterministic, idempotent, SIMULATED CSV
  results) and `manual_cro` (UA-014: a supervised human performs every exchange; its
  `submit` is dispatch-guarded and never transmits).
* Registry: `laboratories` (adapter, status prospect→onboarding→contracted→suspended,
  validated capabilities restricted to allow-listed food yeasts) and `lab_contracts`
  (metadata only). A non-simulator lab can be marked `contracted` only with a signed contract.
  `GET …/laboratories/match?capability=&organism=` ranks contracted, signed, cheaper labs first.
  Managing labs is `adapter.manage` (owner/admin); agents can never manage adapters.
