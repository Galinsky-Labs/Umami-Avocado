# Evidence registry and scientific claim review (UA-004)

* **Sources** (`doi`, `url`, `book`, `dataset`, `internal_measurement`, `other`) are
  workspace-scoped and unique per identifier. Sources added by agents are recorded with
  `added_by_kind = agent` and stay unverified until a human reviewer, who did not add the
  source, verifies that it exists and says what is cited (`POST …/sources/{id}/verify`).
  This guards against fabricated citations.
* **Claims** move `draft → under_review → accepted | rejected`; `request_changes` returns
  to draft; an accepted claim can only be `retracted`. Evidence can be linked only in draft
  or under review. A claim needs at least one evidence link before submission.
* **Evidence links** reference exactly one source or one measurement with a stance:
  `supports`, `contradicts` or `context`.
* **Review** is a human decision (`claim.review`): agents and scientists cannot review, and
  nobody reviews their own claim (separation of duties). Reviews are append-only (trigger).
* **Acceptance rule**: at least one *supporting* link to a human-verified source or to a
  `PHYSICAL` measurement. Simulated results alone can never establish a claim.
