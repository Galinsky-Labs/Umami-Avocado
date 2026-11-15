# Durable orchestration and transactional outbox (UA-009)

* `jobs` rows are the queue. `orchestration.enqueue` runs inside the caller's transaction
  and writes a `job.queued` **outbox** event in the same commit, so state changes and
  their announcements cannot diverge. An `Idempotency-Key` header reuses an existing job.
* Workers claim with `SELECT … FOR UPDATE SKIP LOCKED` and a 5-minute lease. Expired
  leases are reclaimed (at-least-once execution — handlers must be idempotent).
* Failures retry with exponential backoff (2^attempt s, ≤300 s) until `max_attempts`, then
  the job is `dead` with a `job.dead` event. `PermanentJobError` skips retries. Handler work
  runs in a savepoint so a failed attempt leaves no partial writes.
* Handlers come from a closed registry (`@handler`). Kinds containing "physical" cannot be
  registered; no handler contacts a laboratory.
* The outbox dispatcher delivers unpublished events in order at least once (currently to the
  log; webhooks/notifications are later units). `GET …/events` shows the feed.
* Run the loop standalone (`PYTHONPATH=services/api:services/worker python -m umami_worker.main`)
  or in the API process with `EMBEDDED_WORKER=true` (used on the single free Render service).
