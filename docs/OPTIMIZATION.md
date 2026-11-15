# Bounded optimization and next-experiment selection (UA-020)

`POST …/projects/{id}/optimization/rounds` (`agent.run`; agents need a contract):

* Fits a pure-Python Gaussian-process surrogate (RBF kernel, standardized outcomes) to
  completed runs of **one** origin for the chosen objective (`final_biomass`, `biomass_yield`,
  `final_glutamate`), then ranks a 9×9×9 candidate grid inside the caller's box by
  upper-confidence bound (β = 2) with a minimum spacing between picks. With fewer than three
  observations it returns a deterministic maximin space-filling design.
* **Bounds** must lie within simulator/protocol limits (T 4–45 °C, pH 3–8, glucose 1–150 g/L);
  batch size ≤ 6.
* `queue_simulated_runs: true` additionally requires `experiment.submit_simulated`, queues
  SIMULATED runs only (idempotent per round and pick) and is capped at 24 simulated runs per
  project per day (`limit_exceeded`). Nothing here can create physical work.
* Every round is stored append-only (`optimization_rounds`) with the observations used, the
  suggestions with predicted mean/SD and the queued run IDs.
