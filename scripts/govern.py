#!/usr/bin/env python3
"""LS GOVERN: small policy-governed controller of micro-work and Proxmox sandboxes.
Standard library only. No downloaded scripts are executed by this engine.
"""
import argparse, datetime as dt, fcntl, hashlib, html, json, os, re, shutil, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT=Path(os.getenv('LS_GOV_ROOT','/opt/ls-govern'))
WEB=Path(os.getenv('LS_GOV_WEB','/opt/ls-conquer/www/govern'))
DB=ROOT/'govern.sqlite'
STAMP=lambda:dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
SLUG=re.compile(r'^[a-z][a-z0-9-]{0,39}$')
ACTIONS={'inspect','ports','storage','services','apt-plan','ideas','build','test','publish','checkpoint'}
READ={'inspect','ports','storage','services','apt-plan','ideas'}
REALMS={
 'citadel':{'mode':'civil','allowed':sorted(READ|{'checkpoint'}),'max_jobs':1},
 'workshop':{'mode':'civil','allowed':sorted(ACTIONS),'max_jobs':2},
 'beach':{'mode':'sandbox','allowed':sorted(ACTIONS),'max_jobs':2},
 'anarchy':{'mode':'anarchy','allowed':sorted(ACTIONS),'max_jobs':3},
}
# Non-negotiable rules even in "anarchy": no untrusted execution as root, no unapproved
# production deployment, no shell interpolation, no altering existing PVE resources.
HARD_LIMITS={'max_workers':3,'min_free_ram_mb':512,'min_free_disk_percent':10,
             'max_load_per_core':1.6,'max_jobs_per_tick':4,'max_projects':60}

class Conn(sqlite3.Connection):
 def __exit__(self,*exc):
  try:return super().__exit__(*exc)
  finally:self.close()

def connect():
 ROOT.mkdir(parents=True,exist_ok=True)
 cx=sqlite3.connect(DB,timeout=12,factory=Conn);cx.row_factory=sqlite3.Row
 cx.execute('PRAGMA busy_timeout=7000');return cx

def init():
 for p in (ROOT,ROOT/'src',ROOT/'backups',ROOT/'receipts',WEB,WEB/'apps'):p.mkdir(parents=True,exist_ok=True)
 with connect() as cx:
  cx.execute('PRAGMA journal_mode=WAL')
  cx.executescript('''
   CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
   CREATE TABLE IF NOT EXISTS realms(name TEXT PRIMARY KEY,mode TEXT,allowed TEXT,max_jobs INT,active INT DEFAULT 1);
   CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY,realm TEXT,created TEXT,sha TEXT,tested_sha TEXT,published_sha TEXT);
   CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,realm TEXT,action TEXT,target TEXT,status TEXT DEFAULT 'QUEUED',created TEXT,started TEXT,finished TEXT,elapsed_ms INTEGER,detail TEXT);
   CREATE INDEX IF NOT EXISTS jobqueue ON jobs(status,id);
   CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,actor TEXT,action TEXT,decision TEXT,detail TEXT);
   CREATE TABLE IF NOT EXISTS ideas(id INTEGER PRIMARY KEY,at TEXT,realm TEXT,title TEXT UNIQUE,notes TEXT);
   CREATE TABLE IF NOT EXISTS sandboxes(vmid INTEGER PRIMARY KEY,realm TEXT,created TEXT,state TEXT,template TEXT);
   CREATE TABLE IF NOT EXISTS checkpoints(id INTEGER PRIMARY KEY,at TEXT,path TEXT,sha256 TEXT,bytes INTEGER);
  ''')
  for name,cfg in REALMS.items():cx.execute('INSERT OR IGNORE INTO realms(name,mode,allowed,max_jobs) VALUES(?,?,?,?)',(name,cfg['mode'],json.dumps(cfg['allowed']),cfg['max_jobs']))
  cx.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('enabled','1')")

def event(actor,action,decision,detail=''):
 with connect() as cx:cx.execute('INSERT INTO events(at,actor,action,decision,detail) VALUES(?,?,?,?,?)',(STAMP(),actor,action,decision,str(detail)[:800]))

def run(args,timeout=12):
 try:
  p=subprocess.run(args,check=False,capture_output=True,text=True,timeout=timeout)
  return p.returncode,(p.stdout+'\n'+p.stderr).strip()[:5000]
 except (OSError,subprocess.TimeoutExpired) as e:return 124,str(e)[:300]

def realm(name):
 with connect() as cx:r=cx.execute('SELECT * FROM realms WHERE name=?',(name,)).fetchone()
 if not r:raise ValueError('Unknown realm: '+name)
 return r

def authorized(name,action,record=True):
 r=realm(name)
 approved=bool(r['active'] and action in ACTIONS and action in json.loads(r['allowed']))
 if record:event('POLICY',f'{name}/{action}','ALLOW' if approved else 'DENY',f'mode={r["mode"]}')
 return approved

def policy(name,op,action):
 if action not in ACTIONS:raise ValueError('Unknown built-in action')
 r=realm(name)
 allowed=set(json.loads(r['allowed']))
 if op=='permit':allowed.add(action)
 elif op=='deny':allowed.discard(action)
 else:raise ValueError('permit or deny')
 with connect() as cx:cx.execute('UPDATE realms SET allowed=? WHERE name=?',(json.dumps(sorted(allowed)),name))
 event('LEGISLATOR',f'{name}/{action}',op.upper())
 print(f'{name}: {action} {op.upper()}')

def setmode(name,mode):
 if mode not in ('civil','sandbox','anarchy'):raise ValueError('Invalid mode')
 if name=='citadel' and mode!='civil':raise ValueError('Citadel remains civil')
 with connect() as cx:cx.execute('UPDATE realms SET mode=? WHERE name=?',(mode,name))
 event('GOVERNMENT',name,'MODE',mode)
 print(f'{name}: {mode} (host execution restrictions unchanged)')

def add(action,target='system',region='workshop'):
 if not authorized(region,action):raise ValueError(f'Policy blocked {region}/{action}')
 if action in ('build','test','publish') and not SLUG.fullmatch(target):raise ValueError('Project target must be a short slug')
 with connect() as cx:
  x=cx.execute('INSERT INTO jobs(realm,action,target,status,created) VALUES(?,?,?,?,?)',(region,action,target,'QUEUED',STAMP()))
  i=x.lastrowid
 event('ROUTER','enqueue','QUEUED',f'#{i} {region}:{action}:{target}')
 return i

def facts():
 mem=0
 for line in Path('/proc/meminfo').read_text().splitlines():
  if line.startswith('MemAvailable:'):mem=int(line.split()[1])//1024;break
 d=shutil.disk_usage('/');load=os.getloadavg()[0];cores=os.cpu_count() or 1
 return {'host':os.uname().nodename,'ram_mb':mem,'disk_free_pct':round(d.free/d.total*100,1),
         'load':round(load,2),'cores':cores,'time':STAMP()}

def slots():
 f=facts();reasons=[]
 if f['ram_mb']<HARD_LIMITS['min_free_ram_mb']:reasons.append('RAM')
 if f['disk_free_pct']<HARD_LIMITS['min_free_disk_percent']:reasons.append('disk')
 if f['load']/f['cores']>HARD_LIMITS['max_load_per_core']:reasons.append('load')
 n=0 if reasons else max(1,min(HARD_LIMITS['max_workers'], f['ram_mb']//512, f['cores']))
 return n,reasons,f

def idea(region='workshop'):
 choices=['pixel arcade','command palette','tool map','micro dashboard','inventory viewer','network lab','music visualizer','timer game','CI reporter','recipe studio','log explorer','knowledge atlas']
 date=dt.datetime.now(dt.timezone.utc).date().isoformat()
 result=[]
 with connect() as cx:
  for i in range(3):
   n=int(hashlib.sha256(f'{date}:{region}:{i}'.encode()).hexdigest(),16)
   title=f'{choices[n%len(choices)]} + {choices[(n//19)%len(choices)]}'
   cx.execute('INSERT OR IGNORE INTO ideas(at,realm,title,notes) VALUES(?,?,?,?)',(STAMP(),region,title,'Deterministic local combination; no AI required'))
   result.append(title)
 return ', '.join(result)

# Generated apps are not arbitrary scripts: fixed JS/CSS template, escaped names only.
def source(name):
 return ROOT/'src'/name/'index.html'

def build(name,region):
 if not SLUG.fullmatch(name):raise ValueError('Invalid name')
 with connect() as cx:
  n=cx.execute('SELECT count(*) FROM projects').fetchone()[0]
  exists=cx.execute('SELECT name FROM projects WHERE name=?',(name,)).fetchone()
 if not exists and n>=HARD_LIMITS['max_projects']:raise ValueError('Project budget exhausted')
 p=source(name);p.parent.mkdir(parents=True,exist_ok=True)
 h=html.escape(name)
 data=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h} | LS Govern</title>
 <style>body{{font:17px system-ui;background:#0b1020;color:#e7efff;padding:4vw;max-width:900px;margin:auto}}.panel{{border:1px solid #334763;background:#17223a;padding:22px;border-radius:18px;margin:16px 0}}button{{background:#8fe3c5;color:#10231c;border:0;border-radius:11px;padding:14px 20px;font-weight:bold;cursor:pointer}}#count{{font-size:65px}}small{{color:#a9bdd6}}</style>
 <h1>{h}</h1><p>Self-hosted micro-world · generated by LS GOVERN</p><div class="panel"><small>MICRO-GAME: CLICK LAB</small><div id="count">0</div><button id="go">+1 Point</button><button id="reset">Reset</button></div><div class="panel"><h2>Capability</h2><p>Built → tested → independently verified → published, with SHA-256 evidence.</p><small>Runs entirely in your browser. No backend, account or dependencies.</small></div><script>let n=0;const c=document.getElementById('count');document.getElementById('go').onclick=()=>{{c.textContent=++n}};document.getElementById('reset').onclick=()=>{{n=0;c.textContent=n}};</script></html>'''
 p.write_text(data)
 digest=hashlib.sha256(data.encode()).hexdigest()
 with connect() as cx:
  cx.execute('INSERT INTO projects(name,realm,created,sha) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET sha=excluded.sha,tested_sha=NULL',(name,region,STAMP(),digest))
 return f'BUILT {name} bytes={p.stat().st_size} sha={digest[:12]}'

def test(name,region):
 p=source(name)
 if not p.is_file():raise ValueError('Build first')
 b=p.read_bytes()
 if not (b'<!doctype html>' in b.lower() and b'id="go"' in b and b'getElementById' in b and len(b)<120_000):raise ValueError('HTML invariants failed')
 digest=hashlib.sha256(b).hexdigest()
 with connect() as cx:
  r=cx.execute('SELECT sha,realm FROM projects WHERE name=?',(name,)).fetchone()
  if not r or r['sha']!=digest or r['realm']!=region:raise ValueError('Project realm or artifact changed since build')
  cx.execute('UPDATE projects SET tested_sha=? WHERE name=?',(digest,name))
 return f'TEST=PASS {name} sha={digest[:12]}'

def publish(name,region):
 p=source(name);b=p.read_bytes();digest=hashlib.sha256(b).hexdigest()
 with connect() as cx:r=cx.execute('SELECT tested_sha,sha,realm FROM projects WHERE name=?',(name,)).fetchone()
 # Independent verification gate: raw artifact content must match a previously tested SHA
 # and include the exact fixed app structures before promotion.
 if not r or r['realm']!=region or r['sha']!=digest or r['tested_sha']!=digest or b'<script>' not in b or b'<button' not in b:
  raise ValueError('COUNCIL DENIED: test/current digest mismatch')
 dest=WEB/'apps'/name;dest.mkdir(parents=True,exist_ok=True)
 tmp=dest/'index.html.tmp';tmp.write_bytes(b);os.replace(tmp,dest/'index.html')
 with connect() as cx:cx.execute('UPDATE projects SET published_sha=? WHERE name=?',(digest,name))
 return f'PUBLISHED {name} sha={digest[:12]}'

def checkpoint():
 dest=ROOT/'backups'/('govern-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
 with connect() as src,sqlite3.connect(dest) as backup:src.backup(backup)
 with sqlite3.connect(dest) as verify:ok=verify.execute('PRAGMA quick_check').fetchone()[0]
 if ok!='ok':dest.unlink(missing_ok=True);raise ValueError('Checkpoint corrupted')
 digest=hashlib.sha256(dest.read_bytes()).hexdigest()
 with connect() as cx:
  cx.execute('INSERT INTO checkpoints(at,path,sha256,bytes) VALUES(?,?,?,?)',(STAMP(),str(dest),digest,dest.stat().st_size))
  old=cx.execute('SELECT id,path FROM checkpoints ORDER BY id DESC LIMIT -1 OFFSET 10').fetchall()
  for row in old:
   path=Path(row['path'])
   if path.parent==ROOT/'backups' and path.name.startswith('govern-'):path.unlink(missing_ok=True)
   cx.execute('DELETE FROM checkpoints WHERE id=?',(row['id'],))
 return f'CHECKPOINT {dest.name} sha={digest[:12]}'

def action(act,target,region):
 if act=='inspect':return json.dumps(facts())
 if act in ('ports','storage','services','apt-plan'):
  commands={'ports':['ss','-lntup'],'storage':['df','-h'],'services':['systemctl','--failed','--no-pager'],
            'apt-plan':['apt-get','-s','full-upgrade']}
  rc,out=run(commands[act],35 if act=='apt-plan' else 10)
  if rc!=0:raise ValueError(f'{act} exit={rc} {out[:200]}')
  return out[:1000]
 if act=='ideas':return idea(region)
 if act=='build':return build(target,region)
 if act=='test':return test(target,region)
 if act=='publish':return publish(target,region)
 if act=='checkpoint':return checkpoint()
 raise ValueError('Unsupported action')

def job_exec(j):
 i=j['id'];a=j['action'];r=j['realm'];t=j['target']
 start=time.monotonic()
 if not authorized(r,a):status='DENIED';detail='Policy changed after enqueue'
 else:
  try:detail=action(a,t,r);status='PASS'
  except Exception as e:status='FAILED';detail=f'{type(e).__name__}: {e}'
 ms=int((time.monotonic()-start)*1000)
 with connect() as cx:cx.execute('UPDATE jobs SET status=?,finished=?,elapsed_ms=?,detail=? WHERE id=?',(status,STAMP(),ms,detail[:800],i))
 event('RUNNER',f'job #{i} {a}',status,detail[:160]);return status

def bootstrap():
 with connect() as cx:
  has=cx.execute('SELECT count(*) FROM projects').fetchone()[0]
  queued=cx.execute('SELECT count(*) FROM jobs').fetchone()[0]
  first=cx.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone()
 if not first:
  for name in ('citizen-arcade','beach-lab'):
   for a in ('build','test','publish'):add(a,name,'beach')
  add('ideas','daily','workshop')
  with connect() as cx:cx.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('seeded','1')")
 # One reproducible new world per day; the queue remains finite.
 daily='world-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
 with connect() as cx:
  exists=cx.execute('SELECT 1 FROM jobs WHERE target=? LIMIT 1',(daily,)).fetchone()
  total=cx.execute('SELECT count(*) FROM projects').fetchone()[0]
 if not exists and total<HARD_LIMITS['max_projects']:
  for action_name in ('build','test','publish'):add(action_name,daily,'workshop')

def tick():
 init()
 with connect() as cx:enabled=cx.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()[0]=='1'
 if not enabled:
  print('GOVERN=PAUSED');return
 with (ROOT/'cycle.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('Cycle already running');return
  bootstrap()
  n,reasons,f=slots()
  # Recover stale jobs as uncertain, rather than replay side effects.
  cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=15)).isoformat(timespec='seconds')
  with connect() as cx:cx.execute("UPDATE jobs SET status='UNCERTAIN',detail='Interrupted before final receipt',finished=? WHERE status='RUNNING' AND started<?",(STAMP(),cutoff))
  results=[]
  if n:
   from concurrent.futures import ThreadPoolExecutor
   with connect() as cx:
    candidates=cx.execute('SELECT * FROM jobs WHERE status="QUEUED" ORDER BY id LIMIT 80').fetchall()
    rows=[]
    for j in candidates:
     # Never run test and build (or publish and test) of the same project concurrently.
     if j['action'] in ('test','publish'):
      prerequisite='build' if j['action']=='test' else 'test'
      prev=cx.execute('SELECT status FROM jobs WHERE target=? AND action=? AND id<? ORDER BY id DESC LIMIT 1',
                     (j['target'],prerequisite,j['id'])).fetchone()
      if not prev or prev['status']!='PASS':continue
     rows.append(j)
     if len(rows)>=min(n,HARD_LIMITS['max_jobs_per_tick']):break
    for j in rows:cx.execute('UPDATE jobs SET status="RUNNING",started=? WHERE id=?',(STAMP(),j['id']))
   with ThreadPoolExecutor(max_workers=n) as ex:results=list(ex.map(job_exec,rows))
  event('GOVERNOR','cycle','PASS' if n else 'PAUSED',f'workers={n} jobs={len(results)} pressure={reasons}')
  render()
  print(f'GOVERN={"PASS" if n else "PAUSED"} workers={n} jobs={len(results)} done={results} {WEB}')

def render():
 init()
 with connect() as cx:
  realms=cx.execute('SELECT * FROM realms ORDER BY name').fetchall()
  jobs=cx.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 18').fetchall()
  projects=cx.execute('SELECT * FROM projects ORDER BY created DESC LIMIT 16').fetchall()
  events=cx.execute('SELECT * FROM events ORDER BY id DESC LIMIT 12').fetchall()
  sandbox=cx.execute('SELECT * FROM sandboxes ORDER BY vmid DESC LIMIT 12').fetchall()
 f=facts();slotsnow,reasons,_=slots()
 h=lambda x:html.escape(str(x),quote=True)
 card=''.join(f'<article><small>{h(r["name"])}</small><h2>{h(r["mode"]).upper()}</h2><p>{len(json.loads(r["allowed"]))} permitted actions · max {r["max_jobs"]} per realm</p></article>' for r in realms)
 app=''.join(f'<a href="apps/{h(p["name"])}/">{h(p["name"])}</a> ' for p in projects if p['published_sha'])
 tr=''.join(f'<tr><td>#{j["id"]}</td><td>{h(j["realm"])}</td><td>{h(j["action"])}</td><td>{h(j["target"])}</td><td>{h(j["status"])}</td><td>{h(j["elapsed_ms"] or "—")}</td></tr>' for j in jobs)
 ev=''.join(f'<tr><td>{h(e["at"][11:19])}</td><td>{h(e["actor"])}</td><td>{h(e["action"])}</td><td>{h(e["decision"])}</td></tr>' for e in events)
 sb=''.join(f'<p>#{s["vmid"]} · {h(s["state"])} · {h(s["realm"])}</p>' for s in sandbox) or 'None provisioned'
 page=f'''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="45"><title>LS Govern</title><style>body{{background:#0a101c;color:#e8f2ff;font:15px system-ui;max-width:1180px;margin:auto;padding:3vw}}h1{{font-size:clamp(38px,6vw,60px)}}small{{color:#9eb2cb}}h2{{color:#a8f2d3}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}article{{background:#131e30;border:1px solid #2c3d54;border-radius:16px;padding:20px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #2c3d54;padding:9px;text-align:left}}a{{color:#80d8ff;padding:8px}}.scroll{{overflow:auto}}code{{color:#a8f2d3}}</style>
 <small>LS ∞ / SELF-GOVERNANCE / {h(f['time'])}</small><h1>GOVERN</h1><p>Policy engines · regions · controller votes · automatic receipts · micro-sandboxes</p><div class="grid"><article><small>HOST</small><h2>{h(f['host'])}</h2></article><article><small>FREE RAM</small><h2>{f['ram_mb']} MB</h2></article><article><small>DISK FREE</small><h2>{f['disk_free_pct']}%</h2></article><article><small>WORKER SLOTS</small><h2>{slotsnow}</h2></article></div><h2>Regions and policy modes</h2><div class="grid">{card}</div><h2>Published worlds</h2><article>{app or 'Build/test/publish jobs queued'}</article><h2>Jobs</h2><div class="scroll"><table><tr><th>ID</th><th>Region</th><th>Action</th><th>Target</th><th>Status</th><th>ms</th></tr>{tr}</table></div><h2>Decisions</h2><div class="scroll"><table><tr><th>UTC</th><th>Controller</th><th>Action</th><th>Decision</th></tr>{ev}</table></div><h2>Sandbox LXCs</h2><article>{sb}</article><p><code>gov tick · gov challenge · gov policy list · gov add build mini beach · gov jail new</code></p><small>LAN-only via Conquer; no authentication. Lab modes cannot override host hard limits.</small>'''
 tmp=WEB/'index.html.tmp';tmp.write_text(page);os.replace(tmp,WEB/'index.html')

def challenge():
 cases=[('citadel','__host_shell__'),('beach','__root_exec__'),('anarchy','rm -rf /'),('workshop','arbitrary-sudo')]
 for region,act in cases:
  allowed=authorized(region,act)
  if allowed:raise ValueError(f'Hard boundary breached {region}/{act}')
  print(f'{region:9} {act:18} DENY')
 for region,act in (('citadel','build'),('beach','build'),('anarchy','publish')):
  allowed=authorized(region,act)
  expected=act in json.loads(realm(region)['allowed'])
  if allowed!=expected:raise ValueError(f'Policy mismatch {region}/{act}')
  print(f'{region:9} {act:18} {"ALLOW" if allowed else "DENY"}')
 print('POLICY_BREAKER=PASS (simulated forbidden operations were denied)')

def jail_probe():
 needed=('pct','pveam','pvesm','pvesh')
 print('PROXMOX', 'READY' if all(shutil.which(p) for p in needed) else 'UNAVAILABLE')
 if not all(shutil.which(p) for p in needed):return 'PROXMOX_UNAVAILABLE'
 for cmd in (['pvesm','status'],['pveam','list','local'],['pct','list']):
  rc,out=run(cmd,15);print('$',' '.join(cmd),f'rc={rc}',out[:1500])

def jail_new():
 if os.geteuid()!=0:raise ValueError('Proxmox LXC creation requires root')
 if not shutil.which('pct'):raise ValueError('pct unavailable: run on Proxmox host')
 with connect() as cx:
  active=cx.execute('SELECT COUNT(*) FROM sandboxes WHERE state!="RETIRED"').fetchone()[0]
 if active>=3:raise ValueError('Sandbox LXC quota reached (3)')
 if slots()[0]==0:raise ValueError('Governor paused provisioning due to host pressure')
 rc,s=run(['pvesm','status','-content','vztmpl'],15)
 templates=[line.split()[0] for line in s.splitlines()[1:] if len(line.split())>2 and line.split()[2]=='active']
 rc,s=run(['pvesm','status','-content','rootdir'],15)
 roots=[line.split()[0] for line in s.splitlines()[1:] if len(line.split())>2 and line.split()[2]=='active']
 if not templates or not roots:raise ValueError('No suitable template/rootdir Proxmox storage')
 # Find a cached Alpine archive; no unknown community scripts executed.
 tar=None
 for store in templates:
  rc,s=run(['pveam','list',store],15)
  for line in s.splitlines():
   fields=line.split()
   if fields and re.search(r'alpine-.*amd64.*\.tar\.(gz|xz|zst)$',fields[0]):tar=fields[0];break
  if tar:break
 if not tar:raise ValueError('No cached Alpine template. Download through Proxmox UI or pveam first.')
 rc,s=run(['pvesh','get','/cluster/nextid'],12)
 vmid=s.strip().splitlines()[-1] if s.strip() else ''
 if rc or not vmid.isdigit():raise ValueError('Could not acquire free VMID')
 cmd=['pct','create',vmid,tar,'--hostname',f'gov-lab-{vmid}','--cores','1',
      '--memory','256','--swap','0','--rootfs',f'{roots[0]}:2',
      '--unprivileged','1','--onboot','0','--tags','ls-govern;sandbox']
 rc,out=run(cmd,120)
 if rc:raise ValueError(f'pct create failed: {out[-600:]}')
 with connect() as cx:cx.execute('INSERT INTO sandboxes(vmid,realm,created,state,template) VALUES(?,?,?,?,?)',(int(vmid),'beach',STAMP(),'STOPPED',tar))
 event('JAILER','create','PASS',f'vmid={vmid} {tar}')
 return f'CREATED LXC {vmid} (unprivileged, no network, 256 MB RAM, 2 GB rootfs); gov jail start {vmid}'

def jail_control(verb,ident):
 if not ident.isdigit():raise ValueError('Expected numeric VMID')
 with connect() as cx:row=cx.execute('SELECT * FROM sandboxes WHERE vmid=?',(ident,)).fetchone()
 if not row:raise ValueError('LXC not created by this GOVERN installation')
 rc,cfg=run(['pct','config',ident],12)
 if rc or 'ls-govern' not in next((l for l in cfg.splitlines() if l.startswith('tags:')),''):
  raise ValueError('LXC identity/tag verification failed')
 if verb=='start':rc,out=run(['pct','start',ident],60);state='RUNNING'
 elif verb=='stop':rc,out=run(['pct','stop',ident],40);state='STOPPED'
 elif verb=='test':
  rc,out=run(['pct','exec',ident,'--','sh','-c','echo SANDBOX_OK; uname -m; cat /etc/os-release | head -3'],20)
  state=row['state']
 elif verb=='retire':
  run(['pct','stop',ident],40)
  rc,out=run(['pct','destroy',ident],70);state='RETIRED'
 else:raise ValueError('Unknown jail command')
 if rc:raise ValueError(f'pct {verb} failed: {out[-500:]}')
 with connect() as cx:cx.execute('UPDATE sandboxes SET state=? WHERE vmid=?',(state,ident))
 event('JAILER',f'{verb} {ident}','PASS',out[:200])
 return f'JAIL={verb.upper()} VMID={ident} {out[:160]}'

def status():
 init();n,reasons,f=slots()
 with connect() as cx:enabled=cx.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()[0]=='1'
 print('LS GOVERN',f['host'],'RAM',f['ram_mb'],'MB', 'DISK',f['disk_free_pct'],'%', 'WORKERS',n,'STATE','RUNNING' if enabled else 'PAUSED','PRESSURE',','.join(reasons) or 'no')
 with connect() as cx:
  for r in cx.execute('SELECT * FROM realms ORDER BY name'):print('REGION',r['name'],r['mode'],len(json.loads(r['allowed'])),'actions')
  for x in cx.execute('SELECT action,target,status FROM jobs ORDER BY id DESC LIMIT 8'):print('JOB',x['action'],x['target'],x['status'])

def region_clone(name,base):
 if not SLUG.fullmatch(name):raise ValueError('Invalid region slug')
 parent=realm(base)
 with connect() as cx:
  count=cx.execute('SELECT COUNT(*) FROM realms').fetchone()[0]
  if count>=16:raise ValueError('Region budget reached (16)')
  cx.execute('INSERT INTO realms(name,mode,allowed,max_jobs,active) VALUES(?,?,?,?,1)',
             (name,parent['mode'],parent['allowed'],parent['max_jobs']))
 event('LEGISLATOR','clone-region','PASS',f'{name} from {base}')
 print(f'REGION=CREATED {name} from={base}')

def region_toggle(name,active):
 realm(name)
 with connect() as cx:cx.execute('UPDATE realms SET active=? WHERE name=?',(int(active),name))
 event('LEGISLATOR','region','ENABLED' if active else 'DISABLED',name)
 print(f'REGION={name} '+('ENABLED' if active else 'DISABLED'))

def main():
 p=argparse.ArgumentParser(prog='gov',description='LS Govern — autonomous policy-controlled micro-infrastructure')
 sub=p.add_subparsers(dest='cmd')
 for name in ('status','tick','challenge','checkpoint','ideas','jobs','events','test','render','realms','constitution','council','pause','resume'):sub.add_parser(name)
 rcmd=sub.add_parser('region');rcmd.add_argument('operation',choices=['new','pause','resume']);rcmd.add_argument('name');rcmd.add_argument('base',nargs='?',default='workshop')
 world=sub.add_parser('world');world.add_argument('name');world.add_argument('realm',nargs='?',default='workshop')
 pl=sub.add_parser('policy');pl.add_argument('op',choices=['list','permit','deny']);pl.add_argument('realm',nargs='?',default='');pl.add_argument('action',nargs='?',default='')
 m=sub.add_parser('mode');m.add_argument('realm');m.add_argument('mode',choices=['civil','sandbox','anarchy'])
 a=sub.add_parser('add');a.add_argument('action',choices=sorted(ACTIONS));a.add_argument('target',nargs='?',default='system');a.add_argument('realm',nargs='?',default='workshop')
 j=sub.add_parser('jail');j.add_argument('verb',choices=['probe','new','start','stop','test','retire']);j.add_argument('vmid',nargs='?',default='')
 a=p.parse_args();init();cmd=a.cmd or 'status'
 if cmd=='status':status()
 elif cmd=='tick':tick()
 elif cmd in ('realms','policy') and (cmd=='realms' or a.op=='list'):
  for r in (realm(a.realm),) if cmd=='policy' and a.realm else [realm(k) for k in REALMS]:print(r['name'],r['mode'],json.loads(r['allowed']))
 elif cmd=='policy':policy(a.realm,a.op,a.action);render()
 elif cmd=='mode':setmode(a.realm,a.mode);render()
 elif cmd=='region':
  if a.operation=='new':region_clone(a.name,a.base)
  else:region_toggle(a.name,a.operation=='resume')
  render()
 elif cmd in ('pause','resume'):
  value='0' if cmd=='pause' else '1'
  with connect() as cx:cx.execute("UPDATE settings SET value=? WHERE key='enabled'",(value,))
  event('GOVERNMENT','global',cmd.upper());print('GOVERN='+cmd.upper())
 elif cmd=='add':print('QUEUED',add(a.action,a.target,a.realm))
 elif cmd=='challenge':challenge()
 elif cmd=='world':
  if not SLUG.fullmatch(a.name):raise ValueError('Invalid world name')
  for stage in ('build','test','publish'):add(stage,a.name,a.realm)
  for _ in range(8):
   tick()
   with connect() as cx:
    rec=cx.execute('SELECT published_sha FROM projects WHERE name=?',(a.name,)).fetchone()
   if rec and rec['published_sha']:break
  else:raise ValueError('World not published: inspect gov jobs')
  print(f'WORLD=READY {WEB}/apps/{a.name}/')
 elif cmd=='constitution':
  print('CONSTITUTION: built-in commands only; no arbitrary root shell; no changes to existing LXCs; no unverified publish')
  print(json.dumps(HARD_LIMITS,indent=2))
 elif cmd=='council':
  status()
  with connect() as cx:
   print('DECISIONS',[(row[0],row[1]) for row in cx.execute('SELECT decision,count(*) FROM events GROUP BY decision')])
   print('PUBLISHED',cx.execute('SELECT COUNT(*) FROM projects WHERE published_sha IS NOT NULL').fetchone()[0])
 elif cmd=='checkpoint':print(checkpoint())
 elif cmd=='ideas':print(idea())
 elif cmd=='render':render();print(WEB/'index.html')
 elif cmd=='jail':print(jail_probe() if a.verb=='probe' else jail_new() if a.verb=='new' else jail_control(a.verb,a.vmid))
 elif cmd=='test':
  assert connect().execute('PRAGMA quick_check').fetchone()[0]=='ok'
  challenge();assert len(REALMS)==4;print('GOVERN_TEST=PASS')
 elif cmd in ('events','jobs'):
  with connect() as cx:
   q='SELECT at,actor,action,decision,detail FROM events ORDER BY id DESC LIMIT 20' if cmd=='events' else 'SELECT id,realm,action,target,status,elapsed_ms,detail FROM jobs ORDER BY id DESC LIMIT 20'
   for row in cx.execute(q):print(' | '.join(str(x or '')[:150] for x in row))

if __name__=='__main__':
 try:main()
 except (ValueError,OSError,sqlite3.Error) as e:print(f'GOVERN_ERROR: {e}',file=sys.stderr);sys.exit(1)
