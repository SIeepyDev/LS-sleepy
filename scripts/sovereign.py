#!/usr/bin/env python3
"""LS Sovereign v1: small bounded autonomous controller-of-controllers.

Stdlib-only: SQLite/WAL, systemd timer, existing Conquer static web root.
Execution is limited to explicit built-in jobs and preselected LS web services.
"""
import argparse
import concurrent.futures
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(os.getenv('LS_SOV_ROOT', '/opt/ls-sovereign'))
WEB = Path(os.getenv('LS_SOV_WEB', '/opt/ls-conquer/www/control'))
DB = ROOT/'control.sqlite'
CONFIG = ROOT/'config.json'
LOCK = ROOT/'tick.lock'
NOW = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
DEFAULT = {
    'enabled': True,
    'queue_enabled': True,
    'auto_repair': True,
    'min_free_mb': 768,
    'min_free_disk_pct': 12,
    'max_load_per_cpu': 1.5,
    'max_workers': 3,
    'repair_cooldown_minutes': 60,
    'repair_services': ['ls-conquer-web.service'],
    'auto_jobs': {'lxc': 1800, 'ports': 3600},
    'checkpoint_interval_hours': 24,
}
# Fixed known actions; never execute arbitrary input as root.
JOBS = {
    'lxc': (['pct', 'list'], 12),
    'ports': (['ss', '-lntup'], 12),
    'storage': (['df', '-h'], 12),
    'units': (['systemctl', '--failed', '--no-pager', '--plain'], 12),
    'probe': (['conquer', 'probe'], 40),
    'hunt': (['conquer', 'hunt'], 40),
    'factory': (['factory', 'offline', '1'], 100),
    'crew': (['crew', 'run'], 100),
}
CONTROLLERS = ('INSPECTOR','GOVERNOR','ROUTER','HEALER','ARCHIVIST','ADVISOR')

class Conn(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

def connect():
    ROOT.mkdir(parents=True, exist_ok=True)
    cx=sqlite3.connect(DB, timeout=15, factory=Conn)
    cx.row_factory=sqlite3.Row
    cx.execute('PRAGMA journal_mode=WAL')
    cx.execute('PRAGMA busy_timeout=10000')
    return cx

def setup():
    ROOT.mkdir(parents=True,exist_ok=True)
    WEB.mkdir(parents=True,exist_ok=True)
    (ROOT/'backups').mkdir(exist_ok=True)
    (ROOT/'logs').mkdir(exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULT,indent=2)+'\n')
    with connect() as cx:
        cx.executescript('''
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts TEXT,controller TEXT,action TEXT,status TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY,value TEXT,updated TEXT);
        CREATE TABLE IF NOT EXISTS jobs(
          id INTEGER PRIMARY KEY,kind TEXT NOT NULL,project TEXT NOT NULL DEFAULT 'system',
          status TEXT NOT NULL DEFAULT 'QUEUED',created TEXT NOT NULL,
          started TEXT,finished TEXT,attempts INTEGER NOT NULL DEFAULT 0,
          next_at TEXT,elapsed_ms INTEGER,output TEXT);
        CREATE INDEX IF NOT EXISTS ix_jobs_await ON jobs(status,next_at,id);
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,ts TEXT,path TEXT,sha256 TEXT,bytes INTEGER);
        CREATE TABLE IF NOT EXISTS controllers(name TEXT PRIMARY KEY,last_run TEXT,status TEXT,detail TEXT);
        ''')
        for name in CONTROLLERS:
            cx.execute('INSERT OR IGNORE INTO controllers(name,status,detail) VALUES(?,?,?)',(name,'PENDING',''))

def config():
    d=DEFAULT.copy()
    d.update(json.loads(CONFIG.read_text()))
    return d

def saveconfig(d):
    tmp=CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(d,indent=2)+'\n')
    os.replace(tmp,CONFIG)

def run(argv, seconds=10):
    if shutil.which(argv[0]) is None:
        return 127, f'{argv[0]} not installed'
    try:
        p=subprocess.run(argv,timeout=seconds,capture_output=True,text=True,check=False,env={**os.environ, 'DEBIAN_FRONTEND':'noninteractive'})
        return p.returncode, (p.stdout+'\n'+p.stderr).strip()[:2200]
    except (subprocess.TimeoutExpired, OSError) as e:
        return 124,str(e)[:400]

def event(who,action,status,detail=''):
    with connect() as cx:
        cx.execute('INSERT INTO events(ts,controller,action,status,detail) VALUES(?,?,?,?,?)',
                   (NOW(),who,action,status,str(detail)[:800]))

def controller(name,status,detail=''):
    with connect() as cx:
        cx.execute('UPDATE controllers SET last_run=?,status=?,detail=? WHERE name=?',
                   (NOW(),status,str(detail)[:220],name))

def fact(key,value,log_change=True):
    v=json.dumps(value,sort_keys=True,ensure_ascii=False)
    with connect() as cx:
        old=cx.execute('SELECT value FROM facts WHERE key=?',(key,)).fetchone()
        cx.execute('INSERT OR REPLACE INTO facts VALUES(?,?,?)',(key,v,NOW()))
    if log_change and (not old or old['value']!=v):
        event('INSPECTOR',key,'CHANGED',v[:400])

def inspect():
    meminfo={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        k,_,v=line.partition(':')
        if k in ('MemAvailable','MemTotal'):meminfo[k]=int(v.split()[0])//1024
    disk=shutil.disk_usage('/')
    cores=os.cpu_count() or 1
    load=os.getloadavg()[0]
    metrics={'host':os.uname().nodename,'available_mb':meminfo.get('MemAvailable',0),
             'total_mb':meminfo.get('MemTotal',0),'disk_free_pct':round(disk.free*100/max(1,disk.total),1),
             'load_1':round(load,2),'cores':cores,'time':NOW()}
    fact('host',metrics,log_change=False)
    # Only lightweight, read-only host probes.
    for name, argv in [('lxcs',['pct','list']),('failed_units',['systemctl','--failed','--no-pager','--plain'])]:
        rc,output=run(argv,12)
        if rc==0:
            fact(name, output[:1000])
    controller('INSPECTOR','OK',f"{metrics['available_mb']}MB free; {metrics['disk_free_pct']}% disk free")
    return metrics

def govern(metrics, cfg):
    reasons=[]
    if metrics['available_mb']<cfg['min_free_mb']:reasons.append('low free RAM')
    if metrics['disk_free_pct']<cfg['min_free_disk_pct']:reasons.append('low free disk')
    if metrics['load_1']/max(1,metrics['cores'])>cfg['max_load_per_cpu']:reasons.append('high load')
    if not cfg['queue_enabled']:reasons.append('queue paused')
    slots=0 if reasons else max(1,min(int(cfg['max_workers']),4,
                                  int(metrics['available_mb'])//max(256,int(cfg['min_free_mb']))))
    fact('governor',{'slots':slots,'reasons':reasons,'max_workers':cfg['max_workers']})
    controller('GOVERNOR','PAUSED' if reasons else 'OK',f'{slots} slots; '+(', '.join(reasons) if reasons else 'within limits'))
    return slots

def enqueue(kind,project='system',automatic=False):
    if kind not in JOBS: raise SystemExit('Allowed: '+', '.join(JOBS))
    if not project or len(project)>48 or not all(c.isalnum() or c in '-_' for c in project):
        raise SystemExit('Invalid project label')
    with connect() as cx:
        if automatic:
            x=cx.execute('SELECT id FROM jobs WHERE kind=? AND project=? AND status IN ("QUEUED","RUNNING")',
                         (kind,project)).fetchone()
            if x:return x['id']
        row=cx.execute('INSERT INTO jobs(kind,project,status,created,next_at) VALUES(?,?,?,?,?)',
                       (kind,project,'QUEUED',NOW(),NOW()))
        id=row.lastrowid
    event('ROUTER',f'enqueue {kind}','QUEUED',f'{id} / {project}')
    return id

def schedule(cfg):
    # Only seed jobs if enough time passed since last enqueue. No duplicate recurring timers.
    if not cfg['queue_enabled']:return
    now=time.time()
    for kind, interval in cfg['auto_jobs'].items():
        if kind not in JOBS or not shutil.which(JOBS[kind][0][0]):continue
        with connect() as cx:
            row=cx.execute('SELECT created FROM jobs WHERE kind=? AND project=? ORDER BY id DESC LIMIT 1',(kind,'auto')).fetchone()
        if row:
            try:
                ts=dt.datetime.fromisoformat(row['created']).timestamp()
                if now-ts<int(interval):continue
            except (ValueError,TypeError):pass
        enqueue(kind,'auto',automatic=True)

def recover_interrupted():
    # A killed cycle may leave RUNNING receipts; recover read-only tasks, never blindly
    # repeat external build/deploy work whose outcome may already exist.
    stale=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=10)).isoformat(timespec='seconds')
    recovered=[]
    with connect() as cx:
        rows=cx.execute('SELECT id,kind FROM jobs WHERE status="RUNNING" AND started<?',(stale,)).fetchall()
        for row in rows:
            state='UNCERTAIN' if row['kind'] in ('factory','crew') else 'RETRY'
            cx.execute('UPDATE jobs SET status=?,next_at=?,finished=?,output=? WHERE id=?',
                       (state,NOW(),NOW(),'Recovered stale RUNNING receipt after interruption',row['id']))
            recovered.append((row['id'],state))
    for id,state in recovered:
        event('HEALER',f'stale job #{id}',state,'Recovered interrupted controller cycle')
    return recovered

def execute_job(row):
    name=row['kind']
    args,timeout=JOBS[name]
    start=time.monotonic()
    rc,output=run(args,timeout)
    elapsed=int((time.monotonic()-start)*1000)
    with connect() as cx:
        retry=(rc!=0 and row['attempts']<2 and rc!=127)
        newstatus='RETRY' if retry else 'PASS' if rc==0 else 'FAILED'
        later=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=5*max(1,row['attempts']))).isoformat(timespec='seconds') if retry else None
        cx.execute('UPDATE jobs SET status=?,finished=?,elapsed_ms=?,output=?,next_at=? WHERE id=?',
                   (newstatus,NOW(),elapsed,f'rc={rc} {output}'[:2200],later,row['id']))
    event('ROUTER',f'{name} #{row["id"]}',newstatus,f'{elapsed}ms rc={rc}')
    return name,newstatus,elapsed

def route(slots):
    if slots==0:
        controller('ROUTER','PAUSED','resource governor denied slots')
        return []
    ts=NOW()
    with connect() as cx:
        # Lock each candidate before starting workers. Timed-out RUNNING jobs are not silently replayed.
        rows=cx.execute('SELECT * FROM jobs WHERE status IN ("QUEUED","RETRY") AND next_at<=? ORDER BY id LIMIT ?',
                        (ts,slots)).fetchall()
        for row in rows:
            cx.execute('UPDATE jobs SET status="RUNNING",started=?,attempts=attempts+1 WHERE id=?',(ts,row['id']))
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=slots) as pool:
        for res in pool.map(execute_job,rows):results.append(res)
    controller('ROUTER','OK',f'{len(results)} completed; slots={slots}')
    return results

def heal(cfg):
    if not cfg['auto_repair']:
        controller('HEALER','PAUSED','disabled by config');return
    healed=0
    for service in cfg['repair_services'][:8]:
        # Only auto-repair specific approved LS-owned web services, never Proxmox/system/network units.
        if service!='ls-conquer-web.service':continue
        rc,enabled=run(['systemctl','is-enabled',service],8)
        if rc!=0 or enabled.strip()!='enabled':continue
        rc,active=run(['systemctl','is-active',service],8)
        if active.strip()!='failed':continue
        with connect() as cx:
            last=cx.execute('SELECT ts FROM events WHERE controller="HEALER" AND action=? ORDER BY id DESC LIMIT 1',(service,)).fetchone()
        if last:
            try:
                mins=(time.time()-dt.datetime.fromisoformat(last['ts']).timestamp())/60
                if mins<cfg['repair_cooldown_minutes']:continue
            except (TypeError,ValueError):pass
        rc,output=run(['systemctl','restart',service],20)
        result='RECOVERED' if rc==0 and run(['systemctl','is-active',service],8)[1].strip()=='active' else 'FAILED'
        event('HEALER',service,result,output[:300])
        healed+=1
    controller('HEALER','OK',f'{healed} approved service repair(s)')

def snapshot(cfg,force=False):
    with connect() as cx:
        last=cx.execute('SELECT ts FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
    if not force and last:
        try:
            if (time.time()-dt.datetime.fromisoformat(last['ts']).timestamp()) < cfg['checkpoint_interval_hours']*3600:
                controller('ARCHIVIST','OK','checkpoint recent')
                return None
        except (ValueError,TypeError):pass
    dest=ROOT/'backups'/('control-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
    with connect() as src, sqlite3.connect(dest) as dst:
        src.backup(dst)
    digest=hashlib.sha256(dest.read_bytes()).hexdigest()
    with sqlite3.connect(dest) as verify:
        integrity=verify.execute('PRAGMA quick_check').fetchone()[0]
    if integrity!='ok':
        dest.unlink(missing_ok=True)
        controller('ARCHIVIST','FAILED','snapshot integrity failure')
        return None
    with connect() as cx:
        cx.execute('INSERT INTO snapshots(ts,path,sha256,bytes) VALUES(?,?,?,?)',
                   (NOW(),str(dest),digest,dest.stat().st_size))
    # Recycle our own old SQLite checkpoint files, retaining the newest 14.
    with connect() as cx:
        stale=cx.execute('SELECT id,path FROM snapshots ORDER BY id DESC LIMIT -1 OFFSET 14').fetchall()
        for old in stale:
            oldpath=Path(old['path'])
            if oldpath.parent==ROOT/'backups' and oldpath.name.startswith('control-') and oldpath.suffix=='.sqlite':
                oldpath.unlink(missing_ok=True)
            cx.execute('DELETE FROM snapshots WHERE id=?',(old['id'],))
    controller('ARCHIVIST','OK',f'checkpoint {dest.name}')
    event('ARCHIVIST','snapshot','PASS',f'{dest.name} {digest[:16]}')
    return dest

def advise(metrics,slots):
    # Recommendation engine is deterministic and derived from real metrics.
    with connect() as cx:
        waiting=cx.execute('SELECT count(*) FROM jobs WHERE status IN ("QUEUED","RETRY")').fetchone()[0]
        failed=cx.execute('SELECT count(*) FROM jobs WHERE status="FAILED"').fetchone()[0]
    ideas=[]
    if metrics['disk_free_pct']<20:ideas.append('Disk headroom low: inspect with ncdu; do not auto-delete.')
    if slots==0: ideas.append('Resource governor paused jobs: inspect ctrl facts.')
    if failed:ideas.append(f'{failed} jobs failed: inspect ctrl jobs.')
    if waiting:ideas.append(f'{waiting} jobs waiting: ctrl tick after pressure clears.')
    if not ideas:ideas.append('System healthy: queue work with ctrl add probe|lxc|storage|ports|hunt.')
    fact('advice', ideas)
    controller('ADVISOR','OK',ideas[0])

def render():
    with connect() as cx:
        controllers=cx.execute('SELECT * FROM controllers ORDER BY name').fetchall()
        jobs=cx.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 14').fetchall()
        events=cx.execute('SELECT * FROM events ORDER BY id DESC LIMIT 18').fetchall()
        rows=cx.execute('SELECT key,value FROM facts').fetchall()
    facts={row['key']:json.loads(row['value']) for row in rows}
    host=facts.get('host',{})
    gov=facts.get('governor',{})
    advice=facts.get('advice',[])
    h=lambda x:html.escape(str(x),quote=True)
    ctr=''.join(f'<div class="card"><small>{h(c["name"])}</small><strong>{h(c["status"])}</strong><p>{h(c["detail"])}</p></div>' for c in controllers)
    js=''.join(f'<tr><td>#{j["id"]}</td><td>{h(j["project"])}</td><td>{h(j["kind"])}</td><td>{h(j["status"])}</td><td>{h(j["elapsed_ms"] or "—")}</td></tr>' for j in jobs)
    ev=''.join(f'<tr><td>{h(e["ts"][11:19])}</td><td>{h(e["controller"])}</td><td>{h(e["action"])}</td><td>{h(e["status"])}</td></tr>' for e in events)
    WEB.mkdir(parents=True, exist_ok=True)
    page=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60"><title>LS Sovereign Control</title><style>
    *{{box-sizing:border-box}}body{{background:#0b101a;color:#edf2f8;font:15px system-ui;margin:0 auto;padding:3vw;max-width:1150px}}h1{{font-size:clamp(30px,5vw,52px);margin:4px 0}}small,.muted{{color:#99adc5}}strong{{font-size:19px;color:#9eecc4}}p{{color:#b6c8d9}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:24px 0}}.card{{border:1px solid #27354d;background:#131d2c;padding:20px;border-radius:14px;display:flex;flex-direction:column;gap:8px}}.stat{{font-size:27px;font-weight:750;color:#8bdaf7}}table{{width:100%;border-collapse:collapse;background:#121b28;border-radius:12px;overflow:hidden}}th,td{{border-bottom:1px solid #26364b;padding:9px;text-align:left}}th{{color:#a5bad2;font-size:12px}}a{{color:#90dbff}}code{{color:#a8edc5}}.scroll{{overflow:auto}}ul{{padding-left:19px;line-height:1.8}}</style></head><body>
    <small>LS ∞ / CONTROL PLANE / {h(host.get('time','not yet probed'))}</small><h1>SOVEREIGN</h1><p>One orchestrator · six controllers · bounded parallel jobs · local SQLite intelligence</p>
    <div class="grid"><div class="card"><small>AVAILABLE RAM</small><span class="stat">{h(host.get('available_mb','?'))} MB</span></div><div class="card"><small>FREE DISK</small><span class="stat">{h(host.get('disk_free_pct','?'))}%</span></div><div class="card"><small>ACTIVE JOB SLOTS</small><span class="stat">{h(gov.get('slots','?'))}</span></div><div class="card"><small>CPU LOAD / CORES</small><span class="stat">{h(host.get('load_1','?'))} / {h(host.get('cores','?'))}</span></div></div>
    <h2>Controllers</h2><div class="grid">{ctr}</div>
    <h2>Next actions</h2><div class="card"><ul>{''.join('<li>'+h(x)+'</li>' for x in advice)}</ul><code>ctrl status · ctrl jobs · ctrl add probe · ctrl tick · ctrl checkpoint</code></div>
    <h2>Job Router</h2><div class="scroll"><table><tr><th>ID</th><th>Project</th><th>Action</th><th>Status</th><th>ms</th></tr>{js}</table></div>
    <h2>Recent decisions</h2><div class="scroll"><table><tr><th>UTC</th><th>Controller</th><th>Action</th><th>Result</th></tr>{ev}</table></div>
    <p class="muted">Reuses Conquer's web server. No login; keep this private to your LAN. <a href="../">Conquer</a> · <a href="../crew/">Crew</a> · <a href="../microverse/">Microverse</a> · <a href="../opsx/">OpsX</a></p></body></html>'''
    tmp=WEB/'index.html.tmp'
    tmp.write_text(page)
    os.replace(tmp,WEB/'index.html')

def tick():
    setup()
    with LOCK.open('a+') as lk:
        try:fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Previous controller cycle still active');return 0
        cfg=config()
        if not cfg['enabled']:
            print('Controller paused');return 0
        metrics=inspect()
        slots=govern(metrics,cfg)
        schedule(cfg)
        # Service recovery independent of job queue; no Proxmox service modification.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(heal,cfg)
            recovered=recover_interrupted()
            routed=route(slots)
            future.result(timeout=60)
        snapshot(cfg)
        advise(metrics,slots)
        event('KERNEL','tick','PASS',f'jobs={len(routed)} slots={slots}')
        render()
        print(f"CONTROL=PASS controllers=6 slots={slots} jobs={len(routed)} dashboard={WEB/'index.html'}")
    return 0

def status():
    setup()
    with connect() as cx:
        for c in cx.execute('SELECT name,status,detail,last_run FROM controllers ORDER BY name'):
            print(f'{c["name"]:11} {c["status"]:10} {c["detail"] or ""}')
        print('\nJOBS:',cx.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
              'PENDING:',cx.execute('SELECT COUNT(*) FROM jobs WHERE status IN ("QUEUED","RETRY")').fetchone()[0])
        for f in cx.execute('SELECT key,value FROM facts WHERE key IN ("host","governor","advice")'):
            print(f["key"],f["value"][:300])

def eyes():
    if not shutil.which('tmux'):
        raise SystemExit('Install tmux to use the four-pane view')
    subprocess.run(['tmux','has-session','-t','sovereign'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if subprocess.run(['tmux','has-session','-t','sovereign'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0:
        script=[
            ['tmux','new-session','-d','-s','sovereign','-n','CONTROL','watch -n 5 ctrl status'],
            ['tmux','split-window','-h','-t','sovereign:CONTROL','watch -n 5 ctrl jobs'],
            ['tmux','split-window','-v','-t','sovereign:CONTROL.0','watch -n 5 ctrl facts'],
            ['tmux','split-window','-v','-t','sovereign:CONTROL.2','journalctl -fu ls-sovereign-cycle.service'],
            ['tmux','select-layout','-t','sovereign:CONTROL','tiled'],
            ['tmux','set-window-option','-t','sovereign:CONTROL','pane-border-status','top'],
        ]
        for step in script:
            p=subprocess.run(step,check=False)
            if p.returncode: raise SystemExit('tmux setup failed: '+' '.join(step))
    os.execvp('tmux',['tmux','attach-session','-t','sovereign'])

def jobs():
    with connect() as cx:
        for r in cx.execute('SELECT id,project,kind,status,attempts,elapsed_ms FROM jobs ORDER BY id DESC LIMIT 30'):
            print(f'#{r["id"]:04} {r["project"]:15} {r["kind"]:9} {r["status"]:8} tries={r["attempts"]} ms={r["elapsed_ms"]}')

def test():
    setup()
    with connect() as cx:assert cx.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    assert len(CONTROLLERS)==6
    assert len(JOBS)>=6
    assert 'load_1' in inspect()
    assert 'max_workers' in config()
    print('PASS sqlite + config + host probe + controller registry')

def main():
    p=argparse.ArgumentParser(description='LS Sovereign — controller-of-controllers')
    sub=p.add_subparsers(dest='cmd')
    for name in ('install','tick','status','tree','jobs','facts','events','checkpoint','test','pause','resume','queue-on','queue-off','config','render','eyes'):
        sub.add_parser(name)
    a=sub.add_parser('add');a.add_argument('kind',choices=sorted(JOBS));a.add_argument('project',nargs='?',default='manual')
    a=sub.add_parser('watch');a.add_argument('service')
    args=p.parse_args();setup();cmd=args.cmd or 'status'
    if cmd in ('status','tree'):status()
    elif cmd in ('install','tick'):tick()
    elif cmd=='jobs':jobs()
    elif cmd=='eyes':eyes()
    elif cmd=='test':test()
    elif cmd=='checkpoint':print('SNAPSHOT',snapshot(config(),True))
    elif cmd=='render':render();print(WEB/'index.html')
    elif cmd=='add':print('QUEUED',enqueue(args.kind,args.project))
    elif cmd=='events':
        with connect() as cx:
            for e in cx.execute('SELECT ts,controller,action,status,detail FROM events ORDER BY id DESC LIMIT 24'):
                print(' | '.join(str(x) for x in e))
    elif cmd=='facts':
        with connect() as cx:
            for row in cx.execute('SELECT key,value FROM facts ORDER BY key'):print(row['key'],row['value'][:2000])
    elif cmd in ('pause','resume','queue-on','queue-off'):
        d=config();key='enabled' if cmd in ('pause','resume') else 'queue_enabled'
        d[key]=cmd in ('resume','queue-on');saveconfig(d);event('KERNEL',key,'ON' if d[key] else 'OFF');print(key,d[key])
    elif cmd=='watch':
        if args.service != 'ls-conquer-web.service':raise SystemExit('Only LS Conquer web is currently approved for automatic restart')
        d=config();d['repair_services']=[args.service];saveconfig(d);print('WATCHING',args.service)
    elif cmd=='config':print(json.dumps(config(),indent=2))
    else:p.print_help()

if __name__=='__main__':main()