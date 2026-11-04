# Optional Owner LIVE deployment

Offline routes are public and independent of Neon/Meta. Owner panel requires per-request server-validated Basic authentication over HTTPS; credentials never appear in JS or URLs. Database access is lazy and fails closed only for LIVE. Set PROOF_LIVE_PANEL=1, PROOF_LIVE_ENABLED=0, PROOF_LIVE_PROVIDER=simulated, PROOF_LIVE_PERSISTENCE=postgres, plus securely supplied DATABASE_URL (sslmode=verify-full), PROOF_LIVE_OWNER_SECRET and PROOF_LIVE_CAMPAIGN. Do not configure a Meta key for disabled mode. PROOF_ALLOWED_HOSTS/PORT retain existing Render controls.

Initialize schema explicitly from migrations/001_proof_live_postgres.sql; provision campaigns separately with enabled=false, ceiling1, budget_usd0.05, unit_usd0.05. Runtime never initializes/reset quotas. Authenticated `/api/live/enable` activates only the configured campaign and sends no request; `/api/live/disable` disables it without cancelling an external request already sent. Spent or uncertain reservations are not refunded.

Staging uses only SimulatedProvider and no Meta key. An opt-in startup certification script scripts/certify_live_cloud.py runs only with PROOF_CLOUD_CERTIFY=1; it creates a unique synthetic test campaign and makes no Meta call. Do not use this flag on public production.

Real transport configuration is Render-only and additionally requires PROOF_LIVE_CALL_AUTHORIZED=1, explicit LIVE configuration and server Meta key. Do not configure it until the Owner separately authorizes the first payable request. Initial real case is pinned PM01-02, model muse-spark-1.3 Standard, 4096 completion-token cap, one POST and no retry/fallback. Missing/invalid response never becomes invented extraction or replay.

Rollback: retain original deploy snapshot and commit d3308c9273b7c8b767fa2496d0e8e5f8393ef54e. Disable campaign and LIVE, remove Meta key, then deploy the retained prior artifact or prior commit after verifying the source/config identity. Do not rewrite Git or erase PostgreSQL attempts. Previous offline code must not start with a Meta key configured. Autodeploy stays OFF. Database schema is additive and does not affect the original offline revision.
