#!/usr/bin/env python3
"""LS Factory of Factories: bounded, reusable, evidence-based micro-automation."""
import argparse
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = Path(os.getenv('LS_FACTORY_ROOT', '/opt/ls-factory'))
DB = ROOT/'factory.sqlite'
WWW = ROOT/'www'
JOBS = ROOT/'workers'
RECEIPTS = ROOT/'receipts'
MAX_DESIGNS = 40
MAX_GENERATION = 3
SOURCES = [
    ('Proxmox Community Scripts releases', 'https://github.com/community-scripts/ProxmoxVE/releases.atom'),
    ('Beszel releases', 'https://github.com/henrygd/beszel/releases.atom'),
    ('Dozzle releases', 'https://github.com/amir20/dozzle/releases.atom'),
]
# Factories create children; children can recursively build only up to generation 3.
CHILDREN = {
    'kernel': ['intake', 'builder', 'verifier', 'archivist'],
    'intake': ['feed', 'token', 'discover'],
    'builder': ['digest', 'compose', 'facts'],
    'verifier': ['integrity', 'facts', 'digest'],
    'archivist': ['search', 'token', 'integrity'],
    'feed': ['token'], 'discover': ['search'], 'compose': ['digest'],
}
FACTORIES = {'kernel','intake','builder','verifier','archivist'}

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def sha(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()
def conn():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    db.execute('PRAGMA foreign_keys=ON')
    return db

def init():
    for d in (ROOT, WWW, JOBS, RECEIPTS): d.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, last_ok TEXT, last_error TEXT);
        CREATE TABLE IF NOT EXISTS fuel(id INTEGER PRIMARY KEY, origin TEXT, guid TEXT, title TEXT, url TEXT, excerpt TEXT, bytes INTEGER, tokens_est INTEGER, score INTEGER DEFAULT 0, seen TEXT, UNIQUE(origin,guid));
        CREATE TABLE IF NOT EXISTS designs(id INTEGER PRIMARY KEY, parent INTEGER, generation INTEGER, kind TEXT, state TEXT, score REAL DEFAULT 0, digest TEXT UNIQUE, created TEXT, tested TEXT, FOREIGN KEY(parent) REFERENCES designs(id));
        CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY, design_id INTEGER, at TEXT, passed INTEGER, duration_ms INTEGER, detail TEXT);
        CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY, at TEXT, new_fuel INTEGER, created INTEGER, passed INTEGER, failed INTEGER, duration_ms INTEGER);
        CREATE INDEX IF NOT EXISTS ix_designs_parent ON designs(parent);
        CREATE INDEX IF NOT EXISTS ix_fuel_seen ON fuel(seen);
        ''')
        for name, url in SOURCES: db.execute('INSERT OR IGNORE INTO sources(name,url) VALUES(?,?)',(name,url))
        db.execute('INSERT OR IGNORE INTO designs(parent,generation,kind,state,digest,created) VALUES(NULL,0,?,?,?,?)',('kernel','PROMOTED',sha('kernel:0'),now()))
        try:
            db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS fuel_fts USING fts5(title,excerpt,content="fuel",content_rowid="id")')
            db.executescript('''CREATE TRIGGER IF NOT EXISTS fuel_ai AFTER INSERT ON fuel BEGIN
              INSERT INTO fuel_fts(rowid,title,excerpt) VALUES(new.id,new.title,new.excerpt); END;
              CREATE TRIGGER IF NOT EXISTS fuel_ad AFTER DELETE ON fuel BEGIN
              INSERT INTO fuel_fts(fuel_fts,rowid,title,excerpt) VALUES('delete',old.id,old.title,old.excerpt); END;''')
        except sqlite3.OperationalError: pass

def read_rss(blob):
    root=ET.fromstring(blob)
    out=[]
    for item in root.iter():
        if item.tag.rsplit('}',1)[-1] not in ('entry','item'): continue
        def child_text(*names):
            for c in item:
                if c.tag.rsplit('}',1)[-1] in names: return ''.join(c.itertext()).strip()
            return ''
        title=child_text('title')[:250]
        guid=child_text('id','guid')
        url=child_text('link')
        if not url:
            for c in item:
                if c.tag.rsplit('}',1)[-1]=='link' and c.attrib.get('href'):
                    url=c.attrib['href']; break
        guid=(guid or url or title)[:500]
        desc=re.sub(r'<[^>]+>',' ',child_text('summary','description','content'))[:1200]
        if title and guid: out.append((guid,title,url[:500],re.sub(r'\s+',' ',desc)))
    return out[:25]

def add_fuel(db, origin, guid, title, url='', excerpt=''):
    title=title.strip()[:250]; excerpt=excerpt.strip()[:1200]
    tokens=max(1, (len(title)+len(excerpt)+3)//4)  # estimate, not model tokens
    score=sum(t in (title+' '+excerpt).lower() for t in ('lxc','sqlite','release','docker','cli','container','proxmox','automation'))*10
    before=db.total_changes
    db.execute('INSERT OR IGNORE INTO fuel(origin,guid,title,url,excerpt,bytes,tokens_est,score,seen) VALUES(?,?,?,?,?,?,?,?,?)',
               (origin,guid,title,url,excerpt,len((title+excerpt).encode()),tokens,score,now()))
    return db.total_changes>before

def intake(db, online=True):
    added=0
    # Existing host state is local fuel: no account or network required.
    for fname in ('/opt/ls-conquer/reports/candidates.tsv','/opt/ls-conquer/reports/system.txt'):
        p=Path(fname)
        if p.is_file():
            try:
                data=p.read_text(errors='replace')[:12000]
                for i,line in enumerate(data.splitlines()[:45]):
                    if not line.strip(): continue
                    added+=add_fuel(db,'local:'+p.name,sha(line),line[:230],excerpt='Existing host catalog')
            except OSError: pass
    if shutil.which('pct'):
        try:
            output=subprocess.run(['pct','list'],capture_output=True,text=True,timeout=5,check=False)
            for row in output.stdout.splitlines()[1:31]:
                if row.strip(): added+=add_fuel(db,'proxmox:lxc',sha(row),row,excerpt='Proxmox LXC inventory')
        except (OSError,subprocess.TimeoutExpired): pass
    if online:
        for src in db.execute('SELECT id,name,url FROM sources ORDER BY coalesce(last_ok, '') ASC,id LIMIT 4').fetchall():
            try:
                req=urllib.request.Request(src['url'], headers={'User-Agent':'LS-Factory/1.0 (RSS collector)'})
                with urllib.request.urlopen(req,timeout=5) as response:
                    blob=response.read(300_000)
                rows=read_rss(blob)
                for guid,title,url,excerpt in rows:
                    added+=add_fuel(db,src['name'],guid,title,url,excerpt)
                db.execute('UPDATE sources SET last_ok=?,last_error=NULL WHERE id=?',(now(),src['id']))
            except Exception as e:
                db.execute('UPDATE sources SET last_error=? WHERE id=?',(str(e)[:180],src['id']))
    return added

def generate(db, limit=4):
    made=[]
    parents=db.execute('SELECT * FROM designs WHERE state="PROMOTED" AND generation<? ORDER BY generation,id',(MAX_GENERATION,)).fetchall()
    for parent in parents:
        for kind in CHILDREN.get(parent['kind'],[]):
            if len(made)>=limit: return made
            if db.execute('SELECT COUNT(*) FROM designs').fetchone()[0]>=MAX_DESIGNS: return made
            gen=parent['generation']+1
            key=sha(f'{parent["id"]}/{gen}/{kind}')
            if db.execute('SELECT id FROM designs WHERE digest=?',(key,)).fetchone(): continue
            cur=db.execute('INSERT INTO designs(parent,generation,kind,state,digest,created) VALUES(?,?,?,?,?,?)',
                           (parent['id'],gen,kind,'CREATED',key,now()))
            design_id=cur.lastrowid
            path=JOBS/f'{design_id:03d}-{kind}.py'
            code='''#!/usr/bin/env python3\n# Generated, pinned LS micro-worker; no untrusted source code execution.\nimport sys\nsys.path.insert(0, %r)\nfrom factory_core import run_child\nif __name__ == "__main__":\n    raise SystemExit(run_child(%d, "--self-test" in sys.argv))\n''' % (str(ROOT),design_id)
            path.write_text(code)
            path.chmod(0o755)
            made.append((design_id,kind,str(path)))
    return made

def run_child(design_id, selftest=False):
    init()
    db=conn()
    design=db.execute('SELECT id,kind,generation FROM designs WHERE id=?',(design_id,)).fetchone()
    if not design: print('UNKNOWN WORKER'); return 2
    k=design['kind']
    try:
        if k in FACTORIES:
            assert design['generation'] <= MAX_GENERATION
            detail=f'factory {k} ready; {len(CHILDREN.get(k,[]))} child recipe types'
        elif k=='facts':
            ram=Path('/proc/meminfo').read_text().splitlines()[0]
            load=Path('/proc/loadavg').read_text().split()[0]
            detail=f'host facts: load1={load}; {ram}'
        elif k=='digest':
            artifact=next((x for d in (Path('/opt/ls-conquer/sorted'), ROOT/'workers') if d.exists() for x in d.rglob('*') if x.is_file() and x.stat().st_size < 250_000),None)
            if artifact: detail=f'file SHA256 {artifact.name}: '+hashlib.sha256(artifact.read_bytes()).hexdigest()
            else: detail='sha256 fixture: '+sha('factory reproducibility')
        elif k=='token':
            fixture='tiny factories learn from tested work'
            assert len(re.findall(r'\w+',fixture))>=5
            recent=db.execute('SELECT title,excerpt FROM fuel ORDER BY id DESC LIMIT 20').fetchall()
            text=' '.join((r['title']+' '+r['excerpt']) for r in recent) or fixture
            detail=f'words={len(text.split())}; estimated tokens={(len(text)+3)//4} (not model-exact)'
        elif k=='integrity':
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            detail='SQLite quick_check=ok'
        elif k=='search':
            count=db.execute('SELECT COUNT(*) FROM fuel').fetchone()[0]
            detail=f'search catalog ready, fuel={count}'
        elif k=='feed':
            assert read_rss(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>test</title><id>x</id></entry></feed>')[0][1]=='test'
            detail='Atom parser fixture PASS'
        elif k=='compose':
            assert sha('x')==hashlib.sha256(b'x').hexdigest()
            items=db.execute('SELECT COUNT(*) FROM fuel WHERE score>0').fetchone()[0]
            detail=f'compose verified; {items} scored input items available'
        elif k=='discover':
            count=db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]
            detail=f'discovery sources={count}'
        else: raise ValueError('unsupported worker kind')
        print(f'PASS {k}: {detail}')
        return 0
    except Exception as e:
        print(f'FAIL {k}: {str(e)[:120]}')
        return 1
    finally: db.close()

def check(db, limit=5):
    rows=db.execute("SELECT id,kind FROM designs WHERE state='CREATED' ORDER BY id LIMIT ?", (limit,)).fetchall()
    passes=fails=0
    for row in rows:
        matches=list(JOBS.glob(f'{row["id"]:03d}-*.py'))
        t=time.monotonic()
        try:
            p=subprocess.run([sys.executable,str(matches[0]),'--self-test'],capture_output=True,text=True,timeout=8,cwd=str(ROOT),check=False)
            passed=(p.returncode==0)
            detail=(p.stdout+p.stderr).strip()[:500]
        except (OSError,IndexError,subprocess.TimeoutExpired) as e:
            passed=False; detail=str(e)[:200]
        duration=int((time.monotonic()-t)*1000)
        db.execute('UPDATE designs SET state=?,tested=?,score=? WHERE id=?',('PROMOTED' if passed else 'FAILED',now(),max(0,100-duration/100) if passed else 0,row['id']))
        db.execute('INSERT INTO receipts(design_id,at,passed,duration_ms,detail) VALUES(?,?,?,?,?)',(row['id'],now(),int(passed),duration,detail))
        db.commit()  # Release the ledger lock before next child executes.
        (RECEIPTS/f'{row["id"]:03d}.json').write_text(json.dumps({'id':row['id'],'kind':row['kind'],'at':now(),'passed':passed,'ms':duration,'detail':detail},indent=2))
        passes+=passed; fails+=not passed
    return passes,fails

def refresh(db, limit=2):
    # Revisits real promoted workers over time. Failures become DEGRADED; no auto-deletion.
    rows=db.execute('''SELECT d.id,d.kind FROM designs d
        WHERE d.state='PROMOTED' AND d.kind NOT IN ('kernel','intake','builder','verifier','archivist')
        ORDER BY (SELECT MAX(at) FROM receipts r WHERE r.design_id=d.id) ASC LIMIT ?''',(limit,)).fetchall()
    for row in rows:
        path=next(iter(JOBS.glob(f'{row["id"]:03d}-*.py')),None)
        if not path: continue
        start=time.monotonic()
        try:
            p=subprocess.run([sys.executable,str(path)],capture_output=True,text=True,timeout=8,check=False)
            good=p.returncode==0; detail=(p.stdout+p.stderr).strip()[:400]
        except (OSError,subprocess.TimeoutExpired) as e:
            good=False; detail=str(e)[:200]
        duration=int((time.monotonic()-start)*1000)
        old=db.execute('SELECT score FROM designs WHERE id=?',(row['id'],)).fetchone()[0]
        score=round(.8*old+.2*(max(0,100-duration/100) if good else 0),1)
        db.execute('UPDATE designs SET state=?,score=?,tested=? WHERE id=?',('PROMOTED' if good else 'DEGRADED',score,now(),row['id']))
        db.execute('INSERT INTO receipts(design_id,at,passed,duration_ms,detail) VALUES(?,?,?,?,?)',(row['id'],now(),int(good),duration,detail))
        db.commit()

def recycle(db):
    # Prevent unattended storage growth. Preserve design history and newest 800 observations.
    db.execute('DELETE FROM receipts WHERE id NOT IN (SELECT id FROM receipts ORDER BY id DESC LIMIT 800)')
    db.execute('DELETE FROM cycles WHERE id NOT IN (SELECT id FROM cycles ORDER BY id DESC LIMIT 720)')
    db.execute('DELETE FROM fuel WHERE id NOT IN (SELECT id FROM fuel ORDER BY id DESC LIMIT 2000)')

def cycle(rounds=1, online=True):
    init()
    with (ROOT/'.cycle.lock').open('a+') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: print('Another cycle already running'); return
        for _ in range(max(1,min(rounds,6))):
            t=time.monotonic()
            with conn() as db:
                added=intake(db,online)
                new=generate(db,4)
                db.commit()  # Generated worker processes need access to SQLite.
                ok,bad=check(db,4)
                refresh(db,2)
                recycle(db)
                elapsed=int((time.monotonic()-t)*1000)
                db.execute('INSERT INTO cycles(at,new_fuel,created,passed,failed,duration_ms) VALUES(?,?,?,?,?,?)',(now(),added,len(new),ok,bad,elapsed))
            print(f'CYCLE fuel+{added} children+{len(new)} verified={ok} failed={bad} {elapsed}ms')
            online=False   # only fetch online once per invocation
        render()

def metrics(db):
    return {k:db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for k,t in [('fuel','fuel'),('factories','designs'),('runs','cycles'),('receipts','receipts')]}

def render():
    init()
    with conn() as db:
        counts=metrics(db)
        passed=db.execute('SELECT COUNT(*) FROM designs WHERE state="PROMOTED"').fetchone()[0]
        broken=db.execute('SELECT COUNT(*) FROM designs WHERE state="FAILED"').fetchone()[0]
        rows=db.execute('SELECT id,parent,generation,kind,state,round(score,1) score FROM designs ORDER BY generation,id LIMIT 40').fetchall()
        fuel=db.execute('SELECT title,origin,url,score FROM fuel ORDER BY score DESC,seen DESC LIMIT 16').fetchall()
        cycles=db.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT 7').fetchall()
        errs=db.execute('SELECT name,last_error FROM sources WHERE last_error IS NOT NULL').fetchall()
    esc=lambda s:html.escape(str(s),quote=True)
    tiles=''.join(f'<div class="tile"><small>{name}</small><strong>{value}</strong></div>' for name,value in [('Collected fuel',counts['fuel']),('Factory/worker nodes',counts['factories']),('Verified nodes',passed),('Failed nodes',broken),('Cycle receipts',counts['runs']),('Test receipts',counts['receipts'])])
    tree=''.join(f'<tr><td>{r["id"]}</td><td>{"↳ "*r["generation"]}{esc(r["kind"])}</td><td>{r["generation"]}</td><td>{esc(r["state"])}</td><td>{r["score"]}</td></tr>' for r in rows)
    news=''.join(f'<li><span>{esc(f["origin"])}</span> <a href="{esc(f["url"])}" rel="noopener noreferrer">{esc(f["title"])}</a><small> score {f["score"]}</small></li>' if str(f['url']).startswith('https://') else f'<li><span>{esc(f["origin"])}</span> {esc(f["title"])}</li>' for f in fuel)
    history=''.join(f'<tr><td>{esc(r["at"])}</td><td>+{r["new_fuel"]}</td><td>+{r["created"]}</td><td>{r["passed"]}</td><td>{r["failed"]}</td><td>{r["duration_ms"]}ms</td></tr>' for r in cycles)
    warnings=''.join(f'<li>{esc(x["name"])}: {esc(x["last_error"])}</li>' for x in errs)
    page=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="45"><title>LS / Factory Grid</title><style>
    *{{box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:#0a0f17;color:#e8eff9;margin:0;padding:3vw}}main{{max-width:1200px;margin:auto}}h1{{font-size:clamp(30px,4vw,55px);margin:0}}h2{{font-size:19px}}p,small{{color:#9bacc1}}.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:20px 0}}.tile,.panel{{background:#151e2b;border:1px solid #304052;border-radius:15px;padding:18px}}.tile strong{{display:block;font-size:32px;color:#8ef2bc}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:8px;border-bottom:1px solid #273446;text-align:left}}th{{color:#91a7c0}}li{{margin:8px 0;overflow-wrap:anywhere}}li span{{color:#9dd5ff}}a{{color:#8ed5f7}}code{{color:#a9f2bf}}.stamp{{font-size:12px;color:#94abc1;margin-top:10px}}.chips{{display:flex;gap:9px;flex-wrap:wrap}}.chip{{padding:6px 12px;border:1px solid #405267;border-radius:20px;color:#a3defb}}</style></head><body><main><p>LS ∞ / NON-AI SELF-IMPROVING AUTOMATION</p><h1>FACTORY GRID</h1><p>Discover → Design → Spawn → Test → Score → Archive → Repeat</p><div class="chips"><span class="chip">Depth capped at 3</span><span class="chip">40 node ceiling</span><span class="chip">4 tests/cycle</span><span class="chip">Offline-capable</span></div><div class="tiles">{tiles}</div><div class="grid"><section class="panel"><h2>Factory lineage</h2><table><thead><tr><th>ID</th><th>Node</th><th>Gen</th><th>State</th><th>Score</th></tr></thead><tbody>{tree}</tbody></table></section><section class="panel"><h2>Intake / discovered fuel</h2><ul>{news}</ul></section><section class="panel"><h2>Cycle receipts</h2><table><thead><tr><th>UTC</th><th>Fuel</th><th>Built</th><th>Pass</th><th>Fail</th><th>Time</th></tr></thead><tbody>{history}</tbody></table></section><section class="panel"><h2>Control / commands</h2><p><code>factory</code> — overview<br><code>factory cycle 4</code> — spin 4 rounds<br><code>factory sources</code> — collectors<br><code>factory search sqlite</code> — fuel search<br><code>factory tree</code> — lineage<br><code>factory token FILE</code> — estimates<br><code>factory snapshot</code> — DB backup<br><code>factory test</code> — self-test</p><h2>Source warnings</h2><ul>{warnings or '<li>None recorded</li>'}</ul></section></div><p class="stamp">Rendered {esc(now())}. Read-only LAN dashboard; no external commands from feeds ever run automatically.</p></main></body></html>'''
    temp=WWW/'index.html.tmp'; temp.write_text(page); temp.replace(WWW/'index.html')

def snapshot():
    init()
    folder=ROOT/'snapshots'; folder.mkdir(exist_ok=True)
    path=folder/f'factory-{dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.sqlite'
    source=conn(); target=sqlite3.connect(path)
    try: source.backup(target)
    finally: target.close(); source.close()
    print(f'SNAPSHOT {path.name} sha256={hashlib.sha256(path.read_bytes()).hexdigest()}')
    for old in sorted(folder.glob('factory-*.sqlite'))[:-14]: old.unlink()

def status():
    init()
    with conn() as db:
        counts=metrics(db)
        p=db.execute('SELECT COUNT(*) FROM designs WHERE state="PROMOTED"').fetchone()[0]
        last=db.execute('SELECT at,created,passed,failed,duration_ms FROM cycles ORDER BY id DESC LIMIT 1').fetchone()
        print('LS FACTORY /',now())
        print('Fuel:',counts['fuel'],'Nodes:',counts['factories'],'Verified:',p,'Cycles:',counts['runs'])
        if last: print('Latest:',dict(last))
    print('Database:',DB,'| Dashboard:',WWW/'index.html')

def selftest():
    init(); failures=0
    checks=[('rss',lambda:len(read_rss(b'<rss><channel><item><title>hello</title><guid>1</guid></item></channel></rss>'))==1),
            ('sha256',lambda:sha('ok')==hashlib.sha256(b'ok').hexdigest()),
            ('SQLite',lambda:conn().execute('PRAGMA quick_check').fetchone()[0]=='ok'),
            ('generation',lambda:MAX_GENERATION==3 and MAX_DESIGNS==40),
            ('source count',lambda:conn().execute('SELECT COUNT(*) FROM sources').fetchone()[0]>=3),
            ('dashboard',lambda: bool(render() is None and (WWW/'index.html').exists()))]
    for label,fn in checks:
        try: yes=fn()
        except Exception: yes=False
        print(('PASS' if yes else 'FAIL'),label)
        failures+=not yes
    return failures

def main():
    ap=argparse.ArgumentParser(description='LS micro Factory of Factories')
    ap.add_argument('command',nargs='?',default='status')
    ap.add_argument('arg',nargs='?',default='')
    args=ap.parse_args()
    init()
    c=args.command
    if c in ('status','facts'): status()
    elif c=='cycle': cycle(int(args.arg) if args.arg.isdigit() else 1)
    elif c=='offline': cycle(int(args.arg) if args.arg.isdigit() else 1,online=False)
    elif c=='tree':
        with conn() as db:
            for r in db.execute('SELECT id,kind,generation,state FROM designs ORDER BY generation,id'):
                print(f'{r["id"]:>3} '+('  '*r['generation'])+f'{r["kind"]:14} {r["state"]}')
    elif c=='add':
        u=args.arg.strip()
        parsed=urllib.parse.urlparse(u)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
            print('Usage: factory add https://public-rss-url'); sys.exit(2)
        if parsed.hostname in ('localhost',) or parsed.hostname.endswith('.local'):
            print('Only public HTTPS RSS endpoints allowed'); sys.exit(2)
        with conn() as db:
            if db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]>=12:
                print('Maximum 12 sources'); sys.exit(2)
            db.execute('INSERT OR IGNORE INTO sources(name,url) VALUES(?,?)',(parsed.hostname+' / '+sha(u)[:8],u))
        print('SOURCE ADDED',u)
    elif c=='ingest':
        p=Path(args.arg)
        if not p.is_file() or p.stat().st_size>1024*1024:
            print('Usage: factory ingest TEXT_FILE (up to 1 MB)'); sys.exit(2)
        with conn() as db:
            added=0
            for line in p.read_text(errors='replace').splitlines()[:300]:
                line=line.strip()
                if line: added+=add_fuel(db,'file:'+p.name,sha(line),line[:250],excerpt=line[250:])
        print('LINES INDEXED',added)
    elif c=='ideas':
        print('COLLISIONS / REUSABLE RECIPES')
        for parent,children in CHILDREN.items():
            print(parent+' -> '+', '.join(children))
    elif c=='workers':
        with conn() as db:
            for r in db.execute('SELECT id,kind,state,round(score,1) AS score FROM designs ORDER BY id'):
                print(r['id'],r['kind'],r['state'],r['score'])
    elif c=='sources':
        with conn() as db:
            for r in db.execute('SELECT name,last_ok,last_error,url FROM sources'):
                print(r['name'],r['last_ok'] or 'not fetched',r['last_error'] or '',r['url'])
    elif c=='search':
        term=args.arg.strip()
        if not term: print('Usage: factory search TERM'); return
        with conn() as db:
            for r in db.execute('SELECT title,origin FROM fuel WHERE title LIKE ? OR excerpt LIKE ? LIMIT 20',('%'+term+'%','%'+term+'%')):
                print(r['origin'],':',r['title'])
    elif c=='tokens':
        p=Path(args.arg)
        if not p.is_file(): print('Usage: factory tokens FILE'); return
        s=p.read_text(errors='replace')
        print('Bytes:',p.stat().st_size,'Words:',len(re.findall(r'\w+',s)),'Estimated tokens:',(len(s)+3)//4,'(approximate, not model-exact)')
    elif c=='snapshot': snapshot()
    elif c=='test': sys.exit(bool(selftest()))
    elif c=='render': render()
    elif c=='receipts':
        with conn() as db:
            for r in db.execute('SELECT design_id,passed,duration_ms,detail FROM receipts ORDER BY id DESC LIMIT 20'):
                print(r['design_id'],'PASS' if r['passed'] else 'FAIL',f'{r["duration_ms"]}ms',r['detail'])
    else: print('factory {status|cycle N|offline N|ideas|tree|workers|sources|add RSS_URL|ingest FILE|search TERM|tokens FILE|snapshot|receipts|test}')

if __name__=='__main__': main()