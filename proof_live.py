"""Owner-only opt-in inference, persistent attempt reservations, separate evidence.

Default OFF. R1 never enables LIVE in Render: durable deployment storage has not
been certified. No CLI execute()/SIGALRM, oracle or historical result mutation.
"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
try:
    import fcntl
except ImportError:  # Offline mode must still import on Windows.
    fcntl = None
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid

import proof_hybrid
import proof_meta_experiment as experiment
import proof_theater
import proof_live_transport as transport

ROOT = Path(__file__).resolve().parent
ALLOWED_CASES = frozenset(proof_theater.CASE_IDS)


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def now():
    return datetime.now(timezone.utc).isoformat()


def private_path(path):
    if fcntl is None or not hasattr(os, 'getuid'):
        raise ValueError('R1 LIVE requires POSIX durable file locking; offline remains available')
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to(ROOT):
        raise ValueError('Ledger must be absolute, outside source, and not a symlink')
    if path.parent.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError('Ledger parents must not contain symlinks')
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise ValueError('Ledger directory must be owner-only (0700)')
    return path


def initialize(path, campaign, max_attempts):
    """Explicit provisioning only; server never recreates or resets missing quota."""
    path = private_path(path)
    if not campaign or len(campaign) > 100 or type(max_attempts) is not int or not 1 <= max_attempts <= 10:
        raise ValueError('Invalid campaign or request ceiling')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE campaign (id TEXT PRIMARY KEY, ceiling INTEGER NOT NULL, enabled INTEGER NOT NULL)')
        db.execute('INSERT INTO campaign VALUES (?,?,1)', (campaign, max_attempts))
        db.execute('CREATE TABLE attempts (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, state TEXT NOT NULL, evidence TEXT NOT NULL)')
    folder = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


class Ledger:
    def __init__(self, path, campaign):
        self.path, self.campaign = private_path(path), campaign
        self._verify()
        self.status()

    def _verify(self):
        info = self.path.stat()  # Missing file -> fail closed, never create.
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('Ledger must be an existing owner-only regular file')

    def connect(self):
        self._verify()
        db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True, timeout=2)
        db.execute('PRAGMA synchronous=FULL')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            db.close()
            raise ValueError('Ledger integrity failed')
        row = db.execute('SELECT id FROM campaign').fetchall()
        if row != [(self.campaign,)]:
            db.close()
            raise ValueError('Pinned campaign mismatch')
        return db

    def status(self):
        with self.connect() as db:
            ceiling, enabled = db.execute('SELECT ceiling,enabled FROM campaign').fetchone()
            count = db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            uncertain = db.execute("SELECT COUNT(*) FROM attempts WHERE state IN ('RESERVED','SENDING','UNCERTAIN')").fetchone()[0]
            return {'ceiling': ceiling, 'reserved': count, 'remaining': max(0, ceiling-count),
                    'enabled': bool(enabled), 'uncertain_attempts': uncertain,
                    'monetary_cost_cap_guaranteed': False}

    def acquire(self):
        self._verify()
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise Rejected(409, 'INFERENCE_IN_PROGRESS') from None
        return fd

    def reserve(self, request_id, evidence):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            ceiling, enabled = db.execute('SELECT ceiling,enabled FROM campaign').fetchone()
            if not enabled:
                raise Rejected(403, 'LIVE_DISABLED')
            if db.execute('SELECT 1 FROM attempts WHERE request_id=?', (request_id,)).fetchone():
                raise Rejected(409, 'REQUEST_ALREADY_RESERVED')
            if db.execute("SELECT 1 FROM attempts WHERE state IN ('RESERVED','SENDING','UNCERTAIN')").fetchone():
                raise Rejected(409, 'CAMPAIGN_UNCERTAIN_REVIEW_REQUIRED')
            if db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] >= ceiling:
                raise Rejected(429, 'QUOTA_EXHAUSTED')
            db.execute('INSERT INTO attempts VALUES (?,?,?,?)',
                       (evidence['execution']['id'], request_id, 'RESERVED', json.dumps(evidence, ensure_ascii=False)))

    def write(self, evidence, state):
        with self.connect() as db:
            db.execute('UPDATE attempts SET state=?,evidence=? WHERE id=?',
                       (state, json.dumps(evidence, ensure_ascii=False), evidence['execution']['id']))

    def disable(self):
        with self.connect() as db:
            db.execute('UPDATE campaign SET enabled=0')


class SimulatedProvider:
    simulated = True

    def __call__(self, body, _key):
        request = experiment.strict_json(body.decode())
        case_id = experiment.strict_json(request['messages'][1]['content'])['case']['case_id']
        record = next(r for r in proof_theater.catalog() if r['id'] == case_id)
        envelope = {'model': experiment.MODEL, 'choices': [{'finish_reason': 'stop',
                    'message': {'content': json.dumps(record['extraction'], ensure_ascii=False)}}]}
        return 200, json.dumps(envelope, ensure_ascii=False).encode()


class MetaProvider:
    simulated = False

    def __call__(self, body, key):
        return transport.send_once(body, key)


class Service:
    def __init__(self, ledger, owner_secret, api_key='', provider=None):
        self.ledger, self.owner_secret, self.api_key = ledger, owner_secret, api_key
        self.provider = provider or MetaProvider()
        if not 32 <= len(owner_secret) <= 256 or any(ord(x) < 33 or ord(x) > 126 for x in owner_secret):
            raise ValueError('Independent Owner credential must be >=32 printable ASCII characters')
        if not self.provider.simulated and (len(api_key) < 16 or api_key == owner_secret or
                any(ord(x) < 32 or ord(x) == 127 for x in api_key)):
            raise ValueError('Independent valid server API key required')
        self.authorization = 'Basic ' + base64.b64encode(('owner:'+owner_secret).encode()).decode()
        self.failures = []  # Supplementary brute-force throttle only, NOT budget accounting.
        import threading
        self.auth_lock = threading.Lock()
        self.enabled = True

    def authorize(self, headers):
        with self.auth_lock:
            self.failures = [t for t in self.failures if time.monotonic()-t < 60]
            if len(self.failures) >= 8:
                raise Rejected(429, 'AUTH_RATE_LIMIT')
            values = headers.get_all('Authorization', [])
            if (len(values) != 1 or not values[0].isascii() or len(values[0]) > 2048
                    or not hmac.compare_digest(values[0], self.authorization)):
                self.failures.append(time.monotonic())
                raise Rejected(401, 'OWNER_AUTH_REQUIRED')

    def redact(self, text):
        for secret in [self.owner_secret, self.api_key,
                       base64.b64encode(self.owner_secret.encode()).decode(),
                       base64.b64encode(self.api_key.encode()).decode() if self.api_key else '', self.authorization,
                       self.authorization.removeprefix('Basic ')]:
            if secret:
                text = text.replace(secret, '[REDACTED]').replace(json.dumps(secret)[1:-1], '[REDACTED]')
        return text

    def safe_response(self, text):
        # Never persist malformed raw data. Inspect JSON strings, including nested
        # extraction JSON, before storing a safe response or producing a Passport.
        try:
            parsed = experiment.strict_json(text)
            changed = [False]
            def walk(value, depth=0):
                if isinstance(value, dict):
                    return {walk(k, depth+1): walk(v, depth+1) for k, v in value.items()}
                if isinstance(value, list):
                    return [walk(v, depth+1) for v in value]
                if isinstance(value, str):
                    clean = self.redact(value)
                    changed[0] |= clean != value
                    if depth < 12 and clean.lstrip().startswith(('{', '[')):
                        try:
                            nested = experiment.strict_json(clean)
                        except (ValueError, TypeError, RecursionError):
                            return clean
                        safe_nested = walk(nested, depth+1)
                        if changed[0]:
                            return json.dumps(safe_nested, ensure_ascii=False)
                    return clean
                return value
            safe = walk(parsed)
            literal = self.redact(text)
            changed[0] |= literal != text
            return (self.redact(json.dumps(safe, ensure_ascii=False)) if changed[0] else text), changed[0], parsed
        except (ValueError, TypeError, RecursionError):
            return None, False, None

    def status(self):
        return {'provider': 'SIMULATED_NO_META_CALL' if self.provider.simulated else 'META',
                'new_meta_inference': False, 'model': experiment.MODEL,
                'cases': [{'case_id': r['id'], 'input': r['input']} for r in proof_theater.catalog() if not getattr(self, 'cloud_case_lock', None) or r['id'] == self.cloud_case_lock],
                'budget': self.ledger.status(), 'enabled': self.enabled,
                'automatic_retries': 0, 'timeout_does_not_cancel_meta': True}

    def infer(self, case_id, request_id):
        if not self.enabled:
            raise Rejected(403, 'LIVE_DISABLED')
        if getattr(self, 'cloud_case_lock', None) and case_id != self.cloud_case_lock:
            raise Rejected(400, 'CASE_NOT_ALLOWED')
        if type(case_id) is not str or case_id not in ALLOWED_CASES:
            raise Rejected(400, 'CASE_NOT_ALLOWED')
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise Rejected(400, 'INVALID_REQUEST_ID') from None
        case = next(r['input'] for r in proof_theater.catalog() if r['id'] == case_id)
        request = proof_hybrid.build_extraction_request(case)
        body = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode()
        if len(body) > transport.MAX_REQUEST_BYTES:
            raise Rejected(400, 'REQUEST_TOO_LARGE')
        simulated = bool(self.provider.simulated)
        evidence = {'format': 'PROOF_LIVE_ATTEMPT_01', 'status': 'RESERVED',
                    'origin': 'SIMULATED_PROVIDER_NO_META_INFERENCE' if simulated else 'NEW_META_INFERENCE',
                    'new_meta_inference': False, 'provider_simulated': simulated,
                    'case_id': case_id, 'sources': case['documents'],
                    'request': {'model': experiment.MODEL, 'endpoint': transport.ENDPOINT,
                                'payload': request, 'sha256': hashlib.sha256(body).hexdigest(),
                                'max_completion_tokens': experiment.MAX_OUTPUT_TOKENS},
                    'execution': {'id': uuid.uuid4().hex, 'at': now(), 'elapsed_ms': None},
                    'transport_started': False, 'http_status': None, 'model_reported': None,
                    'usage': None, 'usage_status': 'UNKNOWN_POSSIBLY_BILLABLE', 'cost': None,
                    'cost_status': 'NOT_CALCULATED_PRICES_UNVERIFIED',
                    'baseline_status': 'NOT_RUN', 'extraction': None,
                    'evaluation': None, 'passport': None, 'automatic_retries': 0}
        fd = self.ledger.acquire()
        started = time.monotonic()
        try:
            self.ledger.reserve(request_id, evidence)  # FULL commit before transport, never refunded.
            state = 'DONE'
            try:
                if not self.enabled or not self.ledger.status()['enabled']:
                    evidence.update(status='DISABLED_AFTER_RESERVATION')
                else:
                    evidence.update(transport_started=True, new_meta_inference=not simulated, status='SENDING')
                    self.ledger.write(evidence, 'SENDING')
                    status, raw = self.provider(body, self.api_key)
                    if type(status) is not int or type(raw) is not bytes:
                        raise ValueError('Invalid transport result')
                    if len(raw) > transport.MAX_RESPONSE_BYTES:
                        raise transport.TransportFailure('RESPONSE_TOO_LARGE')
                    evidence.update(http_status=status, response_sha256=hashlib.sha256(raw).hexdigest())
                    text = raw.decode('utf-8')
                    safe, redacted, envelope = self.safe_response(text)
                    evidence.update(response_text=safe, response_redacted=redacted)
                    if isinstance(envelope, dict) and not redacted:
                        reported = envelope.get('usage')
                        if isinstance(reported, dict):
                            usage = {k: v for k, v in reported.items() if k in
                                     ['prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens']
                                     and type(v) is int and v >= 0}
                            detail = reported.get('completion_tokens_details')
                            if isinstance(detail, dict) and type(detail.get('reasoning_tokens')) is int and detail['reasoning_tokens'] >= 0:
                                usage['reasoning_tokens'] = detail['reasoning_tokens']
                            evidence['usage'] = usage or None
                            evidence['usage_status'] = 'REPORTED' if usage else 'UNKNOWN_POSSIBLY_BILLABLE'
                        if isinstance(envelope.get('model'), str):
                            evidence['model_reported'] = self.redact(envelope['model'])[:160]
                    if redacted:
                        evidence['status'] = 'UNSAFE_RESPONSE_REDACTED'
                    elif not 200 <= status < 300:
                        evidence['status'] = 'HTTP_ERROR'
                    elif not isinstance(envelope, dict) or 'choices' not in envelope:
                        evidence['status'] = 'INVALID_JSON_OR_ENVELOPE'
                    else:
                        try:
                            extraction = experiment.parse_response(text, extraction_only=True)
                        except (ValueError, KeyError, TypeError):
                            evidence['status'] = 'INVALID_OR_INCOMPLETE_EXTRACTION'
                        else:
                            result = proof_hybrid.run(case, extraction)
                            computed = result['engine_status'] == 'COMPUTED_BY_BASELINE'
                            rows, checks, reason = proof_theater._audit(case, extraction, computed, result.get('excluded_sources', []))
                            decision = {'baseline_status': result['engine_status'],
                                        'operational_result': result['operational_result'] if computed else None,
                                        'excluded_sources': result.get('excluded_sources', []), 'reason': reason}
                            evidence.update(status='EVALUATED' if computed else 'EXTRACTION_REJECTED',
                                            extraction=extraction, baseline_status=result['engine_status'],
                                            evaluation={'decision': decision, 'lineage': rows, 'checks': checks})
                            identity = {'input_sha256': proof_theater.digest(case),
                                        'extraction_sha256': proof_theater.digest(extraction),
                                        'decision_sha256': proof_theater.digest(decision),
                                        'origin': evidence['origin'],
                                        'validator_sha256': hashlib.sha256(b''.join((ROOT / name).read_bytes() for name in
                                            ('proof_baseline.py','proof_hybrid.py','proof_meta_experiment.py','proof_theater.py'))).hexdigest(),
                                        'live_adapter_sha256': hashlib.sha256(b''.join((ROOT / name).read_bytes() for name in
                                            ('proof_live.py','proof_live_transport.py','proof_live_web.py','proof_web.py'))).hexdigest()}
                            evidence['passport'] = {'format': 'PROOF_LIVE_DECISION_PASSPORT_01',
                                'decision_id': 'proof-live-' + proof_theater.digest(identity)[:20],
                                'reproducibility': identity,
                                'scope': evidence['origin'], 'new_meta_inference': not simulated,
                                'execution': deepcopy(evidence['execution']), 'case_id': case_id,
                                'sources': deepcopy(case['documents']), 'extraction': deepcopy(extraction),
                                'decision': decision, 'checks': checks,
                                'lineage': [r for r in rows if r['validation'] != 'UNREACHED'],
                                'lineage_scope': 'ONLY_REACHED_CHECKS',
                                'model': experiment.MODEL, 'request_sha256': evidence['request']['sha256'],
                                'response_sha256': evidence['response_sha256'],
                                'external_actions_executed': False,
                                'limitation': 'Integrity is not authenticity or physical verification.'}
            except TimeoutError:
                evidence['status'] = 'TIMEOUT_POSSIBLY_BILLABLE'
                state = 'UNCERTAIN'
            except transport.TransportFailure as error:
                evidence['status'] = error.code
                state = 'UNCERTAIN'
            except Exception:
                evidence['status'] = 'EXECUTION_UNCERTAIN'
                state = 'UNCERTAIN'
            evidence['execution']['elapsed_ms'] = round((time.monotonic()-started)*1000, 3)
            if evidence['passport'] is not None:
                evidence['passport']['execution'] = deepcopy(evidence['execution'])
            self.ledger.write(evidence, state)
            return evidence
        finally:
            if hasattr(self.ledger, "release"):
                self.ledger.release(fd)
            else:
                os.close(fd)


def configure(config, mode):
    if config.get('PROOF_LIVE_ENABLED') != '1' and config.get('PROOF_LIVE_PANEL') != '1':
        return None
    cloud = mode == 'render'
    if cloud and config.get('PROOF_LIVE_PERSISTENCE') != 'postgres':
        raise ValueError('Render LIVE disabled: PostgreSQL persistence required')
    provider_name = config.get('PROOF_LIVE_PROVIDER')
    if provider_name not in ['simulated', 'meta']:
        raise ValueError('Explicit simulated/meta provider required')
    if provider_name == 'meta' and config.get('PROOF_LIVE_CALL_AUTHORIZED') != '1':
        raise ValueError('Separate Owner real-call authorization required')
    if provider_name == 'meta' and not cloud:
        raise ValueError('Real Meta inference is Render-only')
    if cloud:
        from proof_live_postgres import Ledger as PostgresLedger
        ledger = PostgresLedger(config.get('DATABASE_URL', ''), config.get('PROOF_LIVE_CAMPAIGN', ''))
    else:
        ledger = Ledger(config.get('PROOF_LIVE_LEDGER', ''), config.get('PROOF_LIVE_CAMPAIGN', ''))
    if config.get('PROOF_LIVE_ENABLED') != '1' and config.get('META_MODEL_API_KEY'):
        raise ValueError('Meta key is forbidden while LIVE is disabled')
    service = Service(ledger, config.get('PROOF_LIVE_OWNER_SECRET', ''),
                   config.get('META_MODEL_API_KEY', '') if provider_name == 'meta' else '',
                   SimulatedProvider() if provider_name == 'simulated' else MetaProvider())
    service.enabled = config.get('PROOF_LIVE_ENABLED') == '1'
    service.owner_activation_allowed = provider_name == 'simulated' or config.get('PROOF_LIVE_CALL_AUTHORIZED') == '1'
    if cloud:
        service.cloud_case_lock = 'PM01-02'
    return service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['init', 'disable']:
        cmd = sub.add_parser(name)
        cmd.add_argument('--ledger', type=Path, required=True)
        cmd.add_argument('--campaign', required=True)
        if name == 'init':
            cmd.add_argument('--max-attempts', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'init':
        initialize(args.ledger, args.campaign, args.max_attempts)
    else:
        Ledger(args.ledger, args.campaign).disable()
    print('Local campaign state updated; no Meta request sent.')


if __name__ == '__main__':
    main()
