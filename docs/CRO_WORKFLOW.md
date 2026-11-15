# Supervised manual CRO workflow and secure file exchange (UA-014)

1. A scientist creates a **work order** from a PHYSICAL proposal for a `manual_cro`
   laboratory. The platform freezes the order package (proposal + exact protocol version) as
   an immutable JSON artifact and records its SHA-256 — that digest is what gets approved.
2. A **different human** with `experiment.approve_physical` (reviewer/owner) approves it.
   Approval requires all preflight blockers except the physical gate to pass and, when the
   protocol has an estimated cost, an *approved* spending reservation covering it (impossible
   while `LAB_MAX_AUTHORIZED_SPEND_USD=0`). Approval dispatches nothing.
3. **Dispatch** (`cro.dispatch`) is a physical action and is denied to everyone while live
   submission is disabled. Returned files can only be recorded for dispatched orders, so the
   inbound path is closed today.
4. Every exchange step (package, approval with digest, notes, inbound files) is an append-only
   `exchange_items` entry; files are immutable artifacts with `source=cro_exchange`.

Files are exchanged only through authenticated API calls; nothing is e-mailed or transmitted
by the platform. Agents cannot create, approve or dispatch work orders.
