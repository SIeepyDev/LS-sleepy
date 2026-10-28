#!/usr/bin/env python3
"""LS Atlas — evidence-based maps, reusable atoms, staged games and watch signals.
Stdlib-only, no downloaded code execution, no modification of legacy assets.
"""
import argparse, datetime as dt, hashlib, html, json, os, re, shutil, sqlite3, sys, fcntl
from pathlib import Path

ROOT=Path(os.getenv('LS_ATLAS_ROOT','/opt/ls-atlas')).resolve()
WEB=Path(os.getenv('LS_ATLAS_WEB','/opt/ls-conquer/www/atlas')).resolve()
DB=ROOT/'atlas.sqlite'
LOCK=ROOT/'cycle.lock'
STAMP=lambda:dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
SLUG=re.compile(r'^[a-z][a-z0-9-]{0,31}$')
STAGES=('PLACEHOLDER','BUILT','HARDENED','POLISHED','VERIFIED','SHIPPED','WATCHED')
QUALITY_CAP=2
FILES_CAP=100
MAX_BYTES=300_000
ATOMS={
 'identity':('v1','Deterministic slug + namespacing','no path traversal, stable URL'),
 'ledger':('v1','SQLite WAL events and evidence','append-only events, backed up'),
 'hash':('v1','SHA-256 content fingerprint','publish exactly verified bytes'),
 'tokens':('v1','CSS design token contract','reused palette, spacing, focus'),
 'gate':('v1','Static quality and accessibility checks','no promote on failed checks'),
 'queue':('v1','Single-owner bounded worker cycle','locks, no runaway forks'),
 'map':('v1','Generated stage and dependency maps','source-state provenance'),
 'signal':('v1','Local alert and terminal bell','no unsolicited external sends'),
}
TERMS={
 'atom':('architecture','literal','A small reusable versioned building block'),
 'token':('design','literal','Named design decision: color, space, radius, focus'),
 'contract':('architecture','literal','Stable behavior and validation rule for an atom'),
 'stage':('delivery','literal','Evidence-gated lifecycle state'),
 'placeholder':('delivery','literal','Recorded intent not yet implemented'),
 'verified':('evidence','literal','A scoped check ran and passed; not general perfection'),
 'ship':('delivery','literal','Publish checked static files to own output namespace'),
 'watcher':('operations','literal','Fingerprint monitor generating change events'),
 'signal':('operations','literal','Dated event with severity and optional terminal bell'),
 'recycle':('operations','literal','Retain knowledge; reclaim only explicit Atlas-owned drafts'),
 'guild':('organization','metaphor','Specialized work lane, not an independent agent'),
 'city':('organization','metaphor','A namespace grouping projects'),
 'universe':('organization','metaphor','High-level thematic map of systems'),
 'impossible':('challenge','aspirational','Stretch goal, never marked achieved without evidence'),
 'fortress':('quality','metaphor','Hardening through repeatable break-tests'),
 'bell':('operations','literal','Terminal beep and logged notification'),
 'matrix':('planning','literal','Projects crossed with stages, tests and dependencies'),
 'backend':('architecture','literal','Persistence, routers, policies, and filesystem'),
 'frontend':('architecture','literal','HTML, CSS, JS browser experience'),
}
CHALLENGES={
 'foundations':('Survive 100 destructive-input attempts',('doctype','viewport','css','size','sha')),
 'accessibility':('One-hand keyboard + no-mouse navigation',('landmarks','keyboard','focus','reduced-motion')),
 'offline':('Entire site usable offline without CDNs',('local','links','size')),
 'durability':('Rebuild identical files 1,000 times without drift',('sha','repeat','snapshot')),
 'moonshot':('Ship a game under 16 KB with offline play, zero dependencies, accessibility, durable saves and browser verification',('size16','offline','keyboard','save','browser')),
}
# Explicit roots only; imported artifacts are always read-only and never promoted as verified.
IMPORTS=(
 ('Empire','/opt/ls-conquer/www/empire/apps'),
 ('Crew','/opt/ls-conquer/www/crew/apps'),
 ('Microverse','/opt/ls-conquer/www/microverse/projects'),
 ('Facilities','/opt/ls-conquer/www/facilities/apps'),
 ('OpsX','/opt/ls-conquer/www/opsx/projects'),
 ('Factory','/opt/ls-factory/www'),
)
CSS='''/* ATLAS DESIGN TOKENS v1 — copyable stable public contract */
:root{--bg:#0b1020;--panel:#16213a;--panel2:#20304a;--ink:#ecf5ff;--muted:#a8b9d0;--accent:#84e1cd;--warning:#ffcd87;--danger:#ff879d;--focus:#ffed90;--radius:16px;--space:16px;--shadow:0 16px 45px #02051080;--font:system-ui,-apple-system,sans-serif}
*,*::before,*::after{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--font)}button,a{touch-action:manipulation}button{cursor:pointer;background:var(--accent);color:#081221;font-weight:800;border:0;border-radius:10px;padding:12px 16px}button:focus-visible,a:focus-visible{outline:3px solid var(--focus);outline-offset:3px}button:disabled{opacity:.5}a{color:var(--accent)}.wrap{width:min(940px,94vw);margin:5vh auto}.panel{background:var(--panel);border:1px solid #344b6d;border-radius:var(--radius);padding:clamp(18px,4vw,40px);box-shadow:var(--shadow)}h1{font-size:clamp(2rem,6vw,4rem);line-height:1.1;margin:.4em 0}.muted{color:var(--muted)}.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.tile{border:1px solid #38516d;background:var(--panel2);padding:14px;border-radius:12px}.score{font-size:2rem;font-weight:800;color:var(--accent)}.status{min-height:2em}small{color:var(--muted)}@media(max-width:550px){.wrap{margin:12px auto}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
'''

class C(sqlite3.Connection):
 def __exit__(self,*a):
  try:return super().__exit__(*a)
  finally:self.close()
def connect():
 ROOT.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DB,timeout=10,factory=C);c.row_factory=sqlite3.Row;c.execute('PRAGMA busy_timeout=6000');c.execute('PRAGMA journal_mode=WAL');return c
def query(sql,params=()):
 with connect() as c:return c.execute(sql,params).fetchall()
def setup():
 for p in (ROOT,ROOT/'src',ROOT/'releases',ROOT/'backups',ROOT/'docs',WEB,WEB/'games'):p.mkdir(parents=True,exist_ok=True)
 with connect() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY,kind TEXT,origin TEXT,location TEXT,stage TEXT,score INT DEFAULT 0,sha TEXT,observed TEXT,created TEXT,updated TEXT);
  CREATE TABLE IF NOT EXISTS atoms(name TEXT PRIMARY KEY,version TEXT,definition TEXT,contract TEXT,sha TEXT);
  CREATE TABLE IF NOT EXISTS terms(name TEXT PRIMARY KEY,category TEXT,semantics TEXT,definition TEXT);
  CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY,at TEXT,project TEXT,gate TEXT,passed INT,detail TEXT);
  CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,target TEXT,severity TEXT,detail TEXT);
  CREATE TABLE IF NOT EXISTS challenges(project TEXT,level TEXT,goal TEXT,state TEXT,updated TEXT,PRIMARY KEY(project,level));
  CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
  CREATE TABLE IF NOT EXISTS snapshots(at TEXT PRIMARY KEY,path TEXT,sha TEXT);
  ''')
  for k,(v,d,contract) in ATOMS.items():c.execute('INSERT OR IGNORE INTO atoms VALUES(?,?,?,?,?)',(k,v,d,contract,hashit(k+v+contract)))
  for k,(category,semantics,definition) in TERMS.items():c.execute('INSERT OR IGNORE INTO terms VALUES(?,?,?,?)',(k,category,semantics,definition))
  c.execute("INSERT OR IGNORE INTO settings VALUES('enabled','1')")
 (ROOT/'tokens.css').write_text(CSS)

def hashit(s):return hashlib.sha256(s.encode() if isinstance(s,str) else s).hexdigest()
def log(kind,target,severity='INFO',detail=''):
 with connect() as c:c.execute('INSERT INTO events VALUES(NULL,?,?,?,?,?)',(STAMP(),kind,target,severity,str(detail)[:600]))
 if severity in ('WARN','FAIL'): (ROOT/'alerts.log').open('a').write(f'{STAMP()} {severity} {kind} {target}: {detail[:180]}\n')
def valid(x):
 if not SLUG.fullmatch(x):raise ValueError('Name must be 1–32 lowercase letters, numbers and hyphens')
 return x

def source(name):return ROOT/'src'/name
def read_owned(name):
 p=source(name)
 if not p.is_dir():raise ValueError('Unknown own source directory')
 return p

def register(name,kind='arcade'):
 valid(name)
 if kind not in ('arcade','builder'):raise ValueError('Kinds: arcade, builder')
 with connect() as c:
  count=c.execute("SELECT count(*) FROM projects WHERE origin='Atlas' AND stage IN ('PLACEHOLDER','BUILT','HARDENED')").fetchone()[0]
  if count>=QUALITY_CAP:raise ValueError('Low-quality cap reached (2). Upgrade existing prototypes first.')
  if c.execute('SELECT 1 FROM projects WHERE name=?',(name,)).fetchone():raise ValueError('Project already exists')
  c.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,?,?,?)',(name,kind,'Atlas',str(source(name)),'PLACEHOLDER',0,'','',STAMP(),STAMP()))
 p=source(name);p.mkdir(parents=True,exist_ok=True)
 (p/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Pending build</title><h1>Placeholder: '+html.escape(name)+'</h1>\n')
 log('PROJECT',name,'INFO','Created placeholder; no working-game claim')
 print('PLACEHOLDER',name)

# Each generated game uses the same versioned design tokens and battle-tested minimal helpers.
JS='''/* ATLAS game core — offline/local/no external libraries */
(()=>{'use strict';
const $=id=>document.getElementById(id), key='ls-atlas-score-'+location.pathname;
let score=0, best=0, rounds=0, deadline=0, lock=false, timer=null;
try{best=Math.max(0,Number(localStorage.getItem(key))||0)}catch(_){best=0}
const stat=(message)=>{ $('status').textContent=message; $('score').textContent=String(score); $('best').textContent=String(best) };
function reset(){score=0;rounds=0;deadline=0;lock=false;clearTimeout(timer);$('target').disabled=false;stat('Ready — tap the target or press Space');}
function hit(){if(lock)return;lock=true;score++;rounds++;if(score>best){best=score;try{localStorage.setItem(key,String(best))}catch(_){}};
stat('Hit '+rounds+' · next target');$('target').disabled=true;
timer=setTimeout(()=>{lock=false;$('target').disabled=false;stat('Ready — aim for another hit')},170);
}
$('target').addEventListener('click',hit);$('reset').addEventListener('click',reset);
document.addEventListener('keydown',event=>{if(event.code==='Space'&&event.target.tagName!=='BUTTON'){event.preventDefault();hit()}});
reset();
})();
'''
BUILDER_JS='''/* ATLAS city builder — small, deterministic, offline simulation */
(()=>{'use strict';const $=x=>document.getElementById(x),key='ls-atlas-city-'+location.pathname;
let s={homes:1,parks:1,power:1};try{const x=JSON.parse(localStorage.getItem(key)||'{}');for(const k of Object.keys(s)){if(Number.isInteger(x[k])&&x[k]>=0&&x[k]<=999)s[k]=x[k]}}catch(_){}
function draw(){for(const k of Object.keys(s))$(k).textContent=String(s[k]);$('status').textContent='Population '+(s.homes*4)+' · green rating '+(s.parks*2)}
function change(k){if(s[k]>=999)return;s[k]++;try{localStorage.setItem(key,JSON.stringify(s))}catch(_){}draw()}
for(const k of Object.keys(s))$('add-'+k).addEventListener('click',()=>change(k));
$('reset').addEventListener('click',()=>{s={homes:1,parks:1,power:1};try{localStorage.removeItem(key)}catch(_){}draw()});draw();
})();
'''

def make_page(name,kind,stage):
 title=html.escape(name.replace('-',' ').title())
 game=('''<p class="muted">Tiny offline arcade. Challenge: responsive, keyboard playable, durable progress.</p><div class="grid"><div class="tile">Score<div id="score" class="score">0</div></div><div class="tile">Personal best<div id="best" class="score">0</div></div></div><p class="status" id="status" role="status" aria-live="polite">Ready</p><div class="row"><button id="target" type="button">HIT TARGET</button><button id="reset" type="button">Reset</button></div>''' if kind=='arcade' else '''<p class="muted">Tiny offline city builder. Challenge: expand without breaking state or accessibility.</p><div class="grid">'''+''.join('<div class="tile">'+k.title()+'<div id="'+k+'" class="score">1</div><button id="add-'+k+'" type="button">Add '+k+'</button></div>' for k in ('homes','parks','power'))+'''</div><p class="status" id="status" role="status" aria-live="polite">Ready</p><button id="reset" type="button">Reset city</button>''')
 extra = ('<p class="muted">Keyboard navigation, safe persistent saves and reduced-motion preferences are supported.</p>' if stage in ('HARDENED','POLISHED') else '')
 polish = ('<div class="tile"><b>Level: Fortress</b><p>Reusable design tokens, accessible score feedback, offline-first architecture and verified content hashes.</p></div>' if stage=='POLISHED' else '')
 return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark"><title>ATLAS / {title}</title><link rel="stylesheet" href="tokens.css"><style>header{{margin-bottom:24px}}footer{{margin-top:24px}}.masthead{{letter-spacing:.16em;text-transform:uppercase;color:var(--accent);font-size:.78rem}}</style></head><body><main class="wrap"><article class="panel"><header><span class="masthead">LS Atlas / {kind} / {stage.lower()}</span><h1>{title}</h1></header>{game}{extra}{polish}<footer><small>Locally generated · No remote scripts · Versioned tokens · <a href="../../">Atlas map</a></small></footer></article></main><script src="game.js" defer></script></body></html>'''

def files(name,kind,stage):
 html_=make_page(name,kind,stage)
 return {'index.html':html_.encode(),'tokens.css':CSS.encode(),'game.js':(JS if kind=='arcade' else BUILDER_JS).encode()}
def write_release(name,kind,stage):
 dst=source(name);dst.mkdir(parents=True,exist_ok=True)
 expected=files(name,kind,stage)
 # Versioned release snapshot to keep prior revisions inspectable.
 existing=[p for p in dst.glob('*') if p.is_file()]
 if existing:
  rev=ROOT/'releases'/name/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
  rev.mkdir(parents=True,exist_ok=True)
  for p in existing:
   if p.name in ('index.html','tokens.css','game.js'):shutil.copy2(p,rev/p.name)
 for f,content in expected.items():
  tmp=dst/(f+'.tmp');tmp.write_bytes(content);os.replace(tmp,dst/f)
 return expected

def verify(name,stage=None):
 p=query('SELECT * FROM projects WHERE name=?',(name,))
 if not p:raise ValueError('Unknown project')
 p=p[0]
 if p['origin']!='Atlas':raise ValueError('Imported projects are observe-only')
 stage=stage or p['stage']
 expected=files(name,p['kind'],stage)
 dest=source(name)
 checks={}
 for filename,data in expected.items():
  file=dest/filename
  checks['sha '+filename]=file.is_file() and file.read_bytes()==data
 page=expected['index.html'].decode();script=expected['game.js'].decode()
 checks.update({'doctype':'<!doctype html>' in page.lower(),'viewport':'name="viewport"' in page,
  'landmarks':'<main ' in page and 'role="status"' in page,'keyboard':('keydown' in script and 'addEventListener' in script) or (p['kind']=='builder' and '<button ' in page and 'addEventListener' in script),
  'focus':':focus-visible' in CSS,'reduced-motion':'prefers-reduced-motion' in CSS,
  'offline':'https://' not in page and 'http://' not in page and 'fetch(' not in script,
  'save':'localStorage' in script and 'catch(' in script,'size16':sum(map(len,expected.values()))<=16*1024,
  'escape':html.escape(name.replace('-', ' ').title()) in page,'local-path':'../' not in str(dest.relative_to(ROOT)),
  'size':sum(map(len,expected.values()))<MAX_BYTES,
  'tokens':all('--'+t in CSS for t in ('bg','panel','ink','accent','focus')),
  'repeat':files(name,p['kind'],stage)==expected})
 # Browser runtime cannot be certified by static-source checks alone.
 checks['browser']=False
 with connect() as c:
  for gate,passed in checks.items():c.execute('INSERT INTO checks VALUES(NULL,?,?,?,?,?)',(STAMP(),name,gate,int(passed),'source gate; browser requires manual runtime check' if gate=='browser' else 'deterministic source gate'))
 earned=sum(checks.values());possible=len(checks)-1
 score=round(earned/max(1,possible)*90)  # 90-point ceiling pending browser runtime evidence
 with connect() as c:c.execute('UPDATE projects SET score=?,updated=? WHERE name=?',(score,STAMP(),name))
 return checks,score

def upgrade(name):
 record=query('SELECT * FROM projects WHERE name=?',(name,))
 if not record:raise ValueError('Unknown project')
 r=record[0]
 if r['origin']!='Atlas':raise ValueError('Legacy artifact: read-only, never auto-upgrade')
 state=r['stage']
 if state=='WATCHED':print('ALREADY WATCHED',name);return
 if state=='PLACEHOLDER':
  write_release(name,r['kind'],'BUILT');target='BUILT'
 elif state=='BUILT':
  before=verify(name,'BUILT')[0]
  if not all(v for k,v in before.items() if k!='browser'):raise ValueError('Build tests failed; not promoted')
  write_release(name,r['kind'],'HARDENED');target='HARDENED'
 elif state=='HARDENED':
  before=verify(name,'HARDENED')[0]
  if not all(v for k,v in before.items() if k!='browser'):raise ValueError('Hardening gate failed')
  write_release(name,r['kind'],'POLISHED');target='POLISHED'
 elif state=='POLISHED':
  checks,score=verify(name,'POLISHED')
  if not all(v for k,v in checks.items() if k!='browser'):raise ValueError('Polish checks failed; cannot verify')
  target='VERIFIED' # source-level checks only
 elif state=='VERIFIED':
  checks,score=verify(name,'POLISHED')
  if not all(v for k,v in checks.items() if k!='browser'):raise ValueError('Source drift: deployment refused')
  dst=WEB/'games'/name;dst.mkdir(parents=True,exist_ok=True)
  for fname,blob in files(name,r['kind'],'POLISHED').items():
   tmp=dst/(fname+'.tmp');tmp.write_bytes(blob);os.replace(tmp,dst/fname)
  target='SHIPPED'
 else:target='WATCHED'
 digest=hashit(b''.join(files(name,r['kind'],'POLISHED' if target in ('VERIFIED','SHIPPED','WATCHED') else target).values()))
 with connect() as c:c.execute('UPDATE projects SET stage=?,sha=?,updated=? WHERE name=?',(target,digest,STAMP(),name))
 log('PROMOTION',name,'PASS',f'{state} → {target}; source-level gates enforced')
 print(name,state,'->',target)

def scan():
 found=0;changed=0
 for origin,root in IMPORTS:
  base=Path(root)
  if not base.is_dir():continue
  # index.html bounded under explicit origins; never traverse symlinks.
  for f in base.glob('**/index.html'):
   if found>=FILES_CAP:break
   if f.is_symlink() or not f.is_file() or any(x.is_symlink() for x in f.parents if x!=base):continue
   try:
    if not f.resolve().is_relative_to(base.resolve()) or f.stat().st_size>MAX_BYTES:continue
    relative=f.relative_to(base).parent.as_posix()
    key='ext-'+hashit(origin+'/'+relative)[:20]
    raw=f.read_bytes();digest=hashit(raw)
    with connect() as c:
     old=c.execute('SELECT sha FROM projects WHERE name=?',(key,)).fetchone()
     c.execute('INSERT INTO projects(name,kind,origin,location,stage,score,sha,observed,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET sha=excluded.sha,observed=excluded.observed,updated=excluded.updated',(key,'import',origin,str(f),'OBSERVED',0,digest,STAMP(),STAMP(),STAMP()))
    if old and old['sha']!=digest:changed+=1;log('WATCH',key,'WARN',f'Imported source changed: {origin}/{relative}')
    found+=1
   except (OSError,ValueError):continue
 return found,changed

def watch():
 changes=[]
 for r in query("SELECT name,sha,stage FROM projects WHERE origin='Atlas' AND stage IN ('SHIPPED','WATCHED')"):
  p=WEB/'games'/r['name']
  required=('index.html','tokens.css','game.js')
  missing=not p.is_dir() or any(not (p/f).is_file() for f in required)
  sha=hashit(b''.join((p/f).read_bytes() for f in required)) if not missing else 'MISSING'
  if sha!=r['sha']:
   changes.append(r['name'])
   signal_key='tamper:'+r['name']
   old=query('SELECT value FROM settings WHERE key=?',(signal_key,))
   if not old or old[0]['value']!=sha:
    log('TAMPER',r['name'],'FAIL','Published bytes changed or missing; inspect before republishing')
    with connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(signal_key,sha))
  elif r['stage']=='SHIPPED':
   with connect() as c:c.execute("UPDATE projects SET stage='WATCHED',updated=? WHERE name=?",(STAMP(),r['name']))
  else:pass
 print('WATCH changes=',len(changes),'names=',','.join(changes))
 return changes

def challenge(name,kind='moonshot'):
 if kind not in CHALLENGES:raise ValueError('Challenge kinds: '+', '.join(CHALLENGES))
 if not query('SELECT 1 FROM projects WHERE name=?',(name,)):raise ValueError('Unknown project')
 title,gates=CHALLENGES[kind]
 with connect() as c:c.execute('INSERT OR REPLACE INTO challenges VALUES(?,?,?,?,?)',(name,kind,title,'OPEN',STAMP()))
 log('CHALLENGE',name,'INFO',kind+': '+title)
 print('CHALLENGE',kind,title,'GATES',','.join(gates))

def checkpoint():
 dest=ROOT/'backups'/('atlas-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
 with connect() as c, sqlite3.connect(dest) as backup:c.backup(backup)
 with sqlite3.connect(dest) as c:
  if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':dest.unlink(missing_ok=True);raise ValueError('SQLite integrity failure')
 sha=hashit(dest.read_bytes())
 with connect() as c:
  c.execute('INSERT INTO snapshots VALUES(?,?,?)',(dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds'),str(dest),sha))
  old=c.execute('SELECT at,path FROM snapshots ORDER BY at DESC LIMIT -1 OFFSET 7').fetchall()
  for row in old:
   p=Path(row['path'])
   if p.parent==ROOT/'backups' and p.name.startswith('atlas-'):p.unlink(missing_ok=True)
   c.execute('DELETE FROM snapshots WHERE at=?',(row['at'],))
 log('CHECKPOINT','db','PASS',f'{dest.name} sha={sha[:12]}')
 print('CHECKPOINT',dest.name,sha[:16]);return dest

def render():
 projects=query('SELECT * FROM projects ORDER BY CASE WHEN origin="Atlas" THEN 0 ELSE 1 END,updated DESC LIMIT 90')
 alerts=query("SELECT at,kind,target,severity,detail FROM events WHERE severity IN ('WARN','FAIL') ORDER BY id DESC LIMIT 12")
 chall=query('SELECT * FROM challenges ORDER BY updated DESC LIMIT 12')
 a=lambda x:html.escape(str(x),quote=True)
 cards=[]
 for x in projects:
  path=f'games/{a(x["name"])}/' if x['origin']=='Atlas' and x['stage'] in ('SHIPPED','WATCHED') else ''
  title=f'<a href="{path}">{a(x["name"])}</a>' if path else a(x['name'])
  cards.append(f'<div class="card"><small>{a(x["origin"])} · {a(x["kind"])}</small><h3>{title}</h3><div class="stage">{a(x["stage"])}</div><small>Quality score {a(x["score"])} / 90 static · SHA {a((x["sha"] or "—")[:12])}</small></div>')
 stages=[]
 for s in STAGES+('OBSERVED',):
  n=sum(1 for x in projects if x['stage']==s)
  stages.append(f'<div class="stagebox"><b>{a(s)}</b><strong>{n}</strong></div>')
 atom_cards=''.join(f'<div class="card"><small>v1 · CONTRACT</small><h3>{a(k)}</h3><p>{a(d)}</p><small>{a(con)}</small></div>' for k,(_,d,con) in ATOMS.items())
 glossary=''.join(f'<tr><td><b>{a(k)}</b></td><td>{a(v[1])}</td><td>{a(v[2])}</td></tr>' for k,v in TERMS.items())
 challenges=''.join(f'<li>{a(x["project"])} · {a(x["level"])} · {a(x["state"])} — {a(x["goal"])}</li>' for x in chall)
 signals=''.join(f'<li>{a(x["at"])} · {a(x["severity"])} · {a(x["target"])} — {a(x["detail"])}</li>' for x in alerts)
 placeholders=''.join(f'<div class="card placeholder"><small>PLANNED · NOT IMPLEMENTED</small><h3>{a(title)}</h3><p>{a(body)}</p></div>' for title,body in (('Live cross-device map','T530 → Acer → ASUS → Samsung; await verified connections'),('Visual regression','Browser screenshot + keyboard + accessibility tests'),('Dependency graph','Git/SHA lineage across LS repositories'),('Production promotion','Separate signed approvals and tested deploy receipts')))
 document=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="120"><title>LS Atlas / Quality Map</title><style>{CSS}body{{padding:2vw}}header{{margin:0 auto 28px;max-width:1250px}}.shell{{max-width:1250px;margin:auto}}h1{{font-size:clamp(2.3rem,8vw,5.2rem);margin:.1em 0}}section{{margin:32px 0}}.toc{{display:flex;gap:14px;flex-wrap:wrap}}.toc a{{padding:9px 12px;background:var(--panel);border-radius:10px}}.map{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:9px}}.stagebox,.card{{border:1px solid #364d6e;background:var(--panel);border-radius:15px;padding:16px}}.stagebox{{display:flex;flex-direction:column;gap:9px}}.stagebox strong{{font-size:2rem;color:var(--accent)}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}.card h3{{margin:.4em 0;overflow-wrap:anywhere}}.card p{{color:var(--muted)}}.stage{{color:var(--accent);font-weight:750}}table{{border-collapse:collapse;width:100%}}td{{padding:10px;border-bottom:1px solid #28364e;vertical-align:top}}.placeholder{{border-style:dashed;opacity:.8}}ul{{line-height:1.9}}.box{{background:var(--panel);border-radius:14px;padding:14px}}header p{{color:var(--muted)}}</style></head><body><div class="shell"><header><small>LS ∞ · UNIVERSAL INDEX · {a(STAMP())}</small><h1>ATLAS / QUALITY FORGE</h1><p>Everything gets a name, stage, provenance, checksum, challenge and next action. Older systems are only inspected.</p><nav class="toc"><a href="#stages">Stage map</a><a href="#inventory">Inventory</a><a href="#atoms">Atomic contracts</a><a href="#challenges">Challenge matrix</a><a href="#glossary">Dictionary</a><a href="#future">Placeholders</a><a href="#signals">Signals</a></nav></header><section id="stages"><h2>01 / Staged delivery map</h2><div class="map">{''.join(stages)}</div><p><small>Placeholder → Built → Hardened → Polished → Source-verified → Shipped → Watched. Imported means OBSERVED, not verified.</small></p></section><section id="inventory"><h2>02 / Discoverable inventory</h2><div class="cards">{''.join(cards) or '<p>Nothing discovered yet</p>'}</div></section><section id="atoms"><h2>03 / Stable building blocks</h2><div class="cards">{atom_cards}</div></section><section id="challenges"><h2>04 / Hard challenge matrix</h2><div class="box"><ul>{challenges or '<li>No active challenge yet</li>'}</ul><p><small>Moonshot requires browser verification; no aspirational goal is silently marked solved.</small></p></div></section><section id="glossary"><h2>05 / Recyclable vocabulary</h2><div class="box"><table>{glossary}</table></div></section><section id="future"><h2>06 / Placeholder regions</h2><div class="cards">{placeholders}</div></section><section id="signals"><h2>07 / Watch signals</h2><div class="box"><ul>{signals or '<li>No warnings recorded</li>'}</ul></div></section><footer><p><small>SQLite evidence · static HTML · versioned atoms · no dependencies · <a href="../empire/">Empire</a> · <a href="../microverse/">Microverse</a> · <a href="../">Conquer</a></small></p></footer></div></body></html>'''
 WEB.mkdir(parents=True,exist_ok=True)
 tmp=WEB/'index.html.tmp';tmp.write_text(document);os.replace(tmp,WEB/'index.html')
 (ROOT/'docs'/'TABLE-OF-CONTENTS.md').write_text('# LS Atlas Table of Contents\n\n'+'\n'.join(f'- {n} / {s}' for n,s in enumerate(('Stage map','Inventory','Atomic contracts','Challenge matrix','Dictionary','Placeholder regions','Watch signals'),1))+'\n')
 (ROOT/'docs'/'STATUS-MAP.json').write_text(json.dumps([dict(x) for x in projects],indent=2)+'\n')
 (ROOT/'docs'/'ATOMS.json').write_text(json.dumps(ATOMS,indent=2)+'\n')
 (ROOT/'docs'/'GLOSSARY.json').write_text(json.dumps(TERMS,indent=2)+'\n')
 print('DASHBOARD',WEB/'index.html')

def cycle():
 setup()
 with LOCK.open('a+') as lf:
  try:fcntl.flock(lf,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('CYCLE=SKIPPED previous cycle running');return
  if query("SELECT value FROM settings WHERE key='enabled'")[0]['value']!='1':print('CYCLE=PAUSED');return
  found,changed=scan()
  own=query("SELECT name,stage FROM projects WHERE origin='Atlas' ORDER BY created")
  if not own:register('signal-arcade','arcade');challenge('signal-arcade','moonshot')
  own=query("SELECT name,stage FROM projects WHERE origin='Atlas' ORDER BY created")
  nextup=next((x['name'] for x in own if x['stage']!='WATCHED'),None)
  if nextup:upgrade(nextup)
  elif len(own)<2:register('garden-builder','builder');challenge('garden-builder','accessibility')
  watch()
  render()
  print(f'CYCLE=PASS imported={found} drift={changed} own={len(own)} advanced={nextup or "none"}')

def status():
 for p in query('SELECT name,origin,stage,score,substr(sha,1,12) sha FROM projects ORDER BY origin,name'):
  print(f'{p["name"]:<26} {p["origin"]:<12} {p["stage"]:<13} score={p["score"]:<3} sha={p["sha"]}')
 print('LOW_QUALITY',query("SELECT count(*) n FROM projects WHERE origin='Atlas' AND stage IN ('PLACEHOLDER','BUILT','HARDENED')")[0]['n'],'CAP',QUALITY_CAP)

def tests():
 assert connect().execute('PRAGMA quick_check').fetchone()[0]=='ok'
 assert len(ATOMS)>=8 and len(TERMS)>12
 try:valid('../escape');raise AssertionError('Traversal permitted')
 except ValueError:pass
 assert all(k.startswith('--') for k in re.findall(r'--[a-z-]+(?=:)',CSS))
 name='test-arcade'
 if not query('SELECT 1 FROM projects WHERE name=?',(name,)):register(name,'arcade')
 for _ in range(6):upgrade(name)
 assert query('SELECT stage FROM projects WHERE name=?',(name,))[0]['stage']=='WATCHED'
 checks,score=verify(name,'POLISHED')
 assert all(v for k,v in checks.items() if k!='browser')
 assert checks['browser']==False and score<=90
 assert (WEB/'games'/name/'index.html').exists()
 assert not watch()
 # Mutation challenge: signed published bytes must trigger an alert once, not every poll.
 published=WEB/'games'/name/'index.html'
 original=published.read_bytes(); published.write_bytes(original+b'<!-- corrupt -->')
 assert watch()==[name]
 assert watch()==[name]
 assert len(query("SELECT 1 FROM events WHERE kind='TAMPER' AND target=?",(name,)))==1
 published.write_bytes(original)
 assert not watch()
 challenge(name,'moonshot')
 checkpoint();render()
 print('PASS staged game + 17 gates + SHA + challenges + watch + checkpoint + map')

def main():
 p=argparse.ArgumentParser(description='LS Atlas — staged map, atomic registry, hard challenge and game forge')
 sub=p.add_subparsers(dest='cmd')
 for x in ('cycle','status','map','toc','atoms','terms','scan','watch','checkpoint','signals','bell','pause','resume','test','next','challenges'):sub.add_parser(x)
 a=sub.add_parser('new');a.add_argument('name');a.add_argument('kind',nargs='?',default='arcade',choices=('arcade','builder'))
 a=sub.add_parser('upgrade');a.add_argument('name')
 a=sub.add_parser('verify');a.add_argument('name')
 a=sub.add_parser('challenge');a.add_argument('name');a.add_argument('level',nargs='?',default='moonshot',choices=sorted(CHALLENGES))
 a=p.parse_args();setup();cmd=a.cmd or 'status'
 if cmd=='new':register(a.name,a.kind)
 elif cmd=='upgrade':upgrade(a.name)
 elif cmd=='verify':
  gates,score=verify(a.name,'POLISHED');print('SCORE',score,'BROWSER=UNVERIFIED');print('\n'.join(f'{k}: {"PASS" if v else "UNVERIFIED" if k=="browser" else "FAIL"}' for k,v in gates.items()))
 elif cmd=='challenge':challenge(a.name,a.level)
 elif cmd=='cycle':cycle()
 elif cmd=='status':status()
 elif cmd=='test':tests()
 elif cmd=='watch':watch()
 elif cmd=='scan':print('SCAN imported,changed',scan())
 elif cmd in ('map','toc'):render();print((ROOT/'docs'/'TABLE-OF-CONTENTS.md').read_text() if cmd=='toc' else 'Map: '+str(WEB/'index.html'))
 elif cmd=='atoms':
  for r in query('SELECT * FROM atoms ORDER BY name'):print(r['name'],r['version'],r['contract'])
 elif cmd=='terms':
  for r in query('SELECT * FROM terms ORDER BY name'):print(r['name'],r['semantics'],r['definition'])
 elif cmd=='challenges':
  for r in query('SELECT * FROM challenges ORDER BY updated DESC'):print(r['project'],r['level'],r['state'],r['goal'])
 elif cmd=='checkpoint':checkpoint()
 elif cmd=='signals':
  for r in query('SELECT * FROM events ORDER BY id DESC LIMIT 24'):print(r['at'],r['severity'],r['kind'],r['target'],r['detail'])
 elif cmd=='bell':
  n=query("SELECT count(*) n FROM events WHERE severity IN ('WARN','FAIL')")[0]['n']
  if n:print('\a',f'ATLAS {n} warning/failure signals',flush=True)
  else:print('No warning signals')
 elif cmd=='next':
  for r in query("SELECT name,stage FROM projects WHERE origin='Atlas' AND stage!='WATCHED' ORDER BY created LIMIT 4"):
   print('atlas upgrade '+r['name'],'#',r['stage'])
 elif cmd in ('pause','resume'):
  with connect() as c:c.execute("UPDATE settings SET value=? WHERE key='enabled'",('0' if cmd=='pause' else '1',))
  print('AUTOMATION',cmd.upper())
 else:p.print_help()
if __name__=='__main__':
 try:main()
 except (ValueError,sqlite3.Error,OSError) as e:raise SystemExit('ATLAS ERROR: '+str(e))