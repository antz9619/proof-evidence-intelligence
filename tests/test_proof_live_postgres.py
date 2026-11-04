"""Integration checks; set PROOF_TEST_POSTGRES_URL to a disposable TLS database."""
import os,uuid,threading,unittest,secrets
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import proof_live as live
import proof_live_postgres as pg

@unittest.skipUnless(os.environ.get('PROOF_TEST_POSTGRES_URL'),'disposable PostgreSQL not configured')
class PostgresTests(unittest.TestCase):
 def setUp(self):
  self.url=os.environ['PROOF_TEST_POSTGRES_URL'];self.campaign=uuid.uuid4().hex
  import psycopg
  with psycopg.connect(self.url) as db:
   db.execute(pg.SCHEMA)
   # Test fixture cleanup only in explicitly disposable DB.
   db.execute('DELETE FROM proof_live_attempt');db.execute('DELETE FROM proof_live_campaign')
   db.execute('INSERT INTO proof_live_campaign VALUES (%s,1,true,0.05,0.05)',(self.campaign,))
  self.ledger=pg.Ledger(self.url,self.campaign)
 def evidence(self):return {'execution':{'id':uuid.uuid4().hex},'request':{'model':'muse-spark-1.3'}}
 def test_tls(self):
  with self.ledger.connect() as db:self.assertTrue(db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()[0])
 def test_concurrent_reservations(self):
  barrier=threading.Barrier(2)
  def reserve(_):
   barrier.wait()
   try:self.ledger.reserve(str(uuid.uuid4()),self.evidence());return 'reserved'
   except live.Rejected:return 'rejected'
  with ThreadPoolExecutor(2) as pool:self.assertEqual(sorted(pool.map(reserve,range(2))),['rejected','reserved'])
  self.assertEqual(self.ledger.status()['reserved'],1)
 def test_restart_uncertain(self):
  e=self.evidence();self.ledger.reserve(str(uuid.uuid4()),e);self.ledger.write(e,'SENDING')
  reopened=pg.Ledger(self.url,self.campaign)
  self.assertEqual(reopened.status()['uncertain_attempts'],1)
  with self.assertRaises(live.Rejected):reopened.reserve(str(uuid.uuid4()),self.evidence())
 def test_idempotent_no_refund(self):
  e=self.evidence();rid=str(uuid.uuid4());self.ledger.reserve(rid,e);self.ledger.write(e,'DONE')
  with self.assertRaises(live.Rejected):self.ledger.reserve(rid,self.evidence())
  with self.assertRaises(live.Rejected):self.ledger.reserve(str(uuid.uuid4()),self.evidence())
  self.assertEqual(self.ledger.status()['reserved_usd'],'0.050000')
 def test_persistent_disable(self):
  self.ledger.disable()
  with self.assertRaises(live.Rejected):pg.Ledger(self.url,self.campaign).reserve(str(uuid.uuid4()),self.evidence())
 def test_simulated_evaluation_passport(self):
  service=live.Service(self.ledger,secrets.token_urlsafe(40),provider=live.SimulatedProvider())
  r=service.infer('PM01-02',str(uuid.uuid4()))
  self.assertEqual(r['status'],'EVALUATED');self.assertIsNotNone(r['passport']);self.assertFalse(r['new_meta_inference'])
 def test_timeout_no_fiction(self):
  class Timeout:
   simulated=True
   def __call__(self,*args):raise TimeoutError()
  r=live.Service(self.ledger,secrets.token_urlsafe(40),provider=Timeout()).infer('PM01-02',str(uuid.uuid4()))
  self.assertIsNone(r['passport']);self.assertIsNone(r['extraction']);self.assertEqual(r['baseline_status'],'NOT_RUN')
  self.assertEqual(self.ledger.status()['uncertain_attempts'],1)
 def test_no_transaction_during_provider(self):
  outer=self
  class Provider:
   simulated=True
   def __call__(self,body,key):
    with outer.ledger.connect() as db:
     db.execute("SET LOCAL lock_timeout='100ms'")
     db.execute('SELECT id FROM proof_live_campaign WHERE id=%s FOR UPDATE',(outer.campaign,))
    return live.SimulatedProvider()(body,key)
  r=live.Service(self.ledger,secrets.token_urlsafe(40),provider=Provider()).infer('PM01-02',str(uuid.uuid4()))
  self.assertEqual(r['status'],'EVALUATED')
 def test_cloud_lock_and_local_real_disabled(self):
  config={'PROOF_LIVE_ENABLED':'1','PROOF_LIVE_PERSISTENCE':'postgres','DATABASE_URL':self.url,'PROOF_LIVE_CAMPAIGN':self.campaign,'PROOF_LIVE_OWNER_SECRET':secrets.token_urlsafe(40),'PROOF_LIVE_PROVIDER':'simulated'}
  service=live.configure(config,'render')
  with self.assertRaises(live.Rejected):service.infer('PM01-03',str(uuid.uuid4()))
  self.assertEqual(self.ledger.status()['reserved'],0)
 def test_invalid_tls_rejected(self):
  with self.assertRaises(ValueError):pg.Ledger('postgresql://localhost/no?sslmode=disable',self.campaign)
 def test_migrate_sqlite_preserves_uncertainty(self):
  import tempfile,pathlib
  with tempfile.TemporaryDirectory() as folder:
   path=pathlib.Path(folder)/'ledger.sqlite'
   live.initialize(path,self.campaign,1);source=live.Ledger(path,self.campaign)
   e=self.evidence();source.reserve(str(uuid.uuid4()),e);source.write(e,'UNCERTAIN')
   self.assertEqual(pg.migrate_sqlite(source,self.ledger),1)
   state=self.ledger.status();self.assertFalse(state['enabled']);self.assertEqual(state['uncertain_attempts'],1)
   with self.assertRaises(ValueError):pg.migrate_sqlite(source,self.ledger)
 def test_database_unavailable_no_fallback(self):
  import psycopg
  with patch('psycopg.connect',side_effect=psycopg.OperationalError('private diagnostic')):
   with self.assertRaises(live.Rejected) as caught:self.ledger.status()
   self.assertEqual(caught.exception.code,'LIVE_PERSISTENCE_UNAVAILABLE')
 def test_owner_enable_does_not_send(self):
  self.ledger.disable();self.ledger.enable()
  self.assertTrue(self.ledger.status()['enabled']);self.assertEqual(self.ledger.status()['reserved'],0)
 def test_offline_survives_neon_down_with_owner_panel(self):
  import socket,urllib.request,urllib.error,proof_web,base64,psycopg
  with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
  owner=secrets.token_urlsafe(40)
  config={'PORT':str(port),'PROOF_ALLOWED_HOSTS':'proof-staging.example','PROOF_LIVE_PANEL':'1','PROOF_LIVE_ENABLED':'0','PROOF_LIVE_PERSISTENCE':'postgres','DATABASE_URL':self.url,'PROOF_LIVE_CAMPAIGN':self.campaign,'PROOF_LIVE_OWNER_SECRET':owner,'PROOF_LIVE_PROVIDER':'simulated'}
  with patch('psycopg.connect',side_effect=psycopg.OperationalError('private diagnostic')):
   server=proof_web.configured_server(mode='render',environ=config)
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    def fetch(path,auth=False):
     headers={'Host':'proof-staging.example'}
     if auth:headers['Authorization']='Basic '+base64.b64encode(('owner:'+owner).encode()).decode()
     return urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+str(port)+path,headers=headers),timeout=3)
    self.assertEqual(fetch('/?lang=en').status,200)
    with self.assertRaises(urllib.error.HTTPError) as denied:fetch('/live')
    self.assertEqual(denied.exception.code,401)
    self.assertEqual(fetch('/live',True).status,200)
    with self.assertRaises(urllib.error.HTTPError) as unavailable:fetch('/api/live/status',True)
    self.assertEqual(unavailable.exception.code,503)
    self.assertEqual(fetch('/healthz').status,200)
   finally:server.shutdown();server.server_close();thread.join()
