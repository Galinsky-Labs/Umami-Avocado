# Biological-material lineage and custody (UA-012)

* `materials` (strain, culture, sample, extract, plant_material, reagent) carry a permanent
  `origin` (SIMULATED | PHYSICAL), custodian, location and free attributes. Labels are unique
  per workspace. Agents may register only SIMULATED material (research contract required).
* `lineage_edges` are created only by `POST …/materials/derive`, which always creates a new
  child, so the graph is acyclic by construction. Parents and child must share an origin;
  only active materials can be derived from. `GET …/materials/{id}/lineage` returns the
  connected ancestor/descendant graph (bounded depth).
* `custody_events` form an append-only chain (trigger-enforced): registered, transferred,
  received, stored, consumed, disposed. Transfers must name the receiver. Consumed or disposed
  material accepts no further events. **`shipped` is a physical dispatch and is denied to
  everyone while live submission is disabled** (policy `material.ship`); agents can never
  record custody.
* New policy actions: `material.register`, `material.custody`, `material.ship`, plus the
  actions reserved for UA-013–UA-016 (`adapter.manage`, `cro.exchange`, `cro.dispatch`,
  `artifact.upload`, `qc.review`). `cro.dispatch` joins the physical-dispatch invariant.
