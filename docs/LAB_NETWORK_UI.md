# Laboratory network, contracts and integration-status UI (UA-022)

Console **Labs** tab: adapter integration status (mode, result origin, dispatch blocked for every
physical adapter), capability search ranked by contract status and price, the laboratory list
with status changes (the API refuses `contracted` without a signed contract), per-lab contract
metadata, and a registration form limited to allow-listed food yeasts. Managing laboratories
needs `adapter.manage` (owner/admin); everyone else sees read-only data and policy errors.
