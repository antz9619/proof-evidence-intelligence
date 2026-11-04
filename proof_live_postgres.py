"""Transactional PostgreSQL ledger. No fallback and no external-call transaction."""
import json
from urllib.parse import urlsplit, parse_qs
from proof_live import Rejected

SCHEMA = '''
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
'''

class Ledger:
    def __init__(self, url, campaign):
        parsed=urlsplit(url)
        if parsed.scheme not in ('postgres','postgresql') or parse_qs(parsed.query).get('sslmode') != ['verify-full']:
            raise ValueError('PostgreSQL requires sslmode=verify-full')
        self.url,self.campaign=url,campaign
        # Lazy database access: a Neon outage must not prevent offline startup.

    def connect(self):
        import psycopg
        try:
            return psycopg.connect(self.url, connect_timeout=5, options='-c statement_timeout=5000 -c lock_timeout=3000')
        except Exception:
            raise Rejected(503,'LIVE_PERSISTENCE_UNAVAILABLE') from None

    def status(self):
        with self.connect() as db:
            row=db.execute('SELECT ceiling,enabled,budget_usd,unit_usd FROM proof_live_campaign WHERE id=%s',(self.campaign,)).fetchone()
            if row is None: raise Rejected(503,'CAMPAIGN_NOT_PROVISIONED')
            count,uncertain,total=db.execute("SELECT count(*),count(*) FILTER(WHERE state IN ('RESERVED','SENDING','UNCERTAIN')),coalesce(sum(reserved_usd),0) FROM proof_live_attempt WHERE campaign=%s",(self.campaign,)).fetchone()
            return dict(ceiling=row[0],enabled=row[1],reserved=count,remaining=max(0,row[0]-count),uncertain_attempts=uncertain,monetary_cost_cap_guaranteed=False,reserved_usd=str(total))

    def acquire(self):
        return None  # reservation transaction + unique active index coordinate all processes

    def release(self, handle):
        pass

    def reserve(self, request_id, evidence):
        import psycopg
        from psycopg.types.json import Jsonb
        try:
            with self.connect() as db:
                row=db.execute('SELECT ceiling,enabled,budget_usd,unit_usd FROM proof_live_campaign WHERE id=%s FOR UPDATE',(self.campaign,)).fetchone()
                if row is None: raise Rejected(503,'CAMPAIGN_NOT_PROVISIONED')
                if not row[1]: raise Rejected(403,'LIVE_DISABLED')
                if db.execute('SELECT 1 FROM proof_live_attempt WHERE request_id=%s',(request_id,)).fetchone(): raise Rejected(409,'REQUEST_ALREADY_RESERVED')
                if db.execute("SELECT 1 FROM proof_live_attempt WHERE state IN ('RESERVED','SENDING','UNCERTAIN')").fetchone(): raise Rejected(409,'CAMPAIGN_UNCERTAIN_REVIEW_REQUIRED')
                count,total=db.execute('SELECT count(*),coalesce(sum(reserved_usd),0) FROM proof_live_attempt WHERE campaign=%s',(self.campaign,)).fetchone()
                if count>=row[0] or total+row[3]>row[2]: raise Rejected(429,'QUOTA_EXHAUSTED')
                db.execute("INSERT INTO proof_live_attempt(id,campaign,request_id,state,reserved_usd,evidence) VALUES(%s,%s,%s,'RESERVED',%s,%s)",(evidence['execution']['id'],self.campaign,request_id,row[3],Jsonb(evidence)))
        except psycopg.errors.UniqueViolation:
            raise Rejected(409,'INFERENCE_IN_PROGRESS') from None

    def write(self,evidence,state):
        from psycopg.types.json import Jsonb
        with self.connect() as db:
            result=db.execute('UPDATE proof_live_attempt SET state=%s,evidence=%s WHERE id=%s AND campaign=%s',(state,Jsonb(evidence),evidence['execution']['id'],self.campaign))
            if result.rowcount != 1: raise Rejected(503,'ATTEMPT_NOT_RESERVED')

    def enable(self):
        with self.connect() as db:
            row=db.execute("SELECT id FROM proof_live_campaign WHERE id=%s FOR UPDATE",(self.campaign,)).fetchone()
            if row is None: raise Rejected(503,"CAMPAIGN_NOT_PROVISIONED")
            if db.execute("SELECT 1 FROM proof_live_attempt WHERE state IN ('RESERVED','SENDING','UNCERTAIN')").fetchone():
                raise Rejected(409,"CAMPAIGN_UNCERTAIN_REVIEW_REQUIRED")
            db.execute("UPDATE proof_live_campaign SET enabled=true WHERE id=%s",(self.campaign,))

    def disable(self):
        with self.connect() as db:
            db.execute('UPDATE proof_live_campaign SET enabled=false WHERE id=%s',(self.campaign,))


def migrate_sqlite(source, destination):
    """Copy one validated SQLite campaign into an EMPTY PostgreSQL campaign atomically.

    Caller explicitly provisions destination first. Source is read-only through
    the existing ledger API; all imported campaigns remain disabled for review.
    No reservation refund or transport is performed.
    """
    from psycopg.types.json import Jsonb
    with source.connect() as sqlite:
        ceiling,enabled=sqlite.execute('SELECT ceiling,enabled FROM campaign').fetchone()
        rows=sqlite.execute('SELECT id,request_id,state,evidence FROM attempts').fetchall()
    if source.campaign != destination.campaign:
        raise ValueError('Migration campaign identity mismatch')
    with destination.connect() as db:
        campaign=db.execute('SELECT ceiling,unit_usd,budget_usd FROM proof_live_campaign WHERE id=%s FOR UPDATE',(destination.campaign,)).fetchone()
        if campaign is None or campaign[0] != ceiling or len(rows)>ceiling or campaign[1]*len(rows)>campaign[2]:
            raise ValueError('Migration quota mismatch')
        if db.execute('SELECT 1 FROM proof_live_attempt WHERE campaign=%s',(destination.campaign,)).fetchone():
            raise ValueError('Destination must be empty; never overwrite attempts')
        for identity,request_id,state,encoded in rows:
            evidence=json.loads(encoded)
            if evidence['execution']['id'] != identity:
                raise ValueError('Attempt identity mismatch')
            db.execute('INSERT INTO proof_live_attempt(id,campaign,request_id,state,reserved_usd,evidence) VALUES(%s,%s,%s,%s,%s,%s)',(identity,destination.campaign,request_id,state,campaign[1],Jsonb(evidence)))
        db.execute('UPDATE proof_live_campaign SET enabled=false WHERE id=%s',(destination.campaign,))
    return len(rows)
