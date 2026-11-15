# Immutable laboratory artifacts and provenance (UA-015)

* Bytes are content-addressed by SHA-256. Default store: PostgreSQL `artifact_blobs` (bytea,
  immutable). `ARTIFACT_STORE=s3` selects an S3-compatible store only when `S3_ENDPOINT`,
  `S3_BUCKET`, `S3_ACCESS_KEY` and `S3_SECRET_KEY` are all set (and boto3 is installed);
  otherwise PostgreSQL is used. Every read re-verifies the digest.
* `artifacts` rows are immutable (trigger) and record name, media type (allow-list), size,
  digest, store, permanent origin, source (upload, adapter, simulator, cro_exchange, export)
  and provenance (who/what kind of principal recorded it, when, free description, adapter or
  exchange references). Origin must match a linked run or material.
* Upload: `POST …/projects/{id}/artifacts?name=&origin=&description=` with the raw file as body
  (≤10 MB). PHYSICAL uploads need a human with `measurement.record_physical` and a provenance
  description; agents cannot upload. Download returns `X-Content-SHA256` and `X-Result-Origin`.
* Ingestion (`…/artifacts/{id}/ingest`, once per artifact): a results CSV
  (quantity, unit, time_h, biological_replicate, [technical_replicate], value, [origin]) becomes
  immutable measurements with the **artifact's** origin and `artifact:{id}:row=N` provenance.
  A row whose origin column disagrees with the artifact is rejected — file text cannot relabel
  provenance. Units are dimension-checked against each assay.
* `/api/readiness` now reports `artifact_store_connected` (true when the PostgreSQL store is reachable).
