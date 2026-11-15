# Deterministic laboratory simulator and digital milestone (UA-010)

`umami_api/science/simulator.py` is a seeded Monod batch-culture model of *S. cerevisiae* on
glucose (cardinal-temperature and pH response, yield-limited growth, growth-associated free
glutamate). Biological replicates perturb µmax; technical replicates add 2 % measurement noise.
The same design and seed always produce identical output. **It is not calibrated against real
data and every value it produces is labelled `SIMULATED`.**

Flow: `POST …/projects/{id}/simulated-runs` (`experiment.submit_simulated`; agents need a
research contract) creates an `experiment_runs` row and a durable `simulator.run` job
(UA-009, `Idempotency-Key` supported). The worker writes immutable SIMULATED measurements
against auto-created `sim-*` assays (method text states they are simulated), stores a
final-time summary and emits `run.completed`. Redelivery of a completed run is a no-op.

`GET …/projects/{id}/digital-milestone` reports the digital loop: completed simulated run →
SIMULATED measurements → claim citing them → claim submitted to human review. Simulated
evidence alone still cannot get a claim accepted (UA-004), and `physical_results_exist`
stays false until real, supervised laboratory work exists.

The console's **Simulator** tab queues runs, polls their state and shows the milestone.
