#!/usr/bin/env python3
"""LS Facilities: small, systemd-driven local ops + creative project toolkit."""
import argparse, datetime, hashlib, html, json, os, pathlib, random, re, shutil, sqlite3, subprocess, sys, time, urllib.request, xml.etree.ElementTree as ET

ROOT=pathlib.Path(os.getenv('FAC_ROOT','/opt/ls-facilities'))
WWW=pathlib.Path(os.getenv('FAC_WWW','/opt/ls-conquer/www/facilities'))
DB=ROOT/'facilities.sqlite'
IDENT=re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,39}$')
PKG=re.compile(r'^[a-z0-9][a-z0-9.+:-]*$')
THEMES=('mint','amber','violet','cyan')
ROLES={
 'glasses':'System inspector','clock':'Timestamps and lifecycle', 'storage':'Disks and storage',
 'services':'Service failures and states','ports':'Listening ports','resources':'CPU, RAM, disk load',
 'apt':'Package caretaker','kitchen':'Build a tiny project','oven':'Test generated projects',
 'stove':'Publish tested projects','sink':'Cleanup and redundancy audit',
 'bathroom':'System hygiene','water':'Feed and knowledge ingestion',
 'headphones':'Local media indexing','universe':'Idea collision engine',
 'skill':'Reusable trusted recipes','checkpoint':'SQLite snapshot','timers':'Scheduled workers',
 'microwave':'Quick system smoke test','burner':'Bounded performance benchmark','search':'Search stored knowledge','porter':'Project publishing inventory'
}
PERSONAS=['Archivist','Cartographer','Builder','Tester','Librarian','Curator','Scout','Stylist']
OBJECTS=['LXC registry','mini arcade','music shelf','RSS station','port atlas','file inbox','backup vault','release watcher','resource map','recipe library']
MECHANISMS=['SQLite ledger','static web UI','systemd timer','checksums','filesystem event','HTTP probe','template generator','CI smoke test']
RECIPES={
 'host-inspector':('glasses',[]), 'port-atlas':('ports',[]), 'service-guard':('services',[]),
 'disk-guide':('storage',[]), 'package-planner':('apt',['plan']), 'timekeeper':('clock',[]),
 'creative-scout':('universe',['5']), 'intake':('water',['refresh']),
 'recovery-audit':('bathroom',[]), 'resource-guide':('resources',[])
}
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def run(cmd, seconds=15):
 try:
  p=subprocess.run(cmd,capture_output=True,text=True,timeout=seconds,check=False)
  return p.returncode,(p.stdout or '')+(p.stderr or '')
 except (OSError,subprocess.TimeoutExpired) as e:return 127,str(e)
def init():
 ROOT.mkdir(parents=True,exist_ok=True)
 for x in ('projects','snapshots','reports','media'): (ROOT/x).mkdir(exist_ok=True)
 db=sqlite3.connect(DB,timeout=15)
 db.execute('PRAGMA busy_timeout=8000')
 db.execute('PRAGMA journal_mode=WAL')
 db.executescript('''
 CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,role TEXT,action TEXT,status TEXT,detail TEXT);
 CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY,at TEXT,load REAL,ram_mb INT,disks TEXT,lxcs INT);
 CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY,kind TEXT,created TEXT,status TEXT,sha TEXT);
 CREATE TABLE IF NOT EXISTS ideas(id INTEGER PRIMARY KEY,created TEXT,seed INT,persona TEXT,object TEXT,mechanism TEXT,proposal TEXT UNIQUE,status TEXT);
 CREATE TABLE IF NOT EXISTS feeds(url TEXT PRIMARY KEY,added TEXT,last_poll TEXT,error TEXT);
 CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY,feed TEXT,guid TEXT,title TEXT,url TEXT,seen TEXT,UNIQUE(feed,guid));
 CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY,verb TEXT,args TEXT,created TEXT);
 ''')
 return db
def record(role,action,status,detail=''):
 with init() as d:d.execute('INSERT INTO events(at,role,action,status,detail) VALUES(?,?,?,?,?)',(now(),role,action,status,str(detail)[:1500]))
def clean_name(n):
 if not IDENT.fullmatch(n):raise SystemExit('Name: letters/digits/_/- only, starting with a letter (max 40)')
 return n
def metrics():
 load=float(pathlib.Path('/proc/loadavg').read_text().split()[0])
 mem=next((int(x.split()[1])//1024 for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')),0)
 _,disk=run(['df','-h','/'])
 lxcs=0
 if shutil.which('pct'):
  status,out=run(['pct','list'])
  if status==0:lxcs=max(0,len([x for x in out.splitlines() if x.strip()])-1)
 return load,mem,disk.strip(),lxcs
def status():
 l,m,d,n=metrics()
 print(f'LS FACILITIES | {now()}\nHOST {os.uname().nodename} | LOAD {l} | AVAILABLE RAM {m} MB | LXCs {n}\n{d}\n')
 with init() as db:
  print('PROJECTS',db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],
        'IDEAS',db.execute('SELECT COUNT(*) FROM ideas').fetchone()[0],
        'ARTICLES',db.execute('SELECT COUNT(*) FROM articles').fetchone()[0])
 print('NEXT  fac glasses | fac kitchen new demo site | fac universe 5 | fac water refresh')
def glasses():
 status()
 if shutil.which('pct'):
  print('\nLXCs:');print(run(['pct','list'])[1][:1800])
 if shutil.which('pvesm'):
  print('STORAGE:');print(run(['pvesm','status'])[1][:1800])
 print('SYSTEM ERRORS:'); print(run(['systemctl','--failed','--no-pager','--plain'])[1][:1400])
def clock():
 print('UTC:',now()); print('LOCAL:',datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
 print(run(['uptime','-p'])[1].strip())
def services():print(run(['systemctl','--failed','--no-pager','--plain'])[1][:5000]); print('\nLS SERVICES:'); print(run(['systemctl','list-units','--type=service','--no-pager','--plain'])[1][:3000])
def ports():
 rc,out=run(['ss','-lntup'])
 print(out[:7000]); record('ports','inspect','PASS' if rc==0 else 'FAIL',f'exit={rc}')
def storage():
 print(run(['lsblk','-o','NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS'])[1][:4000]); print(run(['df','-h'])[1][:4000])
def resources():
 print('Load:',pathlib.Path('/proc/loadavg').read_text().strip());print(run(['free','-h'])[1]);print(run(['ps','-eo','pid,%cpu,%mem,comm','--sort=-%mem'])[1][:1500])
def bathroom():
 for label,cmd in [('PACKAGES',['dpkg','--audit']),('FAILED UNITS',['systemctl','--failed','--no-pager']),('JOURNAL',['journalctl','-p','0..3','-n','15','--no-pager'])]:
  print('\n',label);print(run(cmd)[1][:3000])
def apt(action,pkgs,apply=False):
 if not shutil.which('apt-get'):raise SystemExit('APT not installed')
 if action=='update':
  if not apply: print('Use: fac apt update --apply to refresh package metadata');return
  cmd=['apt-get','update']
 elif action=='plan':cmd=['apt-get','-s','full-upgrade']
 elif action=='upgrade':cmd=['apt-get','upgrade','-y'] if apply else ['apt-get','-s','upgrade']
 elif action=='install':
  if not pkgs or any(not PKG.fullmatch(x) for x in pkgs):raise SystemExit('Supply valid Debian package names')
  cmd=['apt-get','install','-y','--no-install-recommends',*pkgs] if apply else ['apt-get','-s','install',*pkgs]
 elif action=='remove':
  if not pkgs or any(not PKG.fullmatch(x) for x in pkgs):raise SystemExit('Supply valid Debian package names')
  cmd=['apt-get','remove','-y',*pkgs] if apply else ['apt-get','-s','remove',*pkgs]
 else:raise SystemExit('apt: plan|update|upgrade|install|remove')
 if apply and os.geteuid()!=0:raise SystemExit('Requires root for --apply')
 if action in ('install','upgrade','remove') and apply:
  sim=['apt-get','-s',action,*pkgs]
  rc,out=run(sim,90)
  if rc:raise SystemExit(out)
  removed=[x.split()[1] for x in out.splitlines() if x.startswith('Remv ')]
  if action=='remove':
   protected=re.compile(r'^(proxmox|pve-|libpve|qemu-server|lxc-pve|systemd|libc6|apt$|dpkg$|openssh-server|ifupdown2|linux-image|grub|zfs)',re.I)
   if any(protected.match(p) for p in pkgs):raise SystemExit('Refusing core infrastructure removal')
   unexpected=[p for p in removed if p not in pkgs]
   if unexpected:raise SystemExit('Unexpected dependency removals: '+', '.join(unexpected))
  elif removed:raise SystemExit('Refusing package transaction with removals: '+', '.join(removed))
 rc,out=run(cmd,900 if apply else 60)
 print(out[-8000:] or f'exit={rc}')
 record('apt',action,'PASS' if rc==0 else 'FAIL',f'apply={apply}; exit={rc}; packages={pkgs}')
 if rc:raise SystemExit(rc)
def generate(n,kind):
 n=clean_name(n)
 if kind not in ('site','game','cli'):raise SystemExit('kit type: site|game|cli')
 home=ROOT/'projects'/n
 if home.exists():raise SystemExit('Already exists: '+str(home))
 home.mkdir(parents=True)
 if kind=='cli':
  (home/'main.py').write_text("#!/usr/bin/env python3\nimport datetime\nprint('Hello from %s:',datetime.datetime.now().isoformat())\n"%n)
  (home/'test.sh').write_text('#!/bin/sh\nset -eu\npython3 main.py | grep -q "Hello from"\n')
  (home/'Makefile').write_text('.PHONY: run test\nrun:\n\tpython3 main.py\ntest:\n\tsh test.sh\n')
 else:
  css='body{font:18px system-ui;background:linear-gradient(120deg,#0a1223,#182f43);color:#ecfeff;min-height:100vh;display:grid;place-items:center}.card{padding:42px;border:1px solid #42617b;border-radius:22px;background:#101b31;max-width:580px;box-shadow:0 25px 65px #050b18}button{padding:12px 21px;background:#7de8cc;color:#142035;border:0;border-radius:12px;font-weight:700;cursor:pointer}h1{font-size:46px}'
  if kind=='game':body=f'<h1>{html.escape(n)} / Reaction Lab</h1><p>Click the button. Try for 10 points.</p><p id="score">Score 0</p><button id="tap">TAP</button><script>let s=0;document.getElementById("tap").onclick=()=>{{document.getElementById("score").textContent="Score "+(++s)}};</script>'
  else:body=f'<h1>{html.escape(n)}</h1><p>Independent micro-site, locally built and testable.</p><p>Generated {html.escape(now())}</p><button onclick="this.textContent=\'RUNNING\'">Launch</button>'
  (home/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(n)+'</title><style>'+css+'</style><main class="card">'+body+'</main></html>')
  (home/'Makefile').write_text('.PHONY: test\ntest:\n\tgrep -q "<!doctype html>" index.html\n')
 (home/'README.md').write_text(f'# {n}\n\nKind: {kind}\n\nRun: `make test`\n')
 with init() as db:db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(n,kind,now(),'BUILT',''))
 record('kitchen','create','PASS',f'{kind} {n}')
 print(f'BUILT {kind}: {home}\nTEST: fac oven {n}\nPUBLISH: fac stove {n}')
def oven(n):
 n=clean_name(n);home=ROOT/'projects'/n
 if not home.is_dir():raise SystemExit('Unknown project')
 rc,out=run(['make','-C',str(home),'test'],20)
 print(out or f'TEST={rc}')
 with init() as db:
  db.execute('UPDATE projects SET status=? WHERE name=?',('TESTED' if rc==0 else 'FAILED',n))
 record('oven','test','PASS' if rc==0 else 'FAIL',n)
 if rc:raise SystemExit(rc)
def stove(n):
 n=clean_name(n);home=ROOT/'projects'/n
 if not (home/'index.html').is_file():raise SystemExit('Only static website/game can be published')
 oven(n)
 target=WWW/'apps'/n
 if target.exists():
  shutil.rmtree(target)
 target.mkdir(parents=True)
 shutil.copy2(home/'index.html',target/'index.html')
 digest=hashlib.sha256((target/'index.html').read_bytes()).hexdigest()
 with init() as db:db.execute('UPDATE projects SET status=?,sha=? WHERE name=?',('PUBLISHED',digest,n))
 print(f'PUBLISHED {n}: /facilities/apps/{n}/ SHA256={digest}')
 record('stove','publish','PASS',n)
def sink():
 print('APT AUTOREMOVE CANDIDATES (simulation only)')
 print(run(['apt-get','-s','autoremove'],40)[1][-4000:])
 print('OWN PROJECT DIRECTORY SIZES')
 print(run(['du','-sh',str(ROOT/'projects'),str(ROOT/'snapshots'),str(ROOT/'media')])[1])
def headphones(folder):
 p=pathlib.Path(folder)
 if not p.is_dir():raise SystemExit('Media directory unavailable')
 extensions={'.mp3','.flac','.ogg','.wav','.m4a'}
 items=[{'name':x.name,'size':x.stat().st_size,'path':str(x)} for x in p.rglob('*') if x.is_file() and x.suffix.lower() in extensions][:2000]
 (ROOT/'reports'/'media.json').write_text(json.dumps({'at':now(),'items':items},indent=2))
 print(f'INDEXED {len(items)} audio files in {p}; report: {ROOT}/reports/media.json')
 record('headphones','index','PASS',f'{len(items)} files')
def add_feed(url):
 from urllib.parse import urlparse
 p=urlparse(url)
 if p.scheme!='https' or not p.hostname or p.username or p.password:raise SystemExit('Use a public HTTPS RSS/Atom URL')
 if p.hostname in ('localhost','127.0.0.1','::1') or p.hostname.endswith(('.local','.internal')):raise SystemExit('Use public HTTPS source')
 with init() as db:db.execute('INSERT OR IGNORE INTO feeds(url,added) VALUES(?,?)',(url,now()))
 print('FEED REGISTERED',url)
def refresh_feeds():
 from urllib.parse import urlparse
 with init() as db:
  feeds=[r[0] for r in db.execute('SELECT url FROM feeds ORDER BY url LIMIT 12')]
  new=0
  for url in feeds:
   try:
    u=urlparse(url)
    if u.scheme!='https':continue
    req=urllib.request.Request(url,headers={'User-Agent':'LS-Facilities/1.0'})
    with urllib.request.urlopen(req,timeout=7) as res:raw=res.read(250000)
    root=ET.fromstring(raw)
    found=[]
    for entry in root.iter():
     if entry.tag.rsplit('}',1)[-1] not in ('entry','item'):continue
     fields={}
     for child in entry:
      k=child.tag.rsplit('}',1)[-1]
      if k in ('title','guid','id','link'):
       fields.setdefault(k,(child.attrib.get('href') or ''.join(child.itertext())).strip())
     title=fields.get('title','')[:250]
     link=fields.get('link','')[:500]
     guid=fields.get('guid') or fields.get('id') or link or title
     if title and guid:found.append((url,guid[:500],title,link,now()))
    old=db.total_changes
    db.executemany('INSERT OR IGNORE INTO articles(feed,guid,title,url,seen) VALUES(?,?,?,?,?)',found[:40])
    new+=db.total_changes-old
    db.execute('UPDATE feeds SET last_poll=?,error=NULL WHERE url=?',(now(),url))
   except Exception as e:db.execute('UPDATE feeds SET error=? WHERE url=?',(str(e)[:200],url))
 print(f'FEEDS={len(feeds)} NEW_ITEMS={new}')
 record('water','refresh','PASS',f'feeds={len(feeds)},new={new}')
def universe(num=5,seed=None):
 num=max(1,min(num,25));seed=int(seed if seed is not None else time.time_ns()%99999999);rng=random.Random(seed)
 print('SEED',seed)
 with init() as db:
  for _ in range(num):
   a,b,c=rng.choice(PERSONAS),rng.choice(OBJECTS),rng.choice(MECHANISMS)
   proposal=f'{a} × {b} × {c}'
   db.execute('INSERT OR IGNORE INTO ideas(created,seed,persona,object,mechanism,proposal,status) VALUES(?,?,?,?,?,?,?)',(now(),seed,a,b,c,proposal,'IDEA'))
   print('IDEA:',proposal)
 record('universe','generate','PASS',f'count={num};seed={seed}')
def skill(action,name=None,verb=None):
 if action=='list':
  with init() as db:
   rows=db.execute('SELECT name,verb,args FROM skills ORDER BY name').fetchall()
  for k,(v,a) in RECIPES.items():print(f'{k:22} {v} {" ".join(a)} (builtin)')
  for n,v,a in rows:print(f'{n:22} {v} {a} (custom)')
 elif action=='new':
  clean_name(name)
  if verb not in ROLES or verb in ('apt','skill','stove','kitchen'):raise SystemExit('Use a read-only role: glasses, clock, services, ports, storage, resources, bathroom, universe, water')
  with init() as db:db.execute('INSERT INTO skills VALUES(?,?,?,?)',(name,verb,'[]',now()))
  print('SKILL CREATED',name, '->',verb)
 elif action=='run':
  with init() as db:row=db.execute('SELECT verb,args FROM skills WHERE name=?',(name,)).fetchone()
  if row:verb,args=row[0],json.loads(row[1])
  elif name in RECIPES:verb,args=RECIPES[name]
  else:raise SystemExit('Skill not found')
  return dispatch(verb,args)
def microwave():
 checks=[]
 for label,fn in [('sqlite',lambda:dbcheck()),('host',lambda:metrics()[1]>0),('python',lambda:sys.version_info.major==3),('project-db',lambda:(ROOT/'projects').is_dir())]:
  try:ok=bool(fn())
  except Exception:ok=False
  checks.append((label,ok));print(('PASS' if ok else 'FAIL'),label)
 record('microwave','smoke','PASS' if all(x[1] for x in checks) else 'FAIL',str(checks))
 if not all(x[1] for x in checks):raise SystemExit(1)
def dbcheck():
 with init() as d:return d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
def burner():
 data=b'LS-ATOMIC-FACILITIES'*65536
 t=time.perf_counter()
 digest=None
 for _ in range(16):digest=hashlib.sha256(data).hexdigest()
 ms=round((time.perf_counter()-t)*1000,2)
 print(f'BENCH SHA256 16 x {len(data)} bytes = {ms} ms; digest={digest}')
 record('burner','benchmark','PASS',f'ms={ms}')
def search(term):
 term=term.strip()
 if not term or len(term)>100:raise SystemExit('Search term required, max 100 chars')
 with init() as db:
  rows=[]
  for tbl,col in [('ideas','proposal'),('articles','title'),('events','detail')]:
   for x in db.execute(f'SELECT {col} FROM {tbl} WHERE {col} LIKE ? ORDER BY id DESC LIMIT 12',(f'%{term}%',)):
    rows.append((tbl,x[0]))
 for k,v in rows[:30]:print(f'{k}: {v}')
 print('RESULTS',len(rows))
def porter():
 with init() as db:
  for name,kind,status in db.execute('SELECT name,kind,status FROM projects ORDER BY created DESC LIMIT 60'):
   print(f'{name:24} {kind:6} {status:12} /facilities/apps/{name}/' if status=='PUBLISHED' else f'{name:24} {kind:6} {status}')
def snapshot():
 WWW.mkdir(parents=True,exist_ok=True)
 l,m,d,n=metrics()
 with init() as db:
  db.execute('INSERT INTO samples(at,load,ram_mb,disks,lxcs) VALUES(?,?,?,?,?)',(now(),l,m,d[-600:],n))
  projects=db.execute('SELECT name,kind,status FROM projects ORDER BY created DESC LIMIT 20').fetchall()
  ideas=db.execute('SELECT proposal FROM ideas ORDER BY id DESC LIMIT 12').fetchall()
  articles=db.execute('SELECT title,url FROM articles ORDER BY id DESC LIMIT 12').fetchall()
  events=db.execute('SELECT at,role,action,status FROM events ORDER BY id DESC LIMIT 20').fetchall()
 def escape(x):return html.escape(str(x),quote=True)
 styles='''body{background:#08111c;color:#e2e9f4;font:15px system-ui,sans-serif;margin:0 auto;padding:35px;max-width:1200px}h1{font-size:clamp(32px,5vw,56px);letter-spacing:-2px;margin:3px 0 20px}small{color:#8ba1b8} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:13px}section,.card{background:#111f31;border:1px solid #263a52;border-radius:16px;padding:19px;margin:12px 0}h2{color:#a3ebd8;font-size:19px}strong{font-size:26px;color:#e5faf4}a{color:#8bd3fa}li{margin:9px 0}code{color:#afffce} .tag{color:#b1c3db;font-size:12px}ul{padding-left:18px} .head{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap} .pill{background:#183c44;padding:8px 12px;border-radius:30px;color:#85f0ce}'''
 cards=[('Host',os.uname().nodename),('Load',l),('Available RAM',f'{m} MB'),('LXCs',n),('Projects',len(projects)),('Knowledge',len(articles))]
 s=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60"><title>LS FACILITIES</title><style>'+styles+'</style><body><div class="head"><div><small>LS ∞ • ATOMIC SYSTEM WORKSHOP</small><h1>FACILITIES</h1></div><span class="pill">SYSTEMD • SQLITE • ZERO NEW DAEMONS</span></div><div class="grid">']
 for k,v in cards:s.append(f'<div class="card"><small>{escape(k)}</small><p><strong>{escape(v)}</strong></p></div>')
 s+=['</div><section><h2>Operational departments</h2><div class="grid">']
 for k,v in ROLES.items():s.append(f'<div><b>{escape(k.upper())}</b><p class="tag">{escape(v)}<p><code>fac {escape(k)}</code></div>')
 s.append('</div></section><div class="grid">')
 def block(title,rows,render):
  s.append('<section><h2>'+escape(title)+'</h2><ul>')
  for x in rows:s.append('<li>'+render(x)+'</li>')
  s.append('</ul></section>')
 block('Built projects',projects,lambda p: f'<a href="apps/{escape(p[0])}/">{escape(p[0])}</a> · {escape(p[1])} · {escape(p[2])}')
 block('Idea collisions',ideas,lambda x:escape(x[0]))
 block('Knowledge intake',articles,lambda x:f'<a rel="noreferrer noopener" target="_blank" href="{escape(x[1])}">{escape(x[0])}</a>' if str(x[1]).startswith('https://') else escape(x[0]))
 block('Recent operations',events,lambda e:escape(' | '.join(map(str,e))))
 s.append('</div><small>Local read-only view • Use terminal for privileged actions • Refreshes every 60 seconds</small></body></html>')
 tmp=WWW/'index.html.tmp'; tmp.write_text('\n'.join(s));tmp.replace(WWW/'index.html')
 print(f'DASHBOARD={WWW}/index.html')
def checkpoint():
 dest=ROOT/'snapshots'/('fac-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite')
 with init() as db:
  backup=sqlite3.connect(dest)
  with backup:db.backup(backup)
  backup.close()
 digest=hashlib.sha256(dest.read_bytes()).hexdigest()
 print(f'CHECKPOINT={dest} SHA256={digest}')
 record('checkpoint','backup','PASS',str(dest))
def dispatch(cmd,args):
 if cmd in ('status','facts'):status()
 elif cmd in ('glasses','inspect'):glasses()
 elif cmd=='clock':clock()
 elif cmd=='services':services()
 elif cmd=='ports':ports()
 elif cmd=='storage':storage()
 elif cmd=='resources':resources()
 elif cmd=='microwave':microwave()
 elif cmd=='burner':burner()
 elif cmd=='search':search(' '.join(args))
 elif cmd=='porter':porter()
 elif cmd=='bathroom':bathroom()
 elif cmd=='sink':sink()
 elif cmd=='headphones':headphones(args[0] if args else '/srv/media')
 elif cmd=='apt':
  ap=argparse.ArgumentParser(prog='fac apt');ap.add_argument('action',choices=['plan','update','install','upgrade','remove']);ap.add_argument('packages',nargs='*');ap.add_argument('--apply',action='store_true');r=ap.parse_args(args);apt(r.action,r.packages,r.apply)
 elif cmd=='kitchen':
  if len(args)<3 or args[0]!='new':raise SystemExit('fac kitchen new NAME site|game|cli')
  generate(args[1],args[2])
 elif cmd=='oven':oven(args[0])
 elif cmd=='stove':stove(args[0])
 elif cmd=='universe':universe(int(args[0]) if args else 5,int(args[1]) if len(args)>1 else None)
 elif cmd=='water':
  if args and args[0]=='add':add_feed(args[1]);
  elif not args or args[0]=='refresh':refresh_feeds()
  else:raise SystemExit('fac water add https://... | fac water refresh')
 elif cmd=='skill':skill(args[0] if args else 'list',args[1] if len(args)>1 else None,args[2] if len(args)>2 else None)
 elif cmd=='checkpoint':checkpoint()
 elif cmd=='timers':print(run(['systemctl','list-timers','--all','--no-pager'])[1][:6000])
 elif cmd=='snapshot':snapshot()
 elif cmd=='db':
  with init() as db:print('DB=',DB,'CHECK=',db.execute('PRAGMA integrity_check').fetchone()[0]);print('EVENTS=',db.execute('SELECT COUNT(*) FROM events').fetchone()[0])
 elif cmd=='help':
  print('''LS FACILITIES — roles are actual operations
 fac                  system status
 fac glasses          inspect host + LXCs
 fac clock            local/UTC timestamps
 fac services         service failures
 fac ports            listening sockets
 fac storage          disks and mounts
 fac porter           published project map
 fac microwave        smoke tests
 fac burner           microbenchmark
 fac search TERM      query collected facts
 fac resources        performance and RAM
 fac apt plan         package upgrade simulation
 fac apt install jq --apply  install package
 fac apt upgrade --apply    upgrade (blocks planned removals)
 fac kitchen new NAME site|game|cli
 fac oven NAME        test project
 fac stove NAME       publish static site
 fac sink             cleanup candidates
 fac bathroom         failure audit
 fac water add HTTPS_URL; fac water refresh
 fac headphones DIR   index audio library
 fac universe 5 [SEED]   deterministic idea generation
 fac skill list | new NAME ROLE | run NAME
 fac checkpoint       consistent database backup
 fac db               SQLite integrity
 fac snapshot         update static dashboard
 fac timers           show schedules''')
 else:raise SystemExit(f'Unknown role: {cmd}; use fac help')
def main():
 dispatch(sys.argv[1] if len(sys.argv)>1 else 'status',sys.argv[2:])
if __name__=='__main__':main()