"""R1 tests use fake providers/connections only; zero paid Meta requests."""
import base64
from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
from email.message import Message

import proof_live as live
import proof_live_transport as transport
import proof_meta_experiment as experiment
import proof_theater
import proof_web

OWNER = 'owner-test-fixture-' * 3
API = 'api-test-fixture-' * 3


def envelope(case_id='PM01-02', mutate=None, usage=None):
    extraction = deepcopy(next(r['extraction'] for r in proof_theater.catalog() if r['id'] == case_id))
    if mutate:
        mutate(extraction)
    value = {'model': experiment.MODEL, 'choices': [{'finish_reason': 'stop',
             'message': {'content': json.dumps(extraction, ensure_ascii=False)}}]}
    if usage is not None:
        value['usage'] = usage
    return json.dumps(value, ensure_ascii=False).encode()


class Fake:
    simulated = True

    def __init__(self, body=None, status=200, error=None):
        self.body = body if body is not None else envelope()
        self.status, self.error, self.calls = status, error, 0

    def __call__(self, body, key):
        self.calls += 1
        if self.error:
            raise self.error
        return self.status, self.body


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'ledger.sqlite'
        live.initialize(self.path, 'r1-test', 3)
        self.ledger = live.Ledger(self.path, 'r1-test')
        self.fake = Fake()
        self.service = live.Service(self.ledger, OWNER, API, self.fake)

    def tearDown(self):
        self.tmp.cleanup()

    def infer(self, service=None, case='PM01-02', rid=None):
        return (service or self.service).infer(case, rid or str(uuid.uuid4()))

    def test_valid_extraction_real_validators_engine_and_passport(self):
        with patch.object(experiment, 'load_oracles', side_effect=AssertionError('oracle')):
            with patch.object(experiment, 'load_verified_extraction', side_effect=AssertionError('fixture')):
                with patch('proof_meta_first_call.execute', side_effect=AssertionError('CLI must not run')):
                    result = self.infer()
        self.assertEqual(result['status'], 'EVALUATED')
        self.assertEqual(result['baseline_status'], 'COMPUTED_BY_BASELINE')
        self.assertFalse(result['new_meta_inference'])
        self.assertEqual(result['origin'], 'SIMULATED_PROVIDER_NO_META_INFERENCE')
        self.assertEqual(result['passport']['decision']['operational_result']['quantity_difference'], 0)
        self.assertFalse(result['passport']['decision']['operational_result']['physical_delivery_verified'])
        self.assertFalse(result['passport']['decision']['operational_result']['automatic_closure_allowed'])
        self.assertEqual(self.fake.calls, 1)
        self.assertIsNone(result['cost'])
        self.assertEqual(self.ledger.status()['reserved'], 1)

    def test_unsupported_status_never_runs_engine(self):
        self.service.provider = Fake(envelope('PM01-03'))
        with patch.object(experiment, 'evaluate', side_effect=AssertionError('baseline')):
            result = self.infer(case='PM01-03')
        self.assertEqual(result['status'], 'EXTRACTION_REJECTED')
        self.assertEqual(result['baseline_status'], 'NOT_RUN')
        self.assertEqual(result['passport']['decision']['reason']['code'], 'UNSUPPORTED_STATUS')
        self.assertIsNone(result['passport']['decision']['operational_result'])
        self.assertFalse(any(r['validation']=='UNREACHED' for r in result['passport']['lineage']))

    def test_omitted_source_and_invalid_citation_never_run_baseline(self):
        for mutate in [lambda x:x['documents'].pop(),
                       lambda x:x['documents'][0]['status'].update(quote='not in source')]:
            with self.subTest(mutate=mutate):
                self.service.provider = Fake(envelope(mutate=mutate))
                with patch.object(experiment, 'evaluate', side_effect=AssertionError('baseline')):
                    result = self.infer()
                self.assertEqual(result['status'], 'EXTRACTION_REJECTED')
                self.assertEqual(result['baseline_status'], 'NOT_RUN')

    def test_json_invalid_incomplete_and_non_envelope_have_no_passport(self):
        for raw in [b'{', envelope().replace(b'"stop"', b'"length"'), b'{"case_id":"PM01-02"}']:
            with self.subTest(raw=raw):
                self.service.provider = Fake(raw)
                result = self.infer()
                self.assertIsNone(result['extraction'])
                self.assertIsNone(result['evaluation'])
                self.assertIsNone(result['passport'])
                self.assertEqual(result['baseline_status'], 'NOT_RUN')

    def test_http_errors_all_consume_reservations_no_retry_or_fake_decision(self):
        for status in [400, 429, 503]:
            fake = Fake(b'{"error":"provider unavailable"}', status)
            self.service.provider = fake
            with patch.object(proof_theater, 'evaluate', side_effect=AssertionError('no replay')):
                result = self.infer()
            self.assertEqual(fake.calls, 1)
            self.assertEqual(result['status'], 'HTTP_ERROR')
            self.assertEqual(result['http_status'], status)
            self.assertIsNone(result['passport'])
            self.assertIsNone(result['cost'])
        self.assertEqual(self.ledger.status()['remaining'], 0)
        with self.assertRaisesRegex(live.Rejected, 'QUOTA_EXHAUSTED'):
            self.infer()

    def test_timeout_and_restart_pause_without_refund(self):
        self.service.provider = Fake(error=TimeoutError())
        result = self.infer()
        self.assertEqual(result['status'], 'TIMEOUT_POSSIBLY_BILLABLE')
        restarted = live.Service(live.Ledger(self.path, 'r1-test'), OWNER, API, Fake())
        with self.assertRaisesRegex(live.Rejected, 'CAMPAIGN_UNCERTAIN'):
            self.infer(restarted)
        self.assertEqual(restarted.ledger.status()['reserved'], 1)
        self.assertIsNone(result['passport'])

    def test_large_response_is_counted_and_uncertain(self):
        self.service.provider = Fake(b'x' * (transport.MAX_RESPONSE_BYTES+1))
        result = self.infer()
        self.assertEqual(result['status'], 'RESPONSE_TOO_LARGE')
        self.assertEqual(self.ledger.status()['reserved'], 1)
        self.assertIsNone(result['passport'])

    def test_usage_is_reported_not_assumed_and_cost_unknown(self):
        self.service.provider = Fake(envelope(usage={'prompt_tokens':12,'completion_tokens':17,
             'total_tokens':29,'extra':'do not expose','output_tokens':True,
             'completion_tokens_details':{'reasoning_tokens':5}}))
        result = self.infer()
        self.assertEqual(result['usage'], {'prompt_tokens':12,'completion_tokens':17,'total_tokens':29,'reasoning_tokens':5})
        self.assertEqual(result['usage_status'], 'REPORTED')
        self.assertIsNone(result['cost'])

    def test_request_id_is_persistent_idempotency_and_quota_survives_restart(self):
        rid = str(uuid.uuid4())
        self.infer(rid=rid)
        restarted = live.Service(live.Ledger(self.path,'r1-test'), OWNER, API, Fake())
        with self.assertRaisesRegex(live.Rejected, 'REQUEST_ALREADY_RESERVED'):
            self.infer(restarted,rid=rid)
        self.infer(restarted)
        self.infer(restarted)
        with self.assertRaisesRegex(live.Rejected, 'QUOTA_EXHAUSTED'):
            self.infer(restarted)
        self.assertEqual(restarted.ledger.status()['reserved'],3)

    def test_reserve_is_durable_before_transport(self):
        def fake(body,key):
            independent = live.Ledger(self.path,'r1-test')
            self.assertEqual(independent.status()['reserved'],1)
            with sqlite3.connect(self.path) as db:
                self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0],'SENDING')
            return 200,envelope()
        fake.simulated = True
        self.service.provider = fake
        self.infer()

    def test_crash_preserves_sent_reservation_and_pauses_after_restart(self):
        root = str(live.ROOT)
        code = "import sys,os,uuid;sys.path.insert(0,sys.argv[1]);import proof_live as x\nclass F:\n simulated=True\n def __call__(self,b,k):os._exit(23)\nx.Service(x.Ledger(sys.argv[2],'r1-test'),'owner-test-fixture-'*3,provider=F()).infer('PM01-02',str(uuid.uuid4()))"
        result=subprocess.run([sys.executable,'-B','-c',code,root,str(self.path)],capture_output=True)
        self.assertEqual(result.returncode,23)
        restarted=live.Service(live.Ledger(self.path,'r1-test'),OWNER,provider=Fake())
        self.assertEqual(restarted.ledger.status()['reserved'],1)
        with self.assertRaisesRegex(live.Rejected,'CAMPAIGN_UNCERTAIN'):
            self.infer(restarted)

    def test_one_inference_concurrently_across_threads_and_process_lock(self):
        entered,release=threading.Event(),threading.Event()
        def fake(body,key):
            entered.set();release.wait(5);return 200,envelope()
        fake.simulated=True;self.service.provider=fake;out=[]
        thread=threading.Thread(target=lambda:out.append(self.infer()));thread.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaisesRegex(live.Rejected,'INFERENCE_IN_PROGRESS'):
                self.infer()
            code="import sys;sys.path.insert(0,sys.argv[1]);import proof_live as x\ntry:x.Ledger(sys.argv[2],'r1-test').acquire()\nexcept x.Rejected:sys.exit(9)\nsys.exit(2)"
            result=subprocess.run([sys.executable,'-B','-c',code,str(live.ROOT),str(self.path)],capture_output=True)
            self.assertEqual(result.returncode,9)
        finally:
            release.set();thread.join(5)
        self.assertEqual(len(out),1)
        self.assertEqual(self.ledger.status()['reserved'],1)

    def test_disabled_switch_is_persistent_no_new_transport(self):
        self.ledger.disable()
        with self.assertRaisesRegex(live.Rejected,'LIVE_DISABLED'):
            self.infer()
        restarted=live.Ledger(self.path,'r1-test');self.assertFalse(restarted.status()['enabled'])
        self.assertEqual(self.fake.calls,0)

    def test_missing_corrupt_or_permissive_ledger_and_campaign_mismatch_fail_closed(self):
        with self.assertRaises(ValueError):live.Ledger(self.path,'other')
        os.chmod(self.path,0o644)
        with self.assertRaises(ValueError):live.Ledger(self.path,'r1-test')
        os.chmod(self.path,0o600)
        with self.assertRaises(FileExistsError):live.initialize(self.path,'new',10)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):live.Ledger(self.path,'r1-test')
        self.path.write_bytes(b'corrupt');os.chmod(self.path,0o600)
        with self.assertRaises(sqlite3.DatabaseError):live.Ledger(self.path,'r1-test')

    def test_invalid_case_and_request_schema_do_not_spend(self):
        for case,rid in [('other',str(uuid.uuid4())),('PM01-02','not-a-uuid'),([],str(uuid.uuid4()))]:
            with self.assertRaises(live.Rejected):self.service.infer(case,rid)
        self.assertEqual(self.fake.calls,0)
        self.assertEqual(self.ledger.status()['reserved'],0)

    def test_secrets_echoed_are_redacted_in_response_database_and_no_passport(self):
        self.service.provider=Fake(json.dumps({'error':OWNER+' '+API+' '+self.service.authorization}).encode(),400)
        result=self.infer();self.assertEqual(result['status'],'UNSAFE_RESPONSE_REDACTED')
        for secret in [OWNER,API,self.service.authorization]:
            self.assertNotIn(secret,json.dumps(result));self.assertNotIn(secret.encode(),self.path.read_bytes())
        self.assertIsNone(result['passport'])

    def test_escaped_nested_secrets_and_long_model_echo_never_persist(self):
        self.service.api_key='provider-key-fixture-'*20
        payload=envelope(mutate=lambda x:x['documents'][0]['status'].update(quote=self.service.api_key))
        # Nested JSON unicode escapes must be checked after parsing, not just raw replace.
        self.service.provider=Fake(payload.replace(b'provider-key-fixture-',b'\\u0070rovider-key-fixture-'))
        result=self.infer();self.assertEqual(result['status'],'UNSAFE_RESPONSE_REDACTED')
        self.assertNotIn(self.service.api_key,json.dumps(result));self.assertNotIn(self.service.api_key.encode(),self.path.read_bytes())
        self.service.provider=Fake(json.dumps({'model':self.service.api_key}).encode())
        result=self.infer();self.assertIsNone(result['model_reported'])
        self.assertIsNone(result['passport'])

    def test_default_local_configuration_ignores_live_env_until_cli_opt_in(self):
        config={'PROOF_LIVE_ENABLED':'1','PROOF_LIVE_PROVIDER':'simulated',
                'PROOF_LIVE_LEDGER':str(self.path),'PROOF_LIVE_CAMPAIGN':'r1-test','PROOF_LIVE_OWNER_SECRET':OWNER}
        server=proof_web.configured_server(port=0,environ=config)
        try:self.assertFalse(hasattr(server,'live_service'))
        finally:server.server_close()
        server=proof_web.configured_server(port=0,environ=config,live_opt_in=True)
        try:self.assertIsInstance(server.live_service.provider,live.SimulatedProvider)
        finally:server.server_close()

    def test_failed_final_persistence_leaves_sending_reservation_blocked(self):
        original=self.ledger.write
        def write(evidence,state):
            if state=='DONE':raise OSError('simulated disk full')
            return original(evidence,state)
        with patch.object(self.ledger,'write',side_effect=write):
            with self.assertRaises(OSError):self.infer()
        restarted=live.Service(live.Ledger(self.path,'r1-test'),OWNER,provider=Fake())
        with self.assertRaisesRegex(live.Rejected,'CAMPAIGN_UNCERTAIN'):self.infer(restarted)
        self.assertEqual(self.fake.calls,1)

    def test_offline_remains_available_without_posix_live_locking(self):
        with patch.object(live,'fcntl',None):
            self.assertIsNone(live.configure({},'local'))
            server=proof_web.configured_server(port=0)
            server.server_close()
            with self.assertRaisesRegex(ValueError,'POSIX'):live.Ledger(self.path,'r1-test')

    def test_secret_numeric_usage_never_leaks_as_provider_metadata(self):
        self.service.api_key='1234567890123456789012345678901234567890'
        self.service.provider=Fake(json.dumps({'usage':{'total_tokens':int(self.service.api_key)}}).encode())
        result=self.infer();self.assertEqual(result['status'],'UNSAFE_RESPONSE_REDACTED')
        self.assertIsNone(result['usage']);self.assertNotIn(self.service.api_key,json.dumps(result))
        self.assertNotIn(self.service.api_key.encode(),self.path.read_bytes())

    def test_explicit_mode_keys_and_render_fail_closed(self):
        self.assertIsNone(live.configure({},'local'))
        settings={'PROOF_LIVE_ENABLED':'1','PROOF_LIVE_PROVIDER':'meta','PROOF_LIVE_LEDGER':str(self.path),
                  'PROOF_LIVE_CAMPAIGN':'r1-test','PROOF_LIVE_OWNER_SECRET':OWNER,'META_MODEL_API_KEY':API}
        with self.assertRaisesRegex(ValueError,'authorization'):live.configure(settings,'local')
        settings['PROOF_LIVE_CALL_AUTHORIZED']='1'
        with self.assertRaisesRegex(ValueError,'Render-only'):live.configure(settings,'local')
        with self.assertRaisesRegex(ValueError,'Render LIVE disabled'):live.configure(settings,'render')
        settings['META_MODEL_API_KEY']=''
        with self.assertRaises(ValueError):live.configure(settings,'local')
        settings['PROOF_LIVE_PROVIDER']='simulated'
        self.assertIsInstance(live.configure(settings,'local').provider,live.SimulatedProvider)

    def test_authorization_per_request_duplicate_nonascii_and_rate_limit(self):
        headers=Message();headers['Authorization']=self.service.authorization;self.service.authorize(headers)
        duplicate=Message();duplicate['Authorization']=self.service.authorization;duplicate['Authorization']='other'
        api_auth=Message();api_auth['Authorization']='Basic '+base64.b64encode(('owner:'+API).encode()).decode()
        for bad in [Message(),duplicate,api_auth]:
            with self.assertRaises(live.Rejected):self.service.authorize(bad)
        nonascii=Message();nonascii['Authorization']='Basic é'
        with self.assertRaises(live.Rejected):self.service.authorize(nonascii)
        for _ in range(4):
            with self.assertRaises(live.Rejected):self.service.authorize(Message())
        with self.assertRaisesRegex(live.Rejected,'AUTH_RATE_LIMIT'):self.service.authorize(headers)
        self.assertEqual(self.fake.calls,0)


class Connection:
    def __init__(self, host, port, **kwargs):
        self.host,self.port,self.kwargs=host,port,kwargs;self.sock=self;self.timeouts=[];self.calls=[];self.chunks=[b'{"ok":true}',b''];self.status=200;self.closed=False
    def set_tunnel(self,*a):self.tunnel=a
    def connect(self):pass
    def settimeout(self,t):self.timeouts.append(t)
    def request(self,*a,**kw):self.calls.append((a,kw))
    def getresponse(self):return self
    def isclosed(self):return not self.chunks
    def read1(self,n):return self.chunks.pop(0)
    def close(self):self.closed=True


class TransportTests(unittest.TestCase):
    def connection(self,**changes):
        c=Connection('fake',443)
        for k,v in changes.items():setattr(c,k,v)
        self.c=c;return lambda *a,**kw:c
    def test_single_post_explicit_timeouts_close_and_no_redirect_follow(self):
        factory=self.connection(status=302)
        status,raw=transport.send_once(b'{}',API,factory=factory,proxy='')
        self.assertEqual(status,302);self.assertEqual(len(self.c.calls),1);self.assertTrue(self.c.closed)
        self.assertEqual(self.c.calls[0][0][0],'POST');self.assertTrue(all(t<=transport.READ_TIMEOUT for t in self.c.timeouts))
        self.assertEqual(self.c.auto_open,0)
    def test_elapsed_connection_deadline_prevents_a_late_post(self):
        factory=self.connection()
        with patch.object(transport.time,'monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(transport.TransportFailure,'TIMEOUT'):
                transport.send_once(b'{}',API,factory=factory,proxy='')
        self.assertEqual(self.c.calls,[]);self.assertTrue(self.c.closed)

    def test_timeout_zero_retries_close_and_oversize(self):
        factory=self.connection()
        def timeout(n):raise TimeoutError()
        self.c.read1=timeout
        with self.assertRaisesRegex(transport.TransportFailure,'TIMEOUT'):transport.send_once(b'{}',API,factory=factory,proxy='')
        self.assertEqual(len(self.c.calls),1);self.assertTrue(self.c.closed)
        factory=self.connection(chunks=[b'x'*(transport.MAX_RESPONSE_BYTES+1)])
        with self.assertRaisesRegex(transport.TransportFailure,'RESPONSE_TOO_LARGE'):transport.send_once(b'{}',API,factory=factory,proxy='')
    def test_real_http_client_socket_close_response_works_without_retry(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class Handler(BaseHTTPRequestHandler):
            calls=0
            def log_message(self,*a):pass
            def do_POST(self):
                Handler.calls+=1;self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Connection','close')
                self.send_header('Content-Length','11');self.end_headers();self.wfile.write(b'{"ok":true}')
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            factory=lambda *a,**kw:http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=kw['timeout'])
            status,raw=transport.send_once(b'{}',API,factory=factory,proxy='')
            self.assertEqual((status,raw),(200,b'{"ok":true}'));self.assertEqual(Handler.calls,1)
        finally:server.shutdown();server.server_close();thread.join()

    def test_fixed_endpoint_proxy_and_header_validation(self):
        import proof_meta_first_call as cli
        self.assertEqual((transport.ENDPOINT,transport.MAX_REQUEST_BYTES,transport.MAX_RESPONSE_BYTES),(cli.ENDPOINT,cli.MAX_REQUEST_BYTES,cli.MAX_RESPONSE_BYTES))
        made=[]
        def factory(*a,**kw):
            c=Connection(*a,**kw);made.append(c);return c
        transport.send_once(b'{}',API,factory=factory,proxy='http://proxy:8080')
        self.assertEqual(made[0].kwargs['timeout'],transport.CONNECT_TIMEOUT)
        self.assertEqual(made[0].tunnel,('api.meta.ai',443))
        for key,body in [('',b'{}'),('bad\nkey',b'{}'),(API,b'x'*(transport.MAX_REQUEST_BYTES+1))]:
            with self.assertRaises(transport.TransportFailure):transport.send_once(body,key,factory=factory,proxy='')
        self.assertEqual(len(made),1)


class WebTests(unittest.TestCase):
    setUp = LiveTests.setUp
    tearDown = LiveTests.tearDown
    def request(self,method,path,payload=None,auth=True,origin=True,extra=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        h={'Content-Type':'application/json','X-PROOF-LIVE':'owner-action'}
        if auth:h['Authorization']=self.service.authorization
        if origin:h['Origin']=f'http://127.0.0.1:{self.server.server_port}'
        if extra:h.update(extra)
        c.request(method,path,body=json.dumps(payload).encode() if payload is not None else None,headers=h)
        response=c.getresponse();body=response.read();headers=dict(response.getheaders());status=response.status;c.close();return status,headers,body
    def test_http_auth_csrf_schema_download_data_and_disable(self):
        self.server=proof_web.make_server(0);self.server.live_service=self.service;self.server.live_root=live.ROOT
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        try:
            status,headers,_=self.request('GET','/live',auth=False)
            self.assertEqual(status,401);self.assertIn('Basic',headers['WWW-Authenticate'])
            self.assertEqual(self.request('GET','/live')[0],200)
            self.assertEqual(self.request('GET','/api/live/status',auth=False)[0],401)
            data={'case_id':'PM01-02','request_id':str(uuid.uuid4())}
            self.assertEqual(self.request('POST','/api/live/infer',data,origin=False)[0],403)
            self.assertEqual(self.request('POST','/api/live/infer',{**data,'prompt':'arbitrary'})[0],400)
            self.assertEqual(self.request('POST','/api/live/infer?credential=x',data)[0],400)
            status,_,body=self.request('POST','/api/live/infer',data);self.assertEqual(status,200)
            result=json.loads(body);self.assertEqual(result['status'],'EVALUATED');self.assertNotIn(OWNER,body.decode());self.assertNotIn(API,body.decode())
            self.assertEqual(self.request('POST','/api/live/disable',{})[0],200)
            self.assertEqual(self.request('POST','/api/live/infer',{'case_id':'PM01-02','request_id':str(uuid.uuid4())})[0],403)
        finally:self.server.shutdown();self.server.server_close();thread.join()


if __name__=='__main__':unittest.main()
