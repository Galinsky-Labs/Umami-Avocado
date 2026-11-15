# Research-agent console and reviewable execution traces (UA-021)

Console **Agents** tab:
* agent principals and their research contracts (purpose, actions, expiry, revoked state);
  owners/admins grant expiring contracts limited to the agent-grantable actions and revoke them
  with one click (the API enforces `contract.manage`);
* next-experiment selection (UA-020): suggest a bounded batch or suggest-and-queue SIMULATED runs;
* the workspace-wide trace queue (`GET /workspaces/{id}/agent/traces[?outcome=]`): provider,
  model, requester, outcome badge, input SHA-256, raw draft, validation errors and the exact
  input context, expandable per trace.
