#!/usr/bin/env python3
"""LS Micro Crew: bounded, durable, no-AI job routing, research and static prototype CI."""
import argparse, concurrent.futures, datetime as dt, hashlib, html, json, os
from pathlib import Path
import re, shutil, sqlite3, subprocess, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(os.getenv('LS_CREW_HOME', '/opt/ls-crew'))
WEB = Path(os.getenv('LS_CREW_WWW', '/opt/ls-conquer/www/crew'))
DB = ROOT/'crew.sqlite'
USER_AGENT = 'LS-MicroCrew/1.0 (+research RSS/Atom; noncommercial)'
SOURCES = [
    ('Proxmox scripts', 'https://github.com/community-scripts/ProxmoxVE/releases.atom'),
        ('Caddy', 'https://github.com/caddyserver/caddy/releases.atom'),
    ('just', 'https://github.com/casey/just/releases.atom'),
]
TASKS = ('build','test','deploy','archive','probe','inventory','collect','search','backup')

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def stamp(): return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S%f')
def sha(b): return hashlib.sha256(b if isinstance(b,bytes) else b.encode()).hexdigest()
def slug(s):
    v=s.strip().lower()
    if len(v)>48 or not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?',v):
        raise ValueError('Name must contain only letters, numbers or internal hyphens (max 48)')
    return v

class ScopedConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

def connect():
    ROOT.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB,timeout=15,factory=ScopedConnection)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('PRAGMA foreign_keys=ON')
    return db

def init():
    for d in [ROOT,ROOT/'artifacts',ROOT/'receipts',ROOT/'snapshots',ROOT/'logs',ROOT/'inbox',ROOT/'processed',WEB,WEB/'apps']:
        d.mkdir(parents=True,exist_ok=True)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,created TEXT NOT NULL,last_release TEXT);
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,project TEXT,task TEXT NOT NULL,payload TEXT NOT NULL DEFAULT '{}',depends INTEGER REFERENCES jobs(id),status TEXT NOT NULL DEFAULT 'QUEUED',created TEXT,started TEXT,finished TEXT,ms INTEGER,detail TEXT);
        CREATE INDEX IF NOT EXISTS job_ready ON jobs(status,depends,id);
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,name TEXT UNIQUE,url TEXT NOT NULL,last_checked TEXT,last_error TEXT);
        CREATE TABLE IF NOT EXISTS fuel(id INTEGER PRIMARY KEY,source TEXT,key TEXT,title TEXT,url TEXT,summary TEXT,ts TEXT,UNIQUE(source,key));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts TEXT,kind TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS snapshots(ts TEXT PRIMARY KEY,filename TEXT,sha TEXT,size INTEGER);
        ''')
        for name,url in SOURCES: db.execute('INSERT OR IGNORE INTO sources(name,url) VALUES(?,?)',(name,url))

def event(kind,detail):
    with connect() as db: db.execute('INSERT INTO events(ts,kind,detail) VALUES(?,?,?)',(now(),kind,str(detail)[:500]))

def add_project(name,kind='pulse'):
    name=slug(name)
    if kind not in ('pulse','inventory','research','lab'): raise ValueError('kind: pulse, inventory, research, lab')
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO projects(name,kind,created) VALUES(?,?,?)',(name,kind,now()))
    event('PROJECT',f'{name} created {kind}')
    return name

def add_job(task,project=None,payload=None,depends=None):
    if task not in TASKS: raise ValueError('Unknown task')
    with connect() as db:
        cur=db.execute('INSERT INTO jobs(project,task,payload,depends,status,created) VALUES(?,?,?,?,?,?)',(project,task,json.dumps(payload or {}),depends,'QUEUED',now()))
        return cur.lastrowid

def pipeline(name):
    with connect() as db:
        if not db.execute('SELECT 1 FROM projects WHERE name=?',(name,)).fetchone():
            raise ValueError('Unknown project: '+name)
    prev=None; ids=[]
    for task in ('build','test','deploy','archive'):
        prev=add_job(task,name,depends=prev); ids.append(prev)
    event('PIPELINE',f'{name}: jobs {ids}')
    return ids

def fetch(url, limit=250_000):
    u=urllib.parse.urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ValueError('Only public HTTPS URLs supported')
    h=u.hostname.lower().rstrip('.')
    if h=='localhost' or h.endswith('.local') or h.endswith('.internal') or h.endswith('.localhost') or h.endswith('.onion'):
        raise ValueError('Local network URL disallowed')
    import ipaddress, socket
    # Avoid remote content redirecting to local/private addresses.
    def public_host(host):
        ips=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        if not ips: raise ValueError('No DNS addresses')
        if any(not ipaddress.ip_address(x[4][0]).is_global for x in ips):
            raise ValueError('Non-public address rejected')
    public_host(h)
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            p=urllib.parse.urlsplit(newurl)
            if p.scheme!='https' or not p.hostname: raise ValueError('Unsafe redirect')
            public_host(p.hostname)
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    opener=urllib.request.build_opener(SafeRedirect)
    with opener.open(urllib.request.Request(url,headers={'User-Agent':USER_AGENT}),timeout=10) as r:
        data=r.read(limit+1)
        if len(data)>limit: raise ValueError('Feed/search response too large')
        return data

def items_rss(data):
    root=ET.fromstring(data)
    records=[]
    for item in root.iter():
        if item.tag.split('}')[-1] not in ('item','entry'): continue
        def child(name):
            for e in item:
                if e.tag.split('}')[-1] == name:
                    return (e.attrib.get('href') or ''.join(e.itertext())).strip()
            return ''
        title=child('title')[:220]
        link=child('link')[:500]
        summary=re.sub('<[^>]*>',' ',child('summary') or child('description'))[:1000]
        key=(child('id') or child('guid') or link or title)[:500]
        if title and key: records.append((key,title,link,summary))
    return records[:30]

def fuel_add(source,key,title,url='',summary=''):
    with connect() as db:
        c=db.execute('INSERT OR IGNORE INTO fuel(source,key,title,url,summary,ts) VALUES(?,?,?,?,?,?)',(source,key,title[:220],url[:500],summary[:1000],now()))
        return c.rowcount

def handle(task,project,payload):
    if task=='build':
        with connect() as db: row=db.execute('SELECT * FROM projects WHERE name=?',(project,)).fetchone()
        if not row: raise RuntimeError('Missing project')
        name=html.escape(row['name']); kind=html.escape(row['kind'])
        metrics={'pulse':'Server pulse','inventory':'Machine inventory','research':'Information feed','lab':'Experimental workbench'}
        summary=metrics[row['kind']]
        details=''
        if row['kind']=='research':
            with connect() as db:
                headlines=[x[0] for x in db.execute('SELECT title FROM fuel ORDER BY id DESC LIMIT 8')]
            details='<h2>Recent discoveries</h2><ul>'+''.join('<li>'+html.escape(t)+'</li>' for t in headlines)+'</ul>'
        elif row['kind']=='lab':
            pairs=[('curl','jq'),('git','make'),('sqlite3','python3'),('pct','pveam'),('rsync','zstd')]
            details='<h2>Tool collisions</h2><ul>'+''.join('<li>'+html.escape(x)+' + '+html.escape(y)+': '+('READY' if shutil.which(x) and shutil.which(y) else 'MISSING')+'</li>' for x,y in pairs)+'</ul>'
        elif row['kind']=='inventory':
            p=sorted((ROOT/'receipts').glob('inventory-*.txt'))
            if p:details='<h2>Latest host inventory</h2><pre style="white-space:pre-wrap">'+html.escape(p[-1].read_text()[:1400])+'</pre>'
        else:
            details='<h2>Host pulse</h2><p>Load 1m: '+str(round(os.getloadavg()[0],2))+' · CPU threads: '+str(os.cpu_count() or 1)+'</p>'
        contents=(f'<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
                  f'<title>{name}</title><style>body{{background:#0b1020;color:#edf4ff;font:18px system-ui;margin:9vw auto;'
                  f'max-width:700px;padding:24px}}section{{border:1px solid #33425b;border-radius:18px;padding:30px;'
                  f'background:#172239}}h1{{font-size:clamp(32px,6vw,56px)}}small{{color:#8aa5cc}}</style></head>'
                  f'<body><small>LS MICRO CREW · {kind.upper()}</small><section><h1>{name}</h1><p>{summary}</p>'
                  f'<p>Generated: {html.escape(now())}</p><p>✓ Built by FORGE</p>{details}</section></body></html>')
        out=ROOT/'artifacts'/project; out.mkdir(parents=True,exist_ok=True)
        tmp=out/'index.tmp'; tmp.write_text(contents); tmp.replace(out/'index.html')
        return f'built {project}: {len(contents.encode())} bytes sha256={sha(contents)[:16]}'
    if task=='test':
        p=ROOT/'artifacts'/project/'index.html'
        if not p.exists(): raise RuntimeError('No build artifact')
        text=p.read_text()
        if '<!doctype html>' not in text or '<h1>' not in text or html.escape(project) not in text:
            raise RuntimeError('HTML acceptance failed')
        return 'PASS HTML + project marker + valid artifact '+sha(text)[:16]
    if task=='deploy':
        p=ROOT/'artifacts'/project/'index.html'
        if not p.exists(): raise RuntimeError('Artifact missing')
        dst=WEB/'apps'/project
        dst.mkdir(parents=True,exist_ok=True)
        tmp=dst/'index.html.tmp'; shutil.copyfile(p,tmp); tmp.replace(dst/'index.html')
        with connect() as db: db.execute('UPDATE projects SET last_release=? WHERE name=?',(now(),project))
        return 'STATIC DEPLOY /crew/apps/'+project+'/'
    if task=='archive':
        src=ROOT/'artifacts'/project/'index.html'
        if not src.exists(): raise RuntimeError('No artifact')
        meta={'at':now(),'project':project,'sha256':sha(src.read_bytes()),'bytes':src.stat().st_size}
        dest=ROOT/'receipts'/f'{project}-{stamp()}.json'; dest.write_text(json.dumps(meta,indent=2))
        return 'RECORDED '+dest.name
    if task=='probe':
        vals={'hostname':os.uname().nodename,'load':os.getloadavg()[0]}
        with open('/proc/meminfo') as f:
            for l in f:
                if l.startswith('MemAvailable:'): vals['available_mb']=int(l.split()[1])//1024; break
        return json.dumps(vals)
    if task=='inventory':
        p=ROOT/'receipts'/f'inventory-{stamp()}.txt'
        cmds=[['df','-h','/'],['ps','-eo','pid,comm,rss','--sort=-rss']]
        if shutil.which('pct'): cmds.append(['pct','list'])
        if shutil.which('pvesm'): cmds.append(['pvesm','status'])
        out=[]
        for c in cmds:
            try:
                r=subprocess.run(c,capture_output=True,text=True,timeout=7,check=False)
                out.append('$ '+' '.join(c)+'\n'+(r.stdout or r.stderr)[:8000])
            except (OSError,subprocess.TimeoutExpired) as e: out.append(str(e))
        p.write_text('\n'.join(out))
        return 'INVENTORY '+p.name
    if task=='collect':
        url=payload['url']; source=payload.get('source',url)
        rows=items_rss(fetch(url)); total=sum(fuel_add(source,*r) for r in rows)
        with connect() as db:
            db.execute('UPDATE sources SET last_checked=?,last_error=NULL WHERE url=?',(now(),url))
        return f'FEED {source}: {len(rows)} entries, {total} new'
    if task=='search':
        term=payload['term'].strip()[:100]; engine=payload.get('engine','hn')
        if engine=='github':
            url='https://api.github.com/search/repositories?q='+urllib.parse.quote(term)+'&per_page=10'
            records=json.loads(fetch(url,150_000)).get('items',[])
            n=sum(fuel_add('github-search',str(r.get('id')),r.get('full_name',''),r.get('html_url',''),r.get('description') or '') for r in records)
        else:
            url='https://hn.algolia.com/api/v1/search?tags=story&query='+urllib.parse.quote(term)+'&hitsPerPage=12'
            records=json.loads(fetch(url,150_000)).get('hits',[])
            n=sum(fuel_add('hn-search',str(r.get('objectID')),r.get('title') or '',r.get('url') or '',r.get('story_text') or '') for r in records if r.get('title'))
        return f'SEARCH {engine} {term}: {len(records)} results, {n} new'
    if task=='backup':
        dest=ROOT/'snapshots'/f'crew-{stamp()}.sqlite'
        with connect() as source:
            target=sqlite3.connect(dest)
            try:source.backup(target)
            finally:target.close()
        b=dest.read_bytes()
        with connect() as db: db.execute('INSERT INTO snapshots(ts,filename,sha,size) VALUES(?,?,?,?)',(now(),dest.name,sha(b),len(b)))
        return f'BACKUP {dest.name} {len(b)} bytes'
    raise RuntimeError('Unknown task '+task)

def claim():
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('''SELECT j.* FROM jobs j LEFT JOIN jobs d ON d.id=j.depends
               WHERE j.status='QUEUED' AND (j.depends IS NULL OR d.status='PASS') ORDER BY j.id LIMIT 1''').fetchone()
        if row: db.execute('UPDATE jobs SET status=?,started=? WHERE id=?',('RUNNING',now(),row['id']))
        return dict(row) if row else None

def worker():
    job=claim()
    if not job: return False
    t=time.monotonic(); ok=True
    try: detail=handle(job['task'],job['project'],json.loads(job['payload']))
    except Exception as e: ok=False; detail=f'{type(e).__name__}: {e}'
    ms=round((time.monotonic()-t)*1000)
    with connect() as db:
        db.execute('UPDATE jobs SET status=?,finished=?,ms=?,detail=? WHERE id=?',('PASS' if ok else 'FAIL',now(),ms,str(detail)[:800],job['id']))
        if not ok:
            # Propagate dependency failures throughout the full pipeline.
            nextid=job['id']
            while True:
                rows=db.execute("SELECT id FROM jobs WHERE status='QUEUED' AND depends=?",(nextid,)).fetchall()
                if not rows: break
                for row in rows:
                    db.execute("UPDATE jobs SET status='BLOCKED',finished=?,detail=? WHERE id=?",(now(),'Prerequisite failed',row['id']))
                    nextid=row['id']
        db.execute('INSERT INTO events(ts,kind,detail) VALUES(?,?,?)',(now(),job['task'].upper(),f'#{job["id"]} {"PASS" if ok else "FAIL"} {ms}ms {detail[:180]}'))
    return True

def capacity():
    try:
        with open('/proc/meminfo') as f: mem=int(next(l.split()[1] for l in f if l.startswith('MemAvailable:')))//1024
        load=os.getloadavg()[0]
        cpus=max(1,os.cpu_count() or 1)
        # Work never blocks host: scale to small number, degrade under load.
        if mem<400 or load>cpus*1.2: return 1
        return max(1,min(4,cpus-1,max(1,mem//450)))
    except Exception: return 1

def run(max_seconds=40):
    max_seconds=max(1,min(120,int(max_seconds)))
    workers=capacity(); deadline=time.monotonic()+max_seconds; processed=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        while time.monotonic()<deadline:
            if not has_ready(): break
            fs=[ex.submit(worker) for _ in range(workers)]
            for f in fs:
                if f.result(): processed+=1
    render()
    print(f'RUN jobs={processed} workers={workers} remaining={queued_count()}')
    return processed

def has_ready():
    with connect() as db:
        return bool(db.execute('''SELECT 1 FROM jobs j LEFT JOIN jobs d ON j.depends=d.id WHERE j.status='QUEUED' AND (j.depends IS NULL OR d.status='PASS') LIMIT 1''').fetchone())

def queued_count():
    with connect() as db: return db.execute("SELECT count(*) FROM jobs WHERE status='QUEUED'").fetchone()[0]

def recover():
    # After abrupt host reboot, retry stranded tasks, idempotent for built-in actions.
    with connect() as db:
        n=db.execute("UPDATE jobs SET status='QUEUED',detail='recovered after interruption' WHERE status='RUNNING' AND started<?",((dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=5)).isoformat(),)).rowcount
    if n: event('RECOVERY',f'Requeued {n} interrupted tasks')

def process_inbox():
    total=0
    for p in sorted((ROOT/'inbox').glob('*.json'))[:30]:
        if p.is_symlink() or not p.is_file():continue
        try:
            if p.stat().st_size>16384: raise ValueError('Request over 16 KB')
            req=json.loads(p.read_text())
            kind=req.get('kind','')
            if kind=='pipeline':
                pipeline(slug(req['project']))
            elif kind=='research':
                term=str(req['term'])[:100]
                add_job('search',payload={'term':term,'engine':req.get('engine','hn')})
            elif kind=='inventory': add_job('inventory')
            elif kind=='probe': add_job('probe')
            elif kind=='backup': add_job('backup')
            else: raise ValueError('Unknown inbox route')
            dest=ROOT/'processed'/f'{stamp()}-{p.name}'
            p.replace(dest);total+=1
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
            # Leave the original request for diagnosis rather than silent deletion.
            event('INBOX_ERROR',f'{p.name}: {str(e)[:120]}')
    if total:event('INBOX',f'Accepted {total} requests')
    print('INBOX accepted',total)
    return total

def sync_local(destination):
    dest=Path(destination).expanduser().resolve()
    if not dest.is_dir() or dest == Path('/') or dest == ROOT or ROOT in dest.parents:
        raise ValueError('Destination must be an existing directory outside LS Crew')
    if not shutil.which('rsync'): raise ValueError('rsync missing')
    for folder in ('receipts','snapshots'):
        target=dest/'ls-crew'/folder
        target.mkdir(parents=True,exist_ok=True)
        subprocess.run(['rsync','-a','--',str(ROOT/folder)+'/',str(target)+'/'],check=True,timeout=60)
    event('SYNC',f'Copied receipts and snapshots to {dest}')
    print('SYNC',dest)

def rotate():
    # Compact only own generated receipts, never touch user project files.
    for name in set(p.name.split('-')[0] for p in (ROOT/'receipts').glob('*.json')):
        files=sorted((ROOT/'receipts').glob(name+'-*.json'))
        for p in files[:-12]: p.unlink()
    files=sorted((ROOT/'snapshots').glob('crew-*.sqlite'))
    for p in files[:-14]: p.unlink()

def cycle(online=False):
    recover()
    process_inbox()
    add_job('probe')
    add_job('inventory')
    with connect() as db:
        projects=db.execute('SELECT name FROM projects ORDER BY id LIMIT 8').fetchall()
        source=db.execute('SELECT name,url FROM sources WHERE url LIKE "https://%" ORDER BY coalesce(last_checked, ""),id LIMIT 3').fetchall()
    for r in projects: pipeline(r['name'])
    if online:
        for s in source: add_job('collect',payload={'source':s['name'],'url':s['url']})
    result=run(45)
    add_job('backup'); run(25); rotate()
    cfg=ROOT/'sync-destination'
    if cfg.exists():
        try:sync_local(cfg.read_text().strip())
        except (ValueError,OSError,subprocess.SubprocessError) as e:event('SYNC_FAILED',str(e))
    return result

def table(db,sql,params=()): return [dict(x) for x in db.execute(sql,params)]

def render():
    with connect() as db:
        projects=table(db,'SELECT name,kind,coalesce(last_release,\'not deployed\') AS deployed FROM projects ORDER BY name')
        jobs=table(db,'SELECT id,coalesce(project,\'-\') AS project,task,status,coalesce(ms,0) AS ms,coalesce(detail,\'\') AS detail FROM jobs ORDER BY id DESC LIMIT 40')
        feeds=table(db,'SELECT source,title,url FROM fuel ORDER BY id DESC LIMIT 12')
        errors=db.execute("SELECT count(*) FROM jobs WHERE status='FAIL'").fetchone()[0]
        passing=db.execute("SELECT count(*) FROM jobs WHERE status='PASS'").fetchone()[0]
    styles='body{background:#0b1020;color:#eef4ff;font:15px system-ui;margin:0 auto;max-width:1150px;padding:28px}h1{font-size:40px;margin:5px 0}small{color:#98abc8}table{width:100%;border-collapse:collapse;margin:16px 0 30px}th{text-align:left;color:#94a8c4}td,th{padding:9px;border-bottom:1px solid #273751;word-break:break-word}a{color:#86d6ff}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:22px}.card{border:1px solid #2d405b;background:#152139;border-radius:14px;padding:18px}.big{font-size:29px;color:#8ef2cb;font-weight:bold} .pass{color:#8ef2cb}.fail{color:#ff8f96}'
    body=[f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="35"><title>LS Micro Crew</title><style>{styles}</style></head><body>',f'<small>LS ∞ / AUTOMATION FLEET</small><h1>MICRO CREW</h1><small>{html.escape(now())} · auto-refresh 35 seconds</small>',f'<div class="cards"><div class="card"><small>PROJECTS</small><div class="big">{len(projects)}</div></div><div class="card"><small>PASS</small><div class="big">{passing}</div></div><div class="card"><small>FAIL</small><div class="big">{errors}</div></div><div class="card"><small>WORKERS AVAILABLE</small><div class="big">{capacity()}</div></div></div>']
    def row(vals): return '<tr>'+''.join('<td>'+html.escape(str(v))[:280]+'</td>' for v in vals)+'</tr>'
    body.append('<h2>Projects / prototypes</h2><table><tr><th>Project</th><th>Recipe</th><th>Last deploy</th></tr>')
    for p in projects: body.append(f'<tr><td><a href="apps/{urllib.parse.quote(p["name"])}/">{html.escape(p["name"])}</a></td><td>{html.escape(p["kind"])}</td><td>{html.escape(p["deployed"])}</td></tr>')
    body.append('</table><h2>Parallel job receipts</h2><table><tr><th>ID</th><th>Project</th><th>Stage</th><th>State</th><th>ms</th><th>Result</th></tr>')
    body.extend(row((j['id'],j['project'],j['task'],j['status'],j['ms'],j['detail'])) for j in jobs)
    body.append('</table><h2>Research fuel</h2><table><tr><th>Source</th><th>Finding</th></tr>')
    for r in feeds:
        # only trusted sanitized protocols in link
        u=r['url'] if urllib.parse.urlsplit(r['url']).scheme in ('https','http') else ''
        body.append(f'<tr><td>{html.escape(r["source"])}</td><td><a href="{html.escape(u,quote=True)}">{html.escape(r["title"])}</a></td></tr>')
    body.append('</table><small>Built with Python standard library + SQLite + systemd. Preview is static/read-only; external search/network may be rate-limited.</small></body></html>')
    tmp=WEB/'index.html.tmp'; tmp.write_text(''.join(body)); tmp.replace(WEB/'index.html')

def status():
    with connect() as db:
        p=db.execute('SELECT count(*) FROM projects').fetchone()[0]
        j=table(db,'SELECT status,count(*) AS n FROM jobs GROUP BY status')
        f=db.execute('SELECT count(*) FROM fuel').fetchone()[0]
    print(f'CREW projects={p} research={f} workers={capacity()} states={j} root={ROOT}')

def route(text):
    t=text.lower()
    if re.search(r'\b(search|research|find github|look up)\b',t):return 'research'
    if re.search(r'\b(feed|rss|ingest|collect)\b',t):return 'collect'
    if re.search(r'\b(build|deploy|prototype|site|website)\b',t):return 'pipeline'
    if re.search(r'\b(disk|storage|container|lxc|inventory)\b',t):return 'inventory'
    if re.search(r'\b(backup|checkpoint|snapshot)\b',t):return 'backup'
    return 'probe'

def main():
    ap=argparse.ArgumentParser(description='LS Micro Crew — self-contained, bounded multi-project workers')
    sp=ap.add_subparsers(dest='cmd')
    x=sp.add_parser('project'); x.add_argument('action',choices=['new','list']); x.add_argument('name',nargs='?'); x.add_argument('kind',nargs='?',default='pulse')
    x=sp.add_parser('pipeline'); x.add_argument('project')
    x=sp.add_parser('search'); x.add_argument('term',nargs='+'); x.add_argument('--engine',choices=['hn','github'],default='hn')
    x=sp.add_parser('feed'); x.add_argument('name'); x.add_argument('url')
    x=sp.add_parser('run'); x.add_argument('seconds',nargs='?',type=int,default=45)
    x=sp.add_parser('cycle'); x.add_argument('--online',action='store_true')
    x=sp.add_parser('route'); x.add_argument('text',nargs='+')
    x=sp.add_parser('jobs'); x.add_argument('--all',action='store_true')
    x=sp.add_parser('sync'); x.add_argument('destination'); x.add_argument('mode',nargs='?',choices=['set','now','off'],default='now')
    x=sp.add_parser('submit'); x.add_argument('kind',choices=['pipeline','research','inventory','probe','backup']); x.add_argument('arg',nargs='?')
    x=sp.add_parser('eyes')
    for cmd in ('init','demo','sources','fuel','facts','stats','test','board','backup','recover','inbox'):sp.add_parser(cmd)
    a=ap.parse_args(); init()
    if a.cmd=='project':
        if a.action=='new' and a.name: print('PROJECT',add_project(a.name,a.kind))
        else:
            with connect() as db:
                for r in db.execute('SELECT name,kind,last_release FROM projects ORDER BY name'): print(*r)
    elif a.cmd=='pipeline':print('PIPELINE',a.project,pipeline(slug(a.project)))
    elif a.cmd=='search':
        task=add_job('search',payload={'term':' '.join(a.term),'engine':a.engine}); print('SEARCH QUEUED',task);run()
    elif a.cmd=='feed':
        if urllib.parse.urlsplit(a.url).scheme!='https': raise ValueError('Feed must use HTTPS')
        with connect() as db:db.execute('INSERT OR REPLACE INTO sources(name,url) VALUES(?,?)',(a.name,a.url))
        print('SOURCE',a.name)
    elif a.cmd=='sources':
        with connect() as db:
            for x in db.execute('SELECT name,url,last_checked,last_error FROM sources ORDER BY name'): print(*x)
    elif a.cmd=='fuel':
        with connect() as db:
            for x in db.execute('SELECT source,title,url FROM fuel ORDER BY id DESC LIMIT 25'):print(' | '.join(str(y or '')[:140] for y in x))
    elif a.cmd=='run':run(a.seconds)
    elif a.cmd=='cycle':cycle(a.online)
    elif a.cmd=='demo':
        for name,kind in (('pulse','pulse'),('inventory','inventory'),('knowledge','research'),('workbench','lab')):
            add_project(name,kind);pipeline(name)
        run(60)
    elif a.cmd=='route':
        desc=' '.join(a.text); kind=route(desc);print('ROUTE',kind,desc)
        if kind=='research': print('NEXT crew search TERMS')
        elif kind=='pipeline':print('NEXT crew project new NAME && crew pipeline NAME && crew run')
        else:
            if kind=='collect':print('NEXT crew cycle --online')
            else: add_job('inventory' if kind=='inventory' else kind);run()
    elif a.cmd=='inbox':process_inbox();run(30)
    elif a.cmd=='sync':
        if a.mode=='set':
            d=Path(a.destination).expanduser().resolve()
            if not d.is_dir() or d==ROOT or ROOT in d.parents:raise ValueError('Select an existing external directory')
            (ROOT/'sync-destination').write_text(str(d))
            print('AUTO SYNC ENABLED',d)
        elif a.mode=='off':(ROOT/'sync-destination').unlink(missing_ok=True);print('AUTO SYNC OFF')
        else:sync_local(a.destination)
    elif a.cmd=='submit':
        req={'kind':a.kind}
        if a.kind=='pipeline':req['project']=slug(a.arg or '')
        if a.kind=='research':req['term']=a.arg or 'self hosting'
        f=ROOT/'inbox'/f'{stamp()}-{a.kind}.json'
        f.write_text(json.dumps(req))
        print('SUBMITTED',f.name)
    elif a.cmd=='eyes':
        if not shutil.which('tmux'): raise ValueError('tmux required; apt install tmux')
        name='crew'
        check=subprocess.run(['tmux','has-session','-t',name],capture_output=True)
        if check.returncode:
            subprocess.run(['tmux','new-session','-d','-s',name,'-n','CREW','watch -n 3 crew stats'],check=True)
            subprocess.run(['tmux','split-window','-h','-t',name,'watch -n 3 crew jobs'],check=True)
            subprocess.run(['tmux','split-window','-v','-t',name+':0.0','watch -n 6 crew fuel'],check=True)
            subprocess.run(['tmux','split-window','-v','-t',name+':0.2','watch -n 5 crew project list'],check=True)
            subprocess.run(['tmux','select-layout','-t',name,'tiled'],check=True)
            subprocess.run(['tmux','set-option','-g','pane-border-status','top'],check=True)
        subprocess.run(['tmux','switch-client' if os.environ.get('TMUX') else 'attach-session','-t',name],check=True)
    elif a.cmd=='facts':
        for k,c in [('Conquer','/opt/ls-conquer/crew.sqlite'),('Factory','/opt/ls-factory/factory.sqlite'),('Arena','/opt/ls-conquer/arena/history.sqlite')]:
            print(k,'present' if Path(c).exists() else 'not found')
        status()
    elif a.cmd=='jobs':
        with connect() as db:
            for x in db.execute('SELECT id,coalesce(project,\'-\'),task,status,coalesce(ms,0),coalesce(detail,\'\') FROM jobs ORDER BY id DESC LIMIT ?', (100 if a.all else 25,)):print(' | '.join(str(y)[:120] for y in x))
    elif a.cmd=='stats':status()
    elif a.cmd=='board': render(); print('BOARD',WEB/'index.html')
    elif a.cmd=='backup': print(handle('backup',None,{}))
    elif a.cmd=='recover':recover(); status()
    elif a.cmd=='test':
        name='smoke';add_project(name); ids=pipeline(name);run(30)
        with connect() as db: states=[r['status'] for r in db.execute('SELECT status FROM jobs WHERE id IN (?,?,?,?) ORDER BY id',ids)]
        assert states==['PASS']*4, states
        assert (WEB/'apps'/name/'index.html').is_file()
        assert route('search tools')=='research'
        assert len(items_rss(b'<rss><channel><item><title>hello</title><guid>123</guid></item></channel></rss>'))==1
        with connect() as db: assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        print('PASS 8 smoke checks: project, route, RSS, pipeline 4 stages, deployed file, SQLite')
    else: ap.print_help()

if __name__=='__main__':
    try: main()
    except (ValueError,sqlite3.Error,OSError) as e:
        print('ERROR:',str(e),file=sys.stderr);sys.exit(1)
