#!/usr/bin/env python3
"""LS OpsX: compact, local-first Debian / Proxmox operations atelier."""
import argparse
import datetime as dt
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

ROOT=Path(os.environ.get('OPSX_ROOT','/opt/ls-workshop'))
WEB=Path(os.environ.get('OPSX_WEB','/opt/ls-conquer/www/opsx' if Path('/opt/ls-conquer/www').is_dir() else str(ROOT/'www')))
DB=ROOT/'opsx.sqlite'
BUNDLES={
 'foundation': ['curl','jq','git','sqlite3','tmux','rsync','make','ca-certificates'],
 'builder': ['shellcheck','bats','entr','task-spooler','hyperfine','just'],
 'discover': ['ripgrep','fd-find','fzf','yq','lnav','tree'],
 'observe': ['btop','duf','ncdu','lsof','strace','smartmontools'],
 'network': ['dnsutils','socat','tcpdump','mtr-tiny','netcat-openbsd'],
 'archive': ['zstd','restic','rclone','age'],
 'automation': ['inotify-tools','parallel','etckeeper','moreutils'],
 'creative': ['figlet','toilet','imagemagick','ffmpeg'],
}
ROLES={
 'caretaker': 'APT catalog, health reports, repair planning',
 'scout': 'Discover installed tools, package availability, candidate bundles',
 'builder': 'Generate small sites, projects, CI recipes, reusable skills',
 'stylist': 'Switch the dashboard theme; publish polished tiny sites',
 'archivist': 'Hash and checkpoint manifest/SQLite history',
 'scheduler': 'Run routines with systemd timers, not busy loops',
}
THEMES=('graphite','aurora','terminal')
PROTECT=re.compile(r'^(?:proxmox|pve-|libpve|qemu-server|lxc-pve|systemd|libc6|apt$|dpkg$|openssh-server|ifupdown2|linux-image|grub|zfs|python3$)', re.I)
NAME=re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,40}$')
PKG=re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9.+:-]*$')

def utc(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def db():
 ROOT.mkdir(parents=True,exist_ok=True)
 cx=sqlite3.connect(DB,timeout=15)
 cx.execute('PRAGMA busy_timeout=5000')
 cx.execute('PRAGMA journal_mode=WAL')
 cx.executescript('''
 CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,area TEXT,action TEXT,status TEXT,details TEXT);
 CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY,at TEXT,load REAL,available_mb INTEGER,disk_percent INTEGER,lxcs INTEGER);
 CREATE TABLE IF NOT EXISTS projects(name TEXT PRIMARY KEY,kind TEXT,created TEXT,path TEXT);
 CREATE TABLE IF NOT EXISTS tools(pkg TEXT PRIMARY KEY,installed INTEGER,available INTEGER,checked TEXT);
 CREATE TABLE IF NOT EXISTS checkpoints(id INTEGER PRIMARY KEY,at TEXT,folder TEXT,sha256 TEXT);
 CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
 ''')
 return cx

def event(area,action,status,details=''):
 with db() as cx:
  cx.execute('INSERT INTO events(at,area,action,status,details) VALUES(?,?,?,?,?)',(utc(),area,action,status,str(details)[:1000]))

def sh(args,timeout=100,capture=True):
 try:
  return subprocess.run(args,text=True,capture_output=capture,timeout=timeout,check=False)
 except (OSError,subprocess.TimeoutExpired) as e:
  return subprocess.CompletedProcess(args,127,'',str(e))

def pkg_installed(pkg):
 r=sh(['dpkg-query','-W','-f=${Status}',pkg],timeout=8)
 return r.returncode==0 and 'install ok installed' in r.stdout

def pkg_available(pkg):
 return sh(['apt-cache','show',pkg],timeout=7).returncode==0

def metrics():
 mem=0
 for ln in Path('/proc/meminfo').read_text().splitlines():
  if ln.startswith('MemAvailable:'): mem=int(ln.split()[1])//1024;break
 load=float(Path('/proc/loadavg').read_text().split()[0])
 du=sh(['df','-P','/'],timeout=6)
 disk=int(du.stdout.splitlines()[1].split()[4].strip('%')) if len(du.stdout.splitlines())>=2 else 0
 lxcs=0
 if shutil.which('pct'):
  res=sh(['pct','list'],timeout=10)
  if res.returncode==0: lxcs=max(0,len([x for x in res.stdout.splitlines() if x.strip()])-1)
 with db() as cx:cx.execute('INSERT INTO metrics(at,load,available_mb,disk_percent,lxcs) VALUES(?,?,?,?,?)',(utc(),load,mem,disk,lxcs))
 return {'load':load,'available_mb':mem,'disk_percent':disk,'lxcs':lxcs}

def catalog(show=False):
 allpkgs=list(dict.fromkeys(p for vals in BUNDLES.values() for p in vals))
 rows=[]
 with db() as cx:
  for pkg in allpkgs:
   installed=pkg_installed(pkg)
   available=True if installed else pkg_available(pkg)
   cx.execute('INSERT OR REPLACE INTO tools VALUES(?,?,?,?)',(pkg,int(installed),int(available),utc()))
   rows.append((pkg,installed,available))
 event('inventory','catalog','PASS',f'{len(rows)} tools catalogued')
 if show:
  for group,pkgs in BUNDLES.items():
   print(f'\n{group.upper()}')
   for p in pkgs:
    record=next(x for x in rows if x[0]==p)
    print(f'  {p:<22} {"INSTALLED" if record[1] else "AVAILABLE" if record[2] else "UNAVAILABLE"}')
 return rows

def root_only():
 if os.geteuid()!=0:raise SystemExit('This action requires root')

def valid_packages(packages):
 if not packages or any(not PKG.fullmatch(p) for p in packages):raise SystemExit('Invalid package name')

def run_apt(args,verb):
 root_only()
 proc=sh(args,timeout=900)
 text=(proc.stdout or '')+(proc.stderr or '')
 print(text[-7000:] if text else f'exit={proc.returncode}')
 event('apt',verb,'PASS' if proc.returncode==0 else 'FAIL',f'rc={proc.returncode}; {text[-400:]}')
 if proc.returncode:raise SystemExit(proc.returncode)

def read_removed(plan):
 return re.findall(r'^Remv\s+(\S+)',plan,flags=re.M)

def apt_command(args):
 sub=args.action
 if sub in ('scan','update'):
  run_apt(['apt-get','update','-qq'],'index-update')
  apt_command(argparse.Namespace(action='plan',packages=[],apply=False))
 elif sub=='plan':
  proc=sh(['apt-get','-s','full-upgrade'],timeout=90)
  output=proc.stdout+proc.stderr
  ROOT.joinpath('reports').mkdir(parents=True,exist_ok=True)
  (ROOT/'reports/upgrade-plan.txt').write_text(output)
  print('\n'.join(output.splitlines()[-45:]))
  print('\nFull plan: '+str(ROOT/'reports/upgrade-plan.txt'))
  event('apt','upgrade-plan','PASS' if proc.returncode==0 else 'FAIL',f'removals={len(read_removed(output))};rc={proc.returncode}')
 elif sub=='install':
  valid_packages(args.packages)
  run_apt(['apt-get','install','-y','--no-install-recommends',*args.packages],'install '+','.join(args.packages))
 elif sub in ('remove','prune','upgrade'):
  if sub=='remove':
   valid_packages(args.packages)
   if any(PROTECT.match(p) for p in args.packages):raise SystemExit('Protected infrastructure package: removal refused')
   command=['apt-get','remove',*args.packages]
  elif sub=='prune':command=['apt-get','autoremove']
  else:command=['apt-get','full-upgrade']
  simulated=sh([command[0],'-s',*command[1:]],timeout=90)
  print((simulated.stdout+simulated.stderr)[-6000:])
  if simulated.returncode: raise SystemExit('Simulation failed')
  removed=read_removed(simulated.stdout)
  protected=[p for p in removed if PROTECT.match(p)]
  if protected:raise SystemExit('Protected removals blocked: '+', '.join(protected))
  if not args.apply:
   print('\nPREVIEW ONLY. Add --apply to execute.');event('apt',sub+'-preview','PASS',f'{len(removed)} removals');return
  # Reject unexpected deletion of any package on automatic full-upgrade.
  if sub=='upgrade' and removed:raise SystemExit('Upgrade would remove packages: inspect plan first')
  run_apt([command[0],'-y',*command[1:]],sub)
 elif sub=='audit':
  for cmd in (['dpkg','--audit'],['apt-get','check']):
   p=sh(cmd,timeout=60);print('$ '+' '.join(cmd)+'\n'+(p.stdout+p.stderr or f'exit={p.returncode}'))
 elif sub=='repair':
  if not args.apply:print('Plan: dpkg --configure -a; apt-get -f install (use --apply)');return
  run_apt(['dpkg','--configure','-a'],'configure')
  run_apt(['apt-get','-f','install','-y'],'dependencies-repair')

def bundle(name):
 if name=='list':
  for k,v in BUNDLES.items():print(f'{k:12} {", ".join(v)}')
  return
 if name not in BUNDLES:raise SystemExit('Unknown bundle: '+name)
 missing=[p for p in BUNDLES[name] if not pkg_installed(p)]
 if not missing:
  print('Already installed: '+name);return
 print('Bundle '+name+' -> '+', '.join(missing))
 root_only()
 # Skip packages absent from current repositories instead of failing the whole bundle.
 selected=[p for p in missing if pkg_available(p)]
 if not selected:print('No available packages in bundle');return
 run_apt(['apt-get','install','-y','--no-install-recommends',*selected],'bundle-'+name)
 catalog()

def project(name,kind):
 if not NAME.fullmatch(name): raise SystemExit('Name must be 1–41 letters/digits/_/- and begin with letter')
 if kind not in ('site','game','pipeline','service','lab'):raise SystemExit('Choose site|game|pipeline|service|lab')
 dest=ROOT/'projects'/name
 if dest.exists():raise SystemExit('Project already exists: '+str(dest))
 dest.mkdir(parents=True)
 (dest/'README.md').write_text(f'# {name}\n\nKind: {kind}\nCreated: {utc()}\n\nRun: `make test` or `make serve`.\n')
 (dest/'Makefile').write_text('test:\n\t@grep -q "<!doctype html>" index.html && echo TEST=PASS\nserve:\n\t@python3 -m http.server 8088\n')
 if kind=='game':
  page='''<!doctype html><html><meta name="viewport" content="width=device-width"><title>Click Lab</title><style>body{font:18px system-ui;background:#0c1021;color:white;text-align:center;padding:12vh}button{font-size:30px;border:0;border-radius:18px;padding:24px 40px;background:#8ad;color:#112;cursor:pointer}</style><h1>CLICK LAB</h1><p>Score: <span id="score">0</span></p><button onclick="document.getElementById('score').textContent=++window.points">+1</button><script>window.points=0</script></html>'''
 else:
  page=f'''<!doctype html><html><meta name="viewport" content="width=device-width"><title>{html.escape(name)}</title><style>body{{background:#0d1020;color:#e9f2ff;font:18px system-ui;max-width:880px;margin:12vh auto;padding:25px}}main{{border:1px solid #384263;border-radius:24px;padding:38px;background:#1a2035}}h1{{font-size:54px}}</style><main><small>LS WORKSHOP / {html.escape(kind)}</small><h1>{html.escape(name)}</h1><p>Built, tested and deployed in one tiny template.</p></main></html>'''
 (dest/'index.html').write_text(page)
 # Deploy as static files to existing conquer web root, if writable.
 site=WEB/'projects'/name
 site.mkdir(parents=True,exist_ok=True)
 shutil.copy2(dest/'index.html',site/'index.html')
 with db() as cx:cx.execute('INSERT INTO projects VALUES(?,?,?,?)',(name,kind,utc(),str(dest)))
 event('builder','new '+kind,'PASS',str(dest))
 print(f'PROJECT={dest}\nSITE={site}\nTEST=make -C {dest} test')

def skill(name):
 if not NAME.fullmatch(name):raise SystemExit('Invalid skill name')
 s=ROOT/'skills'/name
 if s.exists():raise SystemExit('Skill already exists')
 s.mkdir(parents=True)
 script=s/'run.sh'
 script.write_text('#!/bin/sh\nset -eu\nprintf "SKILL %s PASS\\n" "'+name+'"\n')
 script.chmod(0o755)
 (s/'SKILL.md').write_text(f'# {name}\n\nPurpose: document one reusable operation.\n\nInputs: none.\nOutput: PASS receipt.\nVerification: `./run.sh`.\n')
 event('builder','skill-new','PASS',name)
 print(f'SKILL={s}\nRUN={script}')

def checkpoint():
 folder=ROOT/'checkpoints'/dt.datetime.now().strftime('%Y%m%d-%H%M%S')
 folder.mkdir(parents=True,exist_ok=True)
 (folder/'packages.txt').write_text(sh(['dpkg-query','-W','-f=${Package}\t${Version}\n'],timeout=80).stdout)
 (folder/'services.txt').write_text(sh(['systemctl','--failed','--no-pager','--plain'],timeout=20).stdout)
 if shutil.which('pct'):(folder/'lxcs.txt').write_text(sh(['pct','list'],timeout=20).stdout)
 with db() as cx:
  out=sqlite3.connect(folder/'opsx.sqlite')
  cx.backup(out);out.close()
 lines=[]
 for p in folder.iterdir():
  if p.is_file():lines.append(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}')
 manifest='\n'.join(lines)+'\n'
 (folder/'SHA256SUMS').write_text(manifest)
 with db() as cx:cx.execute('INSERT INTO checkpoints(at,folder,sha256) VALUES(?,?,?)',(utc(),str(folder),hashlib.sha256(manifest.encode()).hexdigest()))
 event('archive','checkpoint','PASS',str(folder))
 print(f'CHECKPOINT={folder}')

def get_theme():
 with db() as cx:
  row=cx.execute("SELECT value FROM settings WHERE key='theme'").fetchone()
 return row[0] if row else 'graphite'

def set_theme(theme):
 if theme not in THEMES:raise SystemExit('Themes: '+', '.join(THEMES))
 with db() as cx:cx.execute("INSERT OR REPLACE INTO settings VALUES('theme',?)",(theme,))
 event('stylist','theme','PASS',theme)
 board();print('THEME='+theme)

def board():
 WEB.mkdir(parents=True,exist_ok=True)
 with db() as cx:
  latest=cx.execute('SELECT at,load,available_mb,disk_percent,lxcs FROM metrics ORDER BY id DESC LIMIT 1').fetchone()
  events=cx.execute('SELECT at,area,action,status FROM events ORDER BY id DESC LIMIT 14').fetchall()
  projects=cx.execute('SELECT name,kind FROM projects ORDER BY created DESC LIMIT 15').fetchall()
  tools=cx.execute('SELECT COUNT(*),SUM(installed) FROM tools').fetchone()
  checkpoints=cx.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]
  counts=cx.execute('SELECT COUNT(*) FROM events').fetchone()[0]
 data= {'updated':utc(),'host':sh(['hostname'],timeout=5).stdout.strip(),'theme':get_theme(),'metrics':latest,'tools':tools,'checkpoints':checkpoints,'events':events,'projects':projects,'actions':counts,'bundles':list(BUNDLES.keys()),'roles':ROLES}
 (WEB/'data.json').write_text(json.dumps(data,indent=2))
 colors={
 'graphite':('#0c1019','#e9f0fb','#152033','#83cbff','#28354d'),
 'aurora':('#070e1a','#f0fffc','#112c35','#66f2be','#255361'),
 'terminal':('#070c08','#d7ffe4','#102016','#7cff93','#294632'),
 }
 bg,fg,surface,accent,border=colors[data['theme']]
 def card(head,value):return f'<div class="card"><small>{html.escape(head)}</small><strong>{html.escape(str(value))}</strong></div>'
 m=latest or ('-',0,0,0,0)
 cards=''.join((card('LOAD',m[1]),card('RAM AVAILABLE',str(m[2])+' MB'),card('DISK USED',str(m[3])+'%'),card('LXCs',m[4]),card('TOOLS INSTALLED',tools[1] or 0),card('CHECKPOINTS',checkpoints)))
 rows=''.join(f'<tr><td>{html.escape(str(e[0]))}</td><td>{html.escape(e[1])}</td><td>{html.escape(e[2])}</td><td>{html.escape(e[3])}</td></tr>' for e in events)
 pros=''.join(f'<span>{html.escape(p[0])} <small>/{html.escape(p[1])}</small></span>' for p in projects) or '<span>Create a project with <code>opsx new alpha site</code></span>'
 packs=''.join(f'<span>{html.escape(b)}</span>' for b in BUNDLES)
 text=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="90"><title>LS OpsX | {html.escape(data["host"])}</title><style>*{{box-sizing:border-box}}body{{margin:0;background:{bg};color:{fg};font:15px system-ui}}main{{max-width:1140px;margin:auto;padding:30px 22px 80px}}header{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px}}h1{{font-size:clamp(36px,6vw,62px);letter-spacing:-2px;margin:3px 0}}h2{{margin-top:45px}}small{{color:{accent};font-weight:600}}.muted{{opacity:.68}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-top:27px}}.card{{background:{surface};border:1px solid {border};border-radius:18px;padding:24px;min-height:115px}}strong{{display:block;font-size:30px;margin-top:12px}}section{{border:1px solid {border};background:{surface};border-radius:19px;padding:22px;overflow:auto}}code{{color:{accent}}}table{{border-collapse:collapse;width:100%;font-size:13px}}td{{padding:10px;border-bottom:1px solid {border}}}span{{display:inline-block;padding:9px 13px;border-radius:12px;margin:4px;background:{bg};border:1px solid {border}}}a{{color:{accent}}}footer{{opacity:.55;margin-top:45px}}</style></head><body><main><header><div><small>LS ∞ / ATOMIC OPERATIONS</small><h1>OpsX Workshop</h1><div class="muted">{html.escape(data["host"])} · {html.escape(utc())} · {data['theme']} theme</div></div><div><small>● LOCAL-FIRST / PASSIVE DASHBOARD</small></div></header><div class="grid">{cards}</div><h2>Factory kits</h2><section>{packs}<p class="muted">Install: <code>opsx bundle builder</code> · Generate: <code>opsx new alpha site</code> · Style: <code>opsx theme aurora</code></p></section><h2>Produced projects</h2><section>{pros}</section><h2>Recent receipts</h2><section><table>{rows}</table></section><footer>SQLite · Python stdlib · systemd timers · APT · Existing Conquer web server · <a href="data.json">machine-readable JSON</a></footer></main></body></html>'''
 (WEB/'index.html').write_text(text)
 return WEB/'index.html'

def status():
 m=metrics()
 with db() as cx:
  e=cx.execute('SELECT at,area,action,status FROM events ORDER BY id DESC LIMIT 5').fetchall()
  p=cx.execute('SELECT name,kind FROM projects').fetchall()
 print('HOST=',sh(['hostname'],timeout=5).stdout.strip(),' LOAD=',m['load'],' FREE_MB=',m['available_mb'],'DISK=',str(m['disk_percent'])+'%','LXCs=',m['lxcs'])
 print('BUNDLES=',', '.join(BUNDLES))
 print('PROJECTS=',', '.join(x[0] for x in p) or 'none')
 print('WEB=',board())
 for x in e:print('EVENT',' | '.join(x))

def routines(online=False):
 m=metrics()
 if online:
  r=sh(['apt-get','update','-qq'],timeout=160)
  event('apt','scheduled-index-update','PASS' if r.returncode==0 else 'FAIL',str(r.returncode))
  # don't upgrade Proxmox automatically
  catalog()
 event('routine','run','PASS',str(m))
 board()
 print('ROUTINE=PASS')

def database_report():
 with db() as cx:
  print('INTEGRITY='+cx.execute('PRAGMA integrity_check').fetchone()[0])
  for table in ('events','metrics','projects','tools','checkpoints'):
   print(f'{table.upper()}={cx.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]}')
 print('DB='+str(DB))

def schedules():
 p=sh(['systemctl','list-timers','--all','--no-pager','--plain'],timeout=20)
 lines=[x for x in p.stdout.splitlines() if ('ls-' in x or 'opsx' in x)]
 for line in lines:print(line)
 print('TIMER_UNITS: ls-opsx-probe.timer ls-opsx-scan.timer ls-opsx-checkpoint.timer')

def sync(dest):
 root_only()
 if not shutil.which('rsync'):raise SystemExit('Install rsync first: opsx bundle foundation')
 if not dest or dest.startswith('-'):raise SystemExit('Usage: opsx sync /mounted/backup/path')
 # Mirror copies without deleting anything at the destination; avoid syncing active DB WAL file.
 checkpoint()
 source=ROOT/'checkpoints'
 r=sh(['rsync','-a','--',str(source)+'/',dest.rstrip('/')+'/'],timeout=180)
 print((r.stdout+r.stderr)[-2000:] or f'rsync exit={r.returncode}')
 event('archive','sync','PASS' if r.returncode==0 else 'FAIL',dest)
 if r.returncode:raise SystemExit(r.returncode)

def skills_report():
 directory=ROOT/'skills'
 for d in sorted(directory.glob('*/SKILL.md')):
  print(d.parent.name, '->', d.parent/'run.sh')

def main():
 ap=argparse.ArgumentParser(description='LS OpsX — small infrastructure crews and reusable kits')
 sub=ap.add_subparsers(dest='cmd')
 sub.add_parser('status');sub.add_parser('facts');sub.add_parser('next');sub.add_parser('roles');sub.add_parser('catalog');sub.add_parser('board');sub.add_parser('checkpoint');sub.add_parser('db');sub.add_parser('schedules');sub.add_parser('skills')
 p=sub.add_parser('bundle');p.add_argument('name',nargs='?',default='list')
 p=sub.add_parser('theme');p.add_argument('name',choices=THEMES)
 p=sub.add_parser('new');p.add_argument('name');p.add_argument('kind',choices=['site','game','pipeline','service','lab'])
 p=sub.add_parser('skill');p.add_argument('name')
 p=sub.add_parser('sync');p.add_argument('destination')
 p=sub.add_parser('routine');p.add_argument('--online',action='store_true')
 p=sub.add_parser('history');p.add_argument('-n',type=int,default=25)
 p=sub.add_parser('apt');p.add_argument('action',choices=['scan','update','plan','install','remove','prune','upgrade','audit','repair']);p.add_argument('packages',nargs='*');p.add_argument('--apply',action='store_true')
 a=ap.parse_args();cmd=a.cmd or 'status';db().close()
 if cmd in ('status','facts'):status()
 elif cmd=='catalog':catalog(True)
 elif cmd=='bundle':bundle(a.name)
 elif cmd=='theme':set_theme(a.name)
 elif cmd=='new':project(a.name,a.kind);board()
 elif cmd=='skill':skill(a.name)
 elif cmd=='routine':routines(a.online)
 elif cmd=='history':
  with db() as cx:
   for x in cx.execute('SELECT at,area,action,status,details FROM events ORDER BY id DESC LIMIT ?', (min(1000,max(1,a.n)),)):
    print(' | '.join(str(s) for s in x))
 elif cmd=='apt':apt_command(a);board()
 elif cmd=='checkpoint':checkpoint();board()
 elif cmd=='board':print(board())
 elif cmd=='db':database_report()
 elif cmd=='schedules':schedules()
 elif cmd=='sync':sync(a.destination)
 elif cmd=='skills':skills_report()
 elif cmd=='roles':
  for role,meaning in ROLES.items():print(f'{role:12} {meaning}')
 elif cmd=='next':
  with db() as cx:
   n=cx.execute('SELECT COUNT(*) FROM tools').fetchone()[0]
  print('1. opsx catalog   # refresh toolbox')
  print('2. opsx bundle builder   # add testing/build workers')
  print('3. opsx new arcade game  # instantly produce a web project')
  print('4. opsx apt plan   # inspect system updates')
  print('5. opsx checkpoint   # record configuration')
  print(f'Catalog entries: {n}')

if __name__=='__main__':main()