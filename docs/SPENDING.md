# Quotes, ledger, reservations and spending caps (UA-008)

All amounts are integer US cents. Nothing in this codebase places an order or moves money.

* **Budgets**: one cap per project (`PUT …/projects/{id}/budget`, `budget.manage`). Raising or
  lowering the cap posts a balanced `funding → available` entry; a cap cannot drop below
  reserved + spent funds.
* **Ledger**: append-only, double-entry (`funding`, `available`, `reserved`, `spent`). Every
  posting must sum to zero — enforced in code and by a deferred PostgreSQL constraint trigger;
  UPDATE/DELETE are rejected by trigger.
* **Quotes** are recorded vendor prices, labelled `SIMULATED` or `PHYSICAL`. Agents may only
  record SIMULATED quotes; simulated quotes can never back a reservation.
* **Reservations**: `requested → approved | rejected`, `approved → released`. Approval
  (`spend.approve`) is owner-only, never by the requester (separation of duties), never by
  agents, and must fit under **both** the project cap and the platform cap
  `LAB_MAX_AUTHORIZED_SPEND_USD` (default `0`, so every approval is refused with
  `limit_exceeded` until the owner deliberately raises it). Approval row-locks the budget to
  prevent concurrent over-commitment.
* `consumed`/`spent` exist in the schema but no route reaches them: consumption requires a
  supervised physical order (UA-027) and a physical-lab authorization gate.
