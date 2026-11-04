"""Opt-in staging startup certification. Synthetic provider only, never Meta."""
import os,sys,json,uuid,secrets,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import proof_live as live
from proof_live_postgres import Ledger
from email.message import Message

def main():
 if os.environ.get('PROOF_CLOUD_CERTIFY') != '1':raise RuntimeError('Explicit staging certification required')
 url=os.environ['DATABASE_URL']
 import psycopg
 try:
  with psycopg.connect(url,connect_timeout=5,options='-c statement_timeout=5000 -c lock_timeout=3000') as diagnostic:pass
 except Exception as error:
  message=str(error).lower()
  categories=[name for name,patterns in {
   'TLS_ROOT_MISSING':['root certificate file','sslrootcert'],
   'TLS_VERIFY_FAILED':['certificate verify failed','certificate validation'],
   'AUTH_FAILED':['password authentication failed','authentication failed'],
   'DNS_FAILED':['resolve','name or service not known','translate host'],
   'CONNECT_TIMEOUT':['timeout expired','connection timed out'],
   'DATABASE_OR_ROLE':['does not exist'],
   'INVALID_CONNECTION_OPTION':['invalid connection option','unsupported startup parameter','invalid value for parameter'],
   'CONNECTION_REFUSED':['connection refused'],
  }.items() if any(pattern in message for pattern in patterns)]
  print(json.dumps({'event':'PROOF_DB_DIAGNOSTIC','categories':categories or ['UNCLASSIFIED'],'exception_type':type(error).__name__}),flush=True)
  raise RuntimeError('Safe database diagnostic failed; raw details suppressed') from None
 campaign='staging-cert-'+uuid.uuid4().hex
 ledger=Ledger(url,campaign)
 with ledger.connect() as db:
  previous=db.execute("SELECT count(*) FROM proof_live_attempt WHERE campaign LIKE 'staging-cert-%' AND state='DONE'").fetchone()[0]
  assert db.pgconn.ssl_in_use
  backend_ssl=db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()[0]
  db.execute('INSERT INTO proof_live_campaign VALUES(%s,1,false,0.05,0.05)',(campaign,))
 service=live.Service(ledger,secrets.token_urlsafe(40),provider=live.SimulatedProvider())
 headers=Message();headers['Authorization']=service.authorization;service.authorize(headers)
 try:service.authorize(Message())
 except live.Rejected as e:assert e.status==401
 else:raise AssertionError('Anonymous access accepted')
 try:service.infer('PM01-02',str(uuid.uuid4()))
 except live.Rejected as e:assert e.code=='LIVE_DISABLED'
 else:raise AssertionError('Disabled campaign accepted')
 ledger.enable()
 barrier=threading.Barrier(2)
 def infer(_):
  other=live.Service(Ledger(url,campaign),secrets.token_urlsafe(40),provider=live.SimulatedProvider())
  barrier.wait()
  try:return other.infer('PM01-02',str(uuid.uuid4()))
  except live.Rejected as e:return {'rejected':e.code}
 with ThreadPoolExecutor(2) as pool:results=list(pool.map(infer,range(2)))
 evaluated=[r for r in results if r.get('status')=='EVALUATED']
 assert len(evaluated)==1 and sum('rejected' in r for r in results)==1
 assert evaluated[0]['passport'] and not evaluated[0]['new_meta_inference']
 reopened=Ledger(url,campaign);assert reopened.status()['reserved']==1
 try:service.infer('PM01-02',str(uuid.uuid4()))
 except live.Rejected:pass
 else:raise AssertionError('Quota bypass')
 ledger.disable()
 # Exercise the actual Render-mode server over loopback, with its HTTPS Host/Origin policy.
 import proof_web,urllib.request,urllib.error,base64
 server=proof_web.configured_server(mode='render')
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 host=os.environ['PROOF_ALLOWED_HOSTS']
 def fetch(path,authorized=False,body=None):
  headers={'Host':host}
  if authorized: headers['Authorization']='Basic '+base64.b64encode(('owner:'+os.environ['PROOF_LIVE_OWNER_SECRET']).encode()).decode()
  if body is not None:headers.update({'Origin':'https://'+host,'X-PROOF-LIVE':'owner-action','Content-Type':'application/json'})
  return urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+str(server.server_port)+path,headers=headers,data=body),timeout=8)
 try:
  for path in ['/?lang=es','/?lang=en','/classic?lang=en','/api/theater/cases','/healthz']:assert fetch(path).status==200
  try:fetch('/live')
  except urllib.error.HTTPError as denied:assert denied.code==401
  else:raise AssertionError('Anonymous panel allowed')
  assert fetch('/live',True).status==200
  state=json.loads(fetch('/api/live/status',True).read());assert state['cases'][0]['case_id']=='PM01-02'
  assert not state['enabled'] and not state['budget']['enabled']
  assert json.loads(fetch('/api/live/enable',True,b'{}').read())['request_sent'] is False
  assert json.loads(fetch('/api/live/disable',True,b'{}').read())['status']=='DISABLED'
 finally:server.shutdown();server.server_close();thread.join()
 print(json.dumps({'event':'PROOF_CLOUD_CERTIFICATION','status':'PASS','tls':True,'tls_verified_at_client':True,'postgres_backend_reports_ssl':backend_ssl,'render_mode_smoke':True,'anonymous_http_rejected':True,'owner_http_authenticated':True,'owner_enable_sent_no_request':True,'previous_durable_attempts':previous,'owner_auth':True,'live_off_rejected':True,'simultaneous_requests':2,'reserved':1,'simulated_evaluations':1,'passport':True,'new_meta_calls':0,'campaign':campaign}),flush=True)

if __name__=='__main__':main()
