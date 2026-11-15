# Results explorer, comparisons and science exports (UA-018)

* `GET …/results/series?quantity_kind=&run_ids=…` — per-run time course (nested replicate
  mean/SD, biological n) in canonical units; superseded values excluded.
* `GET …/results/compare?run_ids=…` — run designs side by side with normalization (final
  biomass, apparent yield, µmax).
* `GET …/exports/measurements.csv` (optional `origin`, `run_id`) and `…/exports/dataset.json`
  (project, assays, runs, QC reports, measurements, with a SIMULATED notice). Every row keeps
  its origin and provenance; responses carry `X-Content-SHA256` and `X-Result-Origin`.
* Console **Results** tab: run picker, SVG time-course chart, comparison table and
  authenticated downloads that display the export digest.
