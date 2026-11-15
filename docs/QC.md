# Scientific normalization, reproducibility and quality control (UA-016)

* `science/qc.py` evaluates one assay dataset (canonical units, superseded values excluded):
  plausibility range per quantity kind (error), fewer than 3 biological replicates (warning),
  between-biological-replicate CV above 20 % (warning) and modified-z-score outliers above
  3.5 (warning). Status is `fail` with any error, else `warn`, else `pass`.
* QC reports are immutable and fingerprint the exact measurement set (SHA-256 of IDs).
  Disposition (`accepted`/`rejected`) is a separate, single, append-only human decision under
  `qc.review` — never by the report's generator, never by an agent, and failing reports
  cannot be accepted. QC flags never modify measurements.
* `GET …/runs/{id}/normalization`: endpoint biomass/substrate, apparent biomass yield
  (g/g) and maximum specific growth rate between sampling points.
* `GET …/reproducibility?origin=`: groups completed runs by design (ignoring seed and label)
  and reports the between-run CV of final biomass (reproducible when ≤ 20 %).
