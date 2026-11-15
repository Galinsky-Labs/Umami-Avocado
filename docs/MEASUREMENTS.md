# Measurement ontology, units, assays and replicates (UA-005)

* `umami_api/science/units.py` defines units by SI dimension vectors (mass, length, time,
  amount, temperature) with scale/offset. Conversion requires identical dimensions.
  Instrument-relative or logarithmic scales (OD600, pH, rpm) are **non-convertible**:
  OD600 is never silently turned into dry-cell weight.
* Quantity kinds (biomass concentration, glutamate, IMP/GMP nucleotides, protein content,
  yield, specific growth rate, temperature, pH, …) declare a canonical unit and the
  admissible units. `GET /api/v1/ontology` publishes the vocabulary; `POST /api/v1/ontology/convert` converts.
* **Assays** are workspace-scoped, versioned methods bound to one quantity kind and unit.
  Redefining a key creates the next version; measurements keep referencing the version used.
* **Measurements** are immutable (PostgreSQL trigger rejects UPDATE/DELETE). Each stores the
  reported value/unit and the value converted to the assay's canonical unit. Corrections are new
  records with `supersedes_id`, which must keep the same origin and assay.
* `origin` is permanent provenance: `SIMULATED` or `PHYSICAL`. PHYSICAL requires a human
  scientist (agents are denied by policy) and a provenance description; immutable artifact
  ingestion for physical results is UA-015.
* **Replicates**: technical replicates (repeat measurements of one sample) are averaged first;
  mean and sample SD are computed across biological replicates (independent cultures). The
  summary endpoint requires an origin, so SIMULATED and PHYSICAL results are never pooled.
