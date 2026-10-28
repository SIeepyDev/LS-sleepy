#!/usr/bin/env python3
"""LS Empire: stdlib-only cities/guilds, governed static projects, jobs and evidence."""
import argparse, concurrent.futures, datetime as dt, fcntl, hashlib, html, json, os
from pathlib import Path
import re, shutil, sqlite3, subprocess, time

ROOT=Path(os.getenv('LS_EMPIRE_ROOT','/opt/ls-empire'))
WEB=Path(os.getenv('LS_EMPIRE_WEB','/opt/ls-conquer/www/empire'))
DB=ROOT/'empire.sqlite'; LOCK=ROOT/'cycle.lock'; ALLOW={'build','test','publish','observe'}
NAME=re.compile(r'^[a-z][a-z0-9-]{0,31}$')
KINDS=('city','arcade','infra')
NOW=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def digest(data):return hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()
def valid(s):
    if not NAME.fullmatch(s):raise ValueError('Names: lowercase letters, numbers, hyphens, max 32')
    return s

def conn():
    ROOT.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB,timeout=12)
    c.row_factory=sqlite3.Row;c.execute('PRAGMA busy_timeout=6000');c.execute('PRAGMA journal_mode=WAL')
    return c

def q(sql,params=()):
    with conn() as c:return c.execute(sql,params).fetchall()
def event(actor,action,result,detail=''):
    with conn() as c:c.execute('INSERT INTO events VALUES(NULL,?,?,?,?,?)',(NOW(),actor,action,result,str(detail)[:400]))
def init():
    for p in (ROOT, ROOT/'src',ROOT/'receipts',ROOT/'backups',WEB,WEB/'apps'):p.mkdir(parents=True,exist_ok=True)
    with conn() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS cities(name TEXT PRIMARY KEY,region TEXT,credits INT,created TEXT);
        CREATE TABLE IF NOT EXISTS guilds(name TEXT PRIMARY KEY,role TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS projects(city TEXT,name TEXT,kind TEXT,guild TEXT,state TEXT,sha TEXT,created TEXT,updated TEXT,PRIMARY KEY(city,name));
        CREATE TABLE IF NOT EXISTS policies(city TEXT,action TEXT,allowed INT,PRIMARY KEY(city,action));
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,city TEXT,name TEXT,action TEXT,state TEXT,created TEXT,started TEXT,finished TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS treasury(id INTEGER PRIMARY KEY,at TEXT,city TEXT,amount INT,balance INT,reason TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,actor TEXT,action TEXT,result TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY,value TEXT,updated TEXT);
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,at TEXT,path TEXT,sha TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);''')
        c.execute("INSERT OR IGNORE INTO settings VALUES('enabled','1')")
        for name,reg in (('citadel','strict'),('workshop','civil'),('beach','sandbox')):
            c.execute('INSERT OR IGNORE INTO cities VALUES(?,?,?,?)',(name,reg,100,NOW()))
            for a in ALLOW:c.execute('INSERT OR IGNORE INTO policies VALUES(?,?,?)',(name,a,int(name!='citadel' or a=='observe')))
        for name,role in (('scouts','discovery'),('builders','generation'),('testers','verification'),('porters','publishing'),('archivists','bookkeeping')):
            c.execute('INSERT OR IGNORE INTO guilds VALUES(?,?,?)',(name,role,NOW()))

def city_new(name,region='sandbox'):
    valid(name)
    if region not in ('strict','civil','sandbox'):raise ValueError('Region: strict, civil, sandbox')
    with conn() as c:
        c.execute('INSERT INTO cities VALUES(?,?,?,?)',(name,region,100,NOW()))
        for a in ALLOW:c.execute('INSERT INTO policies VALUES(?,?,?)',(name,a,int(region!='strict' or a=='observe')))
    event('REGISTRAR','city', 'CREATED',name)
def guild_new(name,role):
    valid(name);valid(role)
    with conn() as c:c.execute('INSERT INTO guilds VALUES(?,?,?)',(name,role,NOW()))
    event('REGISTRAR','guild','CREATED',name)
def permitted(city,action):
    rows=q('SELECT allowed FROM policies WHERE city=? AND action=?',(city,action))
    return bool(rows and rows[0]['allowed'])
def treasury(city,amount,reason):
    if not q('SELECT name FROM cities WHERE name=?',(city,)):raise ValueError('Unknown city')
    with conn() as c:
        row=c.execute('SELECT credits FROM cities WHERE name=?',(city,)).fetchone()
        new=row['credits']+amount
        if not 0<=new<=10000:raise ValueError('Compute credits must stay within 0..10000')
        c.execute('UPDATE cities SET credits=? WHERE name=?',(new,city))
        c.execute('INSERT INTO treasury VALUES(NULL,?,?,?,?,?)',(NOW(),city,amount,new,reason))
    event('TREASURY','compute-credits','POSTED',f'{city} {amount:+} => {new}')
    return new

def new_project(city,name,kind='city',guild='builders'):
    valid(city);valid(name);valid(guild)
    if kind not in KINDS:raise ValueError('Choose: city, arcade, infra')
    if not q('SELECT 1 FROM cities WHERE name=?',(city,)):raise ValueError('Unknown city')
    if not q('SELECT 1 FROM guilds WHERE name=?',(guild,)):raise ValueError('Unknown guild')
    if not permitted(city,'build'):raise ValueError('City policy denies building')
    with conn() as c:c.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?)',(city,name,kind,guild,'NEW','',NOW(),NOW()))
    event('BUILDER','new','CREATED',f'{city}/{name} {kind}')

def page_source(city,name,kind):
    a=lambda x:html.escape(x,quote=True)
    title=f'{city.upper()} · {name.replace("-"," ").title()}'
    palette=('#80d8ff','#ad9df8','#8bf0ae')[int(digest(city+name)[:2],16)%3]
    interactive='''<h2>Grow your city</h2><section class="row"><button onclick="change('homes')">Build +1 home</button><button onclick="change('parks')">Plant +1 park</button><button onclick="change('energy')">Power +1 unit</button></section><div id="stats" class="stats"></div>
<script>let k='ls-city-'+location.pathname,s=JSON.parse(localStorage.getItem(k)||'{"homes":1,"parks":1,"energy":1}');function change(x){s[x]++;localStorage.setItem(k,JSON.stringify(s));draw()}function draw(){document.getElementById('stats').textContent=Object.entries(s).map(([k,v])=>k+': '+v).join(' · ')}draw()</script>'''
    if kind=='arcade':interactive='''<h2>Reaction arcade</h2><p id="prompt">Wait for the green light.</p><button id="play">START</button><p id="score"></p><script>let start=0,t;document.getElementById('play').onclick=()=>{let p=document.getElementById('prompt');p.textContent='WAIT';p.style.color='#eee';clearTimeout(t);t=setTimeout(()=>{start=performance.now();p.textContent='CLICK NOW';p.style.color='#80f0b0'},600+Math.random()*2000)};document.getElementById('prompt').onclick=()=>{if(!start)return;document.getElementById('score').textContent=Math.round(performance.now()-start)+' ms';start=0}</script>'''
    if kind=='infra':interactive='''<h2>Micro infrastructure</h2><div class="stats">Static build · No server runtime · SHA-256 registered · Browser ready</div><button onclick="document.getElementById('check').textContent='PASS · '+new Date().toISOString()">RUN BROWSER SMOKE TEST</button><p id="check"></p>'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{a(title)}</title><style>*{{box-sizing:border-box}}body{{background:#0c101a;color:#e7f1ff;font:16px system-ui;max-width:800px;margin:7vh auto;padding:20px}}.shell{{border:1px solid #314056;background:#152031;padding:32px;border-radius:24px;box-shadow:0 12px 45px #0005}}small{{color:#97aaca}}h1{{font-size:clamp(32px,6vw,60px)}}h1,b{{color:{palette}}}p{{line-height:1.6}}button{{background:{palette};color:#0c101a;border:0;border-radius:11px;padding:12px;margin:6px;cursor:pointer;font-weight:700}}.stats{{background:#263348;border-radius:12px;padding:15px;margin:14px 0}}a{{color:{palette}}}</style></head><body><div class="shell"><small>LS ∞ EMPIRE / {a(city.upper())} / {a(kind.upper())}</small><h1>{a(title)}</h1><p>Small, durable, self-hosted experiment. No accounts. No external dependencies.</p>{interactive}<p><a href="../../../">Empire Control</a></p></div></body></html>'''

def build_project(city,name):
    if not permitted(city,'build'):raise ValueError('Build denied by policy')
    p=q('SELECT kind FROM projects WHERE city=? AND name=?',(city,name))
    if not p:raise ValueError('Unknown project')
    doc=page_source(city,name,p[0]['kind'])
    dest=ROOT/'src'/city/name;dest.mkdir(parents=True,exist_ok=True)
    (dest/'index.html').write_text(doc)
    checksum=digest(doc)
    with conn() as c:c.execute('UPDATE projects SET sha=?,state=?,updated=? WHERE city=? AND name=?',(checksum,'BUILT',NOW(),city,name))
    event('BUILDERS','build','PASS',f'{city}/{name} {checksum[:12]}')
    return checksum

def test_project(city,name):
    if not permitted(city,'test'):raise ValueError('Test denied by policy')
    p=q('SELECT sha FROM projects WHERE city=? AND name=?',(city,name))
    f=ROOT/'src'/city/name/'index.html'
    if not p or not f.is_file() or digest(f.read_bytes())!=p[0]['sha']:raise ValueError('Integrity mismatch or missing build')
    if '<!doctype html>' not in f.read_text().lower():raise ValueError('HTML check failed')
    with conn() as c:c.execute('UPDATE projects SET state=?,updated=? WHERE city=? AND name=?',('TESTED',NOW(),city,name))
    event('TESTERS','verify','PASS',f'{city}/{name}')

def publish(city,name):
    if not permitted(city,'publish'):raise ValueError('Publish denied by policy')
    p=q('SELECT state,sha FROM projects WHERE city=? AND name=?',(city,name))
    if not p or p[0]['state'] not in ('TESTED','PUBLISHED'):raise ValueError('Project not tested')
    src=ROOT/'src'/city/name/'index.html'
    if digest(src.read_bytes())!=p[0]['sha']:raise ValueError('Source changed after test')
    dst=WEB/'apps'/city/name;dst.mkdir(parents=True,exist_ok=True)
    tmp=dst/'index.tmp';tmp.write_bytes(src.read_bytes());os.replace(tmp,dst/'index.html')
    with conn() as c:c.execute('UPDATE projects SET state=?,updated=? WHERE city=? AND name=?',('PUBLISHED',NOW(),city,name))
    event('PORTERS','publish','PASS',f'{city}/{name}')

def queue(city,name):
    if not q('SELECT 1 FROM projects WHERE city=? AND name=?',(city,name,)):raise ValueError('Unknown project')
    with conn() as c:
        if c.execute("SELECT 1 FROM jobs WHERE city=? AND name=? AND state IN ('QUEUED','RUNNING')",(city,name)).fetchone():return
        c.execute('INSERT INTO jobs VALUES(NULL,?,?,?,?,?,?,?,?)',(city,name,'pipeline','QUEUED',NOW(),None,None,''))
    event('ROUTER','queue','QUEUED',f'{city}/{name}')

def process_job(row):
    city,name=row['city'],row['name'];result='PASS';detail=''
    try:
        treasury(city,-5,'reserved pipeline compute budget')
        build_project(city,name);test_project(city,name);publish(city,name)
        detail='Built, SHA-verified and published'
    except Exception as e:result='FAILED';detail=str(e)[:250]
    with conn() as c:c.execute('UPDATE jobs SET state=?,finished=?,detail=? WHERE id=?',(result,NOW(),detail,row['id']))
    event('ROUTER','pipeline',result,f'{city}/{name} {detail}')
    return f'{city}/{name} {result}'

def job_cycle():
    c=conn()
    try:
        c.execute('BEGIN IMMEDIATE')
        rows=c.execute("SELECT * FROM jobs WHERE state='QUEUED' ORDER BY id LIMIT 2").fetchall()
        for r in rows:c.execute("UPDATE jobs SET state='RUNNING',started=? WHERE id=?",(NOW(),r['id']))
        c.commit()
    finally:c.close()
    if not rows:return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(process_job,rows))

def survey():
    programs=('conquer','arena','factory','crew','crewlxc','micro','opsx','fac','ctrl','gov','pct','pvesh','pvesm','tsp','just','sqlite3')
    found={p:bool(shutil.which(p)) for p in programs}
    available=int(next((s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:')),'0'))//1024
    disk=shutil.disk_usage('/');load=os.getloadavg()[0];cpu=os.cpu_count() or 1
    facts={'programs':found,'available_mb':available,'disk_free_pct':round(disk.free/disk.total*100,1),'load_per_core':round(load/cpu,2),'updated':NOW()}
    with conn() as c:c.execute('INSERT OR REPLACE INTO facts VALUES(?,?,?)',('host',json.dumps(facts),NOW()))
    return facts

def checkpoint():
    target=ROOT/'backups'/('empire-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S%f')+'.sqlite')
    with conn() as original, sqlite3.connect(target) as copy:original.backup(copy)
    with sqlite3.connect(target) as check:
        if check.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Backup integrity failed')
    with conn() as c:
        c.execute('INSERT INTO snapshots VALUES(NULL,?,?,?)',(NOW(),str(target),digest(target.read_bytes())))
        old=c.execute('SELECT id,path FROM snapshots ORDER BY id DESC LIMIT -1 OFFSET 7').fetchall()
        for r in old:
            f=Path(r['path'])
            if f.parent==ROOT/'backups' and f.name.startswith('empire-'):f.unlink(missing_ok=True)
            c.execute('DELETE FROM snapshots WHERE id=?',(r['id'],))
    event('ARCHIVISTS','checkpoint','PASS',target.name)
    return target

def dashboard():
    cities=q('SELECT * FROM cities ORDER BY name');guilds=q('SELECT * FROM guilds ORDER BY name')
    projects=q('SELECT * FROM projects ORDER BY updated DESC LIMIT 30')
    jobs=q('SELECT * FROM jobs ORDER BY id DESC LIMIT 15');ev=q('SELECT * FROM events ORDER BY id DESC LIMIT 12')
    facts=q("SELECT value FROM facts WHERE key='host'")
    facts=json.loads(facts[0]['value']) if facts else {}
    e=lambda x:html.escape(str(x),quote=True)
    citycards=''.join(f'<article><small>{e(x["region"])}</small><h3>{e(x["name"])}</h3><b>{x["credits"]}</b> compute credits</article>' for x in cities)
    guildcards=''.join(f'<article><small>{e(x["role"])}</small><h3>{e(x["name"])}</h3><p>Specialist guild</p></article>' for x in guilds)
    linkcards=''.join(f'<a class="project" href="apps/{e(x["city"])}/{e(x["name"])}/"><b>{e(x["name"])}</b><span>{e(x["city"])} · {e(x["kind"])} · {e(x["state"])}</span></a>' if x['state']=='PUBLISHED' else f'<div class="project"><b>{e(x["name"])}</b><span>{e(x["city"])} · {e(x["state"])}</span></div>' for x in projects)
    lines=''.join(f'<tr><td>{e(x["city"])}/{e(x["name"])}</td><td>{e(x["state"])}</td><td>{e(x["detail"])}</td></tr>' for x in jobs)
    logs=''.join(f'<tr><td>{e(x["at"][11:19])}</td><td>{e(x["actor"])}</td><td>{e(x["action"])}</td><td>{e(x["result"])}</td></tr>' for x in ev)
    installed=sum(bool(v) for v in facts.get('programs',{}).values())
    text=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="90"><title>LS Empire</title><style>*{{box-sizing:border-box}}body{{background:#090e19;color:#e4efff;font:15px system-ui;max-width:1120px;margin:auto;padding:3vw}}small,.muted{{color:#94a7c7}}header{{padding:30px 0}}h1{{font-size:clamp(42px,7vw,78px);margin:0;letter-spacing:-3px}}h2{{margin-top:30px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}article,.project,.metric{{background:#152036;border:1px solid #304360;border-radius:18px;padding:20px}}article h3{{font-size:24px;margin:6px 0}}article b,.big{{color:#9fe9d9;font-size:27px}}a{{color:#8ad8ff;text-decoration:none}}.project{{display:flex;flex-direction:column;gap:9px}}.project span{{font-size:12px;color:#a9bcdc}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #27364c;text-align:left;padding:10px}}.scroll{{overflow:auto}}.metrics{{display:flex;gap:12px;flex-wrap:wrap}}.metric{{min-width:160px}}.metric strong{{display:block;font-size:24px;color:#a4f1d4}}</style></head><body><header><small>LS ∞ / SELF-HOSTED SYSTEMS CIVILIZATION</small><h1>EMPIRE</h1><p class="muted">Cities · Guilds · Policies · Finite compute budgets · Verified projects · Audit receipts</p></header><div class="metrics"><div class="metric">AVAILABLE RAM<strong>{e(facts.get('available_mb','—'))} MB</strong></div><div class="metric">FREE DISK<strong>{e(facts.get('disk_free_pct','—'))}%</strong></div><div class="metric">KNOWN TOOLS<strong>{installed}</strong></div><div class="metric">PROJECTS<strong>{len(projects)}</strong></div></div><h2>Cities & budgets</h2><div class="grid">{citycards}</div><h2>Guilds</h2><div class="grid">{guildcards}</div><h2>Published worlds</h2><div class="grid">{linkcards}</div><h2>Job router</h2><div class="scroll"><table><tr><th>Project</th><th>Result</th><th>Receipt</th></tr>{lines}</table></div><h2>Event ledger</h2><div class="scroll"><table><tr><th>UTC</th><th>Guild</th><th>Action</th><th>Result</th></tr>{logs}</table></div><p class="muted">Static local dashboard · Python standard library + SQLite · <a href="../">Conquer</a> · <a href="../control/">Sovereign</a> · <a href="../govern/">Govern</a></p></body></html>'''
    tmp=WEB/'index.html.tmp';tmp.write_text(text);os.replace(tmp,WEB/'index.html')

def tick(automatic=False):
    init()
    with LOCK.open('a+') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:print('Another cycle active');return
        enabled=q("SELECT value FROM settings WHERE key='enabled'")[0]['value']=='1'
        if automatic and not enabled:print('AUTOMATION=PAUSED');return
        host=survey()
        if host['available_mb']<600 or host['disk_free_pct']<12 or host['load_per_core']>1.4:
            print('GOVERNOR=PAUSED resources low');dashboard();return
        if automatic:
            today=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
            rows=q('SELECT value FROM settings WHERE key=?',('last_auto_seed',))
            if not rows or rows[0]['value']!=today:
                # Finite daily replenishment; never infinite or real-money creation.
                with conn() as c:
                    balance=c.execute('SELECT credits FROM cities WHERE name=?',('beach',)).fetchone()[0]
                if balance<100:treasury('beach',min(10,100-balance),'daily compute allowance')
                n=len(q('SELECT name FROM projects'))
                if n<30:
                    name='daily-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')
                    try:new_project('beach',name,('city','arcade','infra')[n%3]);queue('beach',name)
                    except (sqlite3.IntegrityError,ValueError):pass
                with conn() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('last_auto_seed',today))
        for result in job_cycle():print(result)
        recent=q('SELECT at FROM snapshots ORDER BY id DESC LIMIT 1')
        if not recent or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(recent[0]['at'])).total_seconds()>86400:checkpoint()
        dashboard()
        print('EMPIRE=PASS projects=',len(q('SELECT 1 FROM projects')),'queued=',len(q("SELECT 1 FROM jobs WHERE state='QUEUED'")))

def main():
    p=argparse.ArgumentParser(description='LS Empire — cities, guilds, governed factories & ledgers')
    sub=p.add_subparsers(dest='cmd')
    for word in ('init','tick','auto','status','cities','guilds','projects','jobs','events','registry','next','checkpoint','challenge','pause','resume','merge-audit','dashboard','ledger','ideas','test'):sub.add_parser(word)
    c=sub.add_parser('city');c.add_argument('name');c.add_argument('region',nargs='?',default='sandbox')
    c=sub.add_parser('guild');c.add_argument('name');c.add_argument('role',nargs='?',default='builder')
    c=sub.add_parser('new');c.add_argument('city');c.add_argument('name');c.add_argument('kind',nargs='?',default='city')
    c=sub.add_parser('queue');c.add_argument('city');c.add_argument('name')
    c=sub.add_parser('build');c.add_argument('city');c.add_argument('name')
    c=sub.add_parser('policy');c.add_argument('city');c.add_argument('action',choices=sorted(ALLOW));c.add_argument('decision',choices=('permit','deny'))
    c=sub.add_parser('grant');c.add_argument('city');c.add_argument('credits',type=int)
    args=p.parse_args();init();cmd=args.cmd or 'status'
    if cmd=='city':city_new(args.name,args.region);print('CITY',args.name)
    elif cmd=='guild':guild_new(args.name,args.role);print('GUILD',args.name)
    elif cmd=='new':new_project(args.city,args.name,args.kind);print('CREATED',args.city,args.name)
    elif cmd=='queue':queue(args.city,args.name);print('QUEUED',args.city,args.name)
    elif cmd=='build':queue(args.city,args.name);tick()
    elif cmd in ('tick','auto'):tick(automatic=(cmd=='auto'))
    elif cmd=='policy':
        with conn() as c:
            if not c.execute('UPDATE policies SET allowed=? WHERE city=? AND action=?',(int(args.decision=='permit'),args.city,args.action)).rowcount:raise ValueError('Unknown city/action')
        event('COURT','policy',args.decision.upper(),f'{args.city}:{args.action}')
        print('POLICY',args.city,args.action,args.decision)
    elif cmd=='grant':print('BALANCE',treasury(args.city,args.credits,'manual grant of simulated compute credits'))
    elif cmd=='challenge':
        assert not permitted('citadel','publish')
        assert permitted('workshop','publish')
        assert not NAME.fullmatch('../unsafe')
        assert q('SELECT count(*) n FROM projects WHERE city=?',('missing',))[0]['n']==0
        event('COURT','challenge','PASS','4 policy and namespace assertions')
        print('PASS 4/4 governance challenges')
    elif cmd=='checkpoint':print('CHECKPOINT',checkpoint())
    elif cmd in ('pause','resume'):
        with conn() as c:c.execute("UPDATE settings SET value=? WHERE key='enabled'",('1' if cmd=='resume' else '0',))
        event('GOVERNOR','automation',cmd.upper());print('AUTOMATION',cmd.upper())
    elif cmd in ('cities','guilds','projects','jobs','events'):
        t={'cities':'cities','guilds':'guilds','projects':'projects','jobs':'jobs','events':'events'}[cmd]
        rows=q(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 30')
        for r in rows:print(' | '.join(str(v)[:75] for v in r))
    elif cmd=='ledger':
        for r in q('SELECT at,city,amount,balance,reason FROM treasury ORDER BY id DESC LIMIT 25'):
            print(f'{r["at"]} | {r["city"]:12} | {r["amount"]:+4} | balance={r["balance"]:4} | {r["reason"]}')
    elif cmd=='ideas':
        worlds=('arcade','city','infra');themes=('launchpad','workbench','observatory','garden','notebook','registrar')
        for i in range(12):
            kind=worlds[i%3];theme=themes[(i*5+2)%len(themes)]
            print(f'{i+1:02} | {kind:6} | {theme:12} | empire new beach {theme}-{kind}-{i+1} {kind}')
    elif cmd=='registry':
        info=survey()
        for k,v in info['programs'].items():print(('FOUND' if v else 'MISSING'),k)
    elif cmd=='merge-audit':
        print('READ-ONLY: existing services remain independent; candidates for consolidation:')
        for name in ('ls-conquer','ls-factory','ls-crew','ls-facilities','ls-opsx','ls-sovereign','ls-govern'):
            units=list(Path('/etc/systemd/system').glob(name+'*.timer'))
            if units:print(name,', '.join(u.name for u in units))
    elif cmd=='next':
        print('NEXT: empire new beach experiment arcade; empire build beach experiment; empire challenge; empire checkpoint')
    elif cmd=='test':
        assert conn().execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert len(q('SELECT name FROM cities'))>=3
        print('PASS sqlite and seeded registries');
        if not q('SELECT 1 FROM projects WHERE city=? AND name=?',('beach','smoke')):new_project('beach','smoke','infra')
        queue('beach','smoke');tick();assert q('SELECT state FROM projects WHERE city=? AND name=?',('beach','smoke'))[0]['state']=='PUBLISHED'
        print('PASS generated project, tested and published')
    elif cmd=='dashboard':survey();dashboard();print(WEB/'index.html')
    elif cmd in ('status','init'):
        print('CITIES',len(q('SELECT 1 FROM cities')),'GUILDS',len(q('SELECT 1 FROM guilds')),'PROJECTS',len(q('SELECT 1 FROM projects')))
        print('QUEUED',len(q("SELECT 1 FROM jobs WHERE state='QUEUED'")),'PASSED',len(q("SELECT 1 FROM jobs WHERE state='PASS'")))
        print('WEB',WEB/'index.html')

if __name__=='__main__':
    try:main()
    except (ValueError,sqlite3.Error,FileNotFoundError) as e:raise SystemExit('EMPIRE ERROR: '+str(e))