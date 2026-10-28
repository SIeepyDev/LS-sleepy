#!/usr/bin/env python3
"""LS Microverse: dependency-free static lab, projects, feeds, music and recipe registry."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

ROOT = Path(os.environ.get('MICRO_ROOT', '/opt/ls-microverse'))
WEB = Path(os.environ.get('MICRO_WEB', '/opt/ls-conquer/www/microverse'))
DB = ROOT / 'microverse.sqlite'
NOW = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
CATALOG = [
    ('BeepMini', 'game engine', 'https://beepmini.com/', 'Small browser-based retro game engine'),
    ('Navidrome', 'music', 'https://github.com/navidrome/navidrome', 'Personal browser music streaming server'),
    ('Miniflux', 'reader', 'https://github.com/miniflux/v2', 'Minimal RSS aggregator'),
    ('Glance', 'dashboard', 'https://github.com/glanceapp/glance', 'Personal single-binary dashboard'),
    ('Dozzle', 'logs', 'https://github.com/amir20/dozzle', 'Live container log viewer'),
    ('PocketBase', 'backend', 'https://github.com/pocketbase/pocketbase', 'Embedded backend and admin UI'),
    ('OliveTin', 'automation', 'https://github.com/OliveTin/OliveTin', 'Web buttons for predefined scripts'),
    ('2048', 'game', 'https://github.com/gabrielecirulli/2048', 'Classic open-source HTML game'),
    ('Beszel', 'monitor', 'https://github.com/henrygd/beszel', 'Tiny server monitoring dashboard'),
    ('Caddy', 'routing', 'https://github.com/caddyserver/caddy', 'Modern web server and HTTPS routing'),
    ('AnimeSchedule', 'anime', 'https://animeschedule.net/', 'Public anime schedules and RSS'),
    ('Web Arcade', 'games', 'https://github.com/duysqubix/web-arcade', 'Zero-install browser games'),
]
DEFAULT_FEEDS = [
    ('Proxmox community releases','https://github.com/community-scripts/ProxmoxVE/releases.atom'),
    ('Anime schedule','https://animeschedule.net/subrss.xml'),
    ('Hacker News highlights','https://hnrss.org/newest?points=100'),
]
SKILLS = [
    ('micro-static', 'Generate and publish a tiny static site', 'micro new my-site site'),
    ('micro-game', 'Create a self-contained browser game', 'micro new my-game game'),
    ('micro-pulse', 'Generate a live system pulse tile', 'micro new my-dashboard dashboard'),
    ('rss-watch', 'Monitor a public RSS/Atom source', 'micro feed add https://example.com/rss'),
    ('youtube-watch', 'Track a YouTube channel with public Atom feeds', 'micro youtube CHANNEL_ID'),
    ('music-library', 'Index authorized media dropped into the local music folder', 'micro music'),
    ('site-smoke', 'Check a deployed page from a terminal', 'curl -fsSI http://localhost:8765/microverse/'),
]

def connect():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=5000')
    return db

def init():
    for p in (ROOT, ROOT/'skills', WEB, WEB/'data', WEB/'projects', WEB/'music'):
        p.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS feeds(id INTEGER PRIMARY KEY, title TEXT, url TEXT UNIQUE, active INTEGER DEFAULT 1, last_ok TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY, feed_id INTEGER, guid TEXT, title TEXT, url TEXT, published TEXT, seen TEXT, UNIQUE(feed_id,guid));
        CREATE TABLE IF NOT EXISTS projects(slug TEXT PRIMARY KEY, kind TEXT, created TEXT, path TEXT);
        CREATE TABLE IF NOT EXISTS skills(slug TEXT PRIMARY KEY, description TEXT, recipe TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT, kind TEXT, detail TEXT);
        CREATE INDEX IF NOT EXISTS idx_entries_feed ON entries(feed_id,id);
        ''')
        for label, url in DEFAULT_FEEDS:
            db.execute('INSERT OR IGNORE INTO feeds(title,url) VALUES(?,?)', (label,url))
        for name,description,recipe in SKILLS:
            db.execute('INSERT OR IGNORE INTO skills VALUES(?,?,?,?)',(name,description,recipe,NOW()))

def event(kind, detail):
    with connect() as db:
        db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',(NOW(),kind,str(detail)[:350]))
        db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 600)')

def json_write(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(path)

def safe_slug(name):
    slug = re.sub(r'[^a-z0-9-]+','-',name.lower()).strip('-')[:45]
    if not slug: raise ValueError('Provide a project/skill name with letters or digits')
    return slug

def text_of(element, *names):
    for child in element:
        if child.tag.rsplit('}',1)[-1] in names:
            return ' '.join(''.join(child.itertext()).split())
    return ''

def parse_feed(blob):
    root=ET.fromstring(blob)
    result=[]
    for node in root.iter():
        if node.tag.rsplit('}',1)[-1] not in ('item','entry'): continue
        title=text_of(node,'title')[:220]
        link=text_of(node,'link')
        for el in node:
            if el.tag.rsplit('}',1)[-1]=='link' and el.attrib.get('href'):
                link=el.attrib['href'];break
        ident=text_of(node,'id','guid') or link or title
        if not title or not ident: continue
        if not (link.startswith('https://') or link.startswith('http://')): link=''
        result.append(dict(guid=ident[:400],title=title,url=link[:600],published=text_of(node,'published','updated','pubDate')[:60]))
    return result[:40]

def valid_https(url):
    u=urlparse(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password:
        raise ValueError('Only public https:// feed URLs are accepted')
    return url

def add_feed(label,url):
    valid_https(url)
    with connect() as db:
        db.execute('INSERT INTO feeds(title,url) VALUES(?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title, active=1', (label[:90],url[:800]))
    event('FEED_ADDED',label)
    export()
    print(f'FEED_ADDED {label}: {url}')

def fetch_feeds(online=True):
    inserted=0;checked=0
    if not online: return checked,inserted
    with connect() as db:
        feeds=db.execute('SELECT * FROM feeds WHERE active=1 ORDER BY id LIMIT 12').fetchall()
    for feed in feeds:
        checked+=1
        try:
            req=urllib.request.Request(feed['url'],headers={'User-Agent':'LS-Microverse/1.0 (self-hosted RSS reader)','Accept':'application/atom+xml,application/rss+xml,application/xml,text/xml,*/*'})
            with urllib.request.urlopen(req,timeout=8) as res:
                blob=res.read(240_000)
            rows=parse_feed(blob)
            with connect() as db:
                for r in rows:
                    before=db.total_changes
                    db.execute('INSERT OR IGNORE INTO entries(feed_id,guid,title,url,published,seen) VALUES(?,?,?,?,?,?)',
                               (feed['id'],r['guid'],r['title'],r['url'],r['published'],NOW()))
                    inserted+=db.total_changes-before
                db.execute('UPDATE feeds SET last_ok=?,error=NULL WHERE id=?',(NOW(),feed['id']))
        except Exception as err:
            with connect() as db:
                db.execute('UPDATE feeds SET error=? WHERE id=?',(str(err)[:160],feed['id']))
    event('INGEST', f'feeds={checked} new={inserted}')
    return checked,inserted

def music_index():
    results=[]
    for f in sorted((WEB/'music').iterdir()):
        if not f.is_file() or f.is_symlink() or f.suffix.lower() not in ('.mp3','.ogg','.opus','.wav','.m4a','.flac'):
            continue
        results.append(dict(title=f.stem[:120],file=f.name,bytes=f.stat().st_size))
    return results[:400]

def catalog_live(online=False):
    items=[]
    for label,cat,url,desc in CATALOG:
        row=dict(name=label,category=cat,url=url,description=desc)
        if online and url.startswith('https://github.com/'):
            repo=url.removeprefix('https://github.com/').strip('/')
            try:
                req=urllib.request.Request(f'https://api.github.com/repos/{repo}',headers={'Accept':'application/vnd.github+json','User-Agent':'LS-Microverse/1.0'})
                with urllib.request.urlopen(req,timeout=5) as resp:
                    body=json.loads(resp.read(100_000))
                row.update(stars=body.get('stargazers_count'),archived=body.get('archived'),updated=body.get('pushed_at'))
            except Exception: pass
        items.append(row)
    return items

def export(catalog_scan=False):
    init()
    with connect() as db:
        feeds=[dict(r) for r in db.execute('SELECT * FROM feeds ORDER BY id')]
        entries=[dict(r) for r in db.execute('SELECT entries.title,entries.url,entries.seen,feeds.title AS source FROM entries JOIN feeds ON entries.feed_id=feeds.id ORDER BY entries.id DESC LIMIT 70')]
        projects=[dict(r) for r in db.execute('SELECT * FROM projects ORDER BY created DESC LIMIT 100')]
        skills=[dict(r) for r in db.execute('SELECT * FROM skills ORDER BY slug')]
        events=[dict(r) for r in db.execute('SELECT at,kind,detail FROM events ORDER BY id DESC LIMIT 20')]
    # Keep previous upstream metadata unless explicitly re-scanned.
    catalog_file=WEB/'data/catalog.json'
    catalog=catalog_live(catalog_scan) if catalog_scan or not catalog_file.exists() else json.loads(catalog_file.read_text())
    json_write(catalog_file,catalog)
    json_write(WEB/'data/state.json', dict(updated=NOW(),feeds=feeds,entries=entries,projects=projects,skills=skills,events=events,music=music_index()))
    return len(entries),len(projects),len(music_index())

SITE_TEMPLATE = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font-family:system-ui;background:#0d1523;color:#e6edf8;max-width:780px;margin:80px auto;padding:25px}}article{{background:#151f30;border:1px solid #38465f;border-radius:20px;padding:36px}}a{{color:#8bd6ff}}button{{background:#5dbdff;border:0;border-radius:9px;padding:10px 16px;cursor:pointer}}</style>
<article><small>LS MICROVERSE / {kind}</small><h1>{title}</h1><p>Generated locally. No npm, frontend framework, hosting account, or build service.</p><button onclick="document.getElementById('result').textContent='BUILD ONLINE · '+new Date().toLocaleTimeString()">Test button</button><p id="result"></p><p><a href="../../">Back to Microverse</a></p></article>'''
GAME_TEMPLATE = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — Game</title><style>body{{font:18px system-ui;background:#090e1a;color:#e5eeff;max-width:550px;margin:8vh auto;padding:18px;text-align:center}}button{{border:0;border-radius:14px;padding:15px;margin:7px;background:#2d83f0;color:white;font:inherit;cursor:pointer}}#target{{font-size:70px;margin:30px;display:block}}</style><h1>{title}</h1><p>Catch the pulse — click when it turns green.</p><div id="target">●</div><button id="go">Start</button><h2 id="score">Best: 0 ms</h2><a href="../../" style="color:#80d7ff">Microverse</a><script>let start=0,timer,ready=false,best=Infinity;const t=document.querySelector('#target'),g=document.querySelector('#go'),s=document.querySelector('#score');g.onclick=()=>{{ready=false;t.style.color='tomato';t.textContent='●';g.textContent='Wait...';clearTimeout(timer);timer=setTimeout(()=>{{ready=true;start=performance.now();t.style.color='#69ecb6';g.textContent='CLICK!'}},700+Math.random()*2200)}};t.onclick=()=>{{if(!ready)return;ready=false;const ms=Math.round(performance.now()-start);best=Math.min(best,ms);s.textContent=`${{ms}} ms · Best: ${{best}} ms`;g.textContent='Again'}};</script>'''

def create_project(name,kind):
    if kind not in ('site','game','dashboard'):raise ValueError('Available kinds: site, game, dashboard')
    slug=safe_slug(name)
    out=WEB/'projects'/slug
    if out.exists():
        raise ValueError(f'Already exists: {slug}; choose another name')
    out.mkdir(parents=True)
    import html
    page=(GAME_TEMPLATE if kind=='game' else SITE_TEMPLATE).format(title=html.escape(name[:90]),kind=kind)
    (out/'index.html').write_text(page,encoding='utf-8')
    with connect() as db:
        db.execute('INSERT INTO projects VALUES(?,?,?,?)',(slug,kind,NOW(),f'projects/{slug}/'))
    event('PROJECT_CREATED',f'{slug} ({kind})')
    export()
    print(f'PROJECT_READY /microverse/projects/{slug}/')

def skill_new(name,description,recipe):
    slug=safe_slug(name)
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO skills VALUES(?,?,?,?)',(slug,description[:240],recipe[:400],NOW()))
    p=ROOT/'skills'/f'{slug}.md'
    p.write_text(f'# {name}\n\n{description}\n\n## Recipe\n\n```sh\n{recipe}\n```\n',encoding='utf-8')
    event('SKILL_SAVED',slug)
    export()
    print(f'SKILL_SAVED {p}')

def refresh(offline=False,discover=False):
    checked,added=fetch_feeds(not offline)
    entries,projects,music=export(discover and not offline)
    print(f'REFRESH feeds={checked} new={added} entries={entries} projects={projects} music={music}')

def status():
    init()
    with connect() as db:
        for table in ('feeds','entries','projects','skills','events'):
            print(f'{table.upper():<11} {db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]}')
        print('SQLITE     '+db.execute('PRAGMA integrity_check').fetchone()[0])
    print('MUSIC      '+str(len(music_index())))
    print('PUBLIC     '+str(WEB))

def selftest():
    init()
    atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>Video one</title><link href="https://example.org/1"/></entry></feed>'
    rss=b'<rss><channel><item><guid>a</guid><title>Post</title><link>https://example.org/2</link></item></channel></rss>'
    assert parse_feed(atom)[0]['url']=='https://example.org/1'
    assert parse_feed(rss)[0]['title']=='Post'
    assert safe_slug('Hello World')=='hello-world'
    export()
    assert (WEB/'data/state.json').is_file()
    with connect() as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    print('PASS atom/rss parser | project slugs | JSON export | SQLite integrity')

def main():
    ap=argparse.ArgumentParser(prog='micro',description='Microverse - tiny site/game/ingestion factory')
    sub=ap.add_subparsers(dest='cmd')
    sub.add_parser('init');sub.add_parser('status');sub.add_parser('music');sub.add_parser('test')
    p=sub.add_parser('refresh');p.add_argument('--offline',action='store_true');p.add_argument('--discover',action='store_true')
    p=sub.add_parser('new');p.add_argument('name');p.add_argument('kind',nargs='?',default='site')
    p=sub.add_parser('feed');p.add_argument('action',choices=('add','list'));p.add_argument('url',nargs='?');p.add_argument('--name',default='Custom feed')
    p=sub.add_parser('youtube');p.add_argument('channel_id')
    p=sub.add_parser('skill');p.add_argument('action',choices=('add','list'));p.add_argument('name',nargs='?');p.add_argument('description',nargs='?');p.add_argument('recipe',nargs='?')
    args=ap.parse_args();init()
    try:
        if args.cmd=='init':
            for name,kind in (('Orbit Notes','site'),('Pulse Lab','dashboard'),('Reflex Lab','game')):
                if not (WEB/'projects'/safe_slug(name)).exists():create_project(name,kind)
            refresh(offline=True)
        elif args.cmd=='status':status()
        elif args.cmd=='test':selftest()
        elif args.cmd=='refresh':refresh(args.offline,args.discover)
        elif args.cmd=='new':create_project(args.name,args.kind)
        elif args.cmd=='music':export();print('Place your own .mp3/.ogg/.wav/.m4a in '+str(WEB/'music'))
        elif args.cmd=='feed':
            if args.action=='add':
                if not args.url:raise ValueError('Usage: micro feed add https://feed.example/rss')
                add_feed(args.name,args.url)
            else:
                with connect() as db:
                    for row in db.execute('SELECT title,url,coalesce(last_ok,"never"),coalesce(error,"") FROM feeds'):
                        print(' | '.join(map(str,row)))
        elif args.cmd=='youtube':
            cid=args.channel_id
            if not re.fullmatch(r'UC[A-Za-z0-9_-]{20,40}',cid):raise ValueError('Provide a YouTube channel ID starting with UC')
            add_feed('YouTube '+cid,'https://www.youtube.com/feeds/videos.xml?channel_id='+cid)
        elif args.cmd=='skill':
            if args.action=='list':
                with connect() as db:
                    for row in db.execute('SELECT slug,description,recipe FROM skills'):
                        print(' | '.join(map(str,row)))
            else:
                if not all((args.name,args.description,args.recipe)):raise ValueError('Usage: micro skill add NAME "What it does" "recipe command"')
                skill_new(args.name,args.description,args.recipe)
        else:ap.print_help()
    except (ValueError,OSError,sqlite3.Error) as exc:
        print(f'ERROR {exc}',file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()