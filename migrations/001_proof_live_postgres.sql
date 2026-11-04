
CREATE TABLE IF NOT EXISTS proof_live_campaign (
 id text PRIMARY KEY, ceiling integer NOT NULL CHECK (ceiling BETWEEN 1 AND 10),
 enabled boolean NOT NULL DEFAULT false, budget_usd numeric(12,6) NOT NULL CHECK(budget_usd>=0),
 unit_usd numeric(12,6) NOT NULL CHECK(unit_usd>0));
CREATE TABLE IF NOT EXISTS proof_live_attempt (
 id text PRIMARY KEY, campaign text NOT NULL REFERENCES proof_live_campaign(id),
 request_id uuid NOT NULL UNIQUE, state text NOT NULL CHECK(state IN ('RESERVED','SENDING','UNCERTAIN','DONE')),
 reserved_usd numeric(12,6) NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 evidence jsonb NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS proof_live_single_active ON proof_live_attempt ((true))
 WHERE state IN ('RESERVED','SENDING','UNCERTAIN');
