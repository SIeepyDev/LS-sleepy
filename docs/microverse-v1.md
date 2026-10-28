# LS Microverse — Tiny game, site, feed and skills factory

- Dependencies: Python3 standard library and existing LS Conquer BusyBox HTTPD; SQLite is embedded in Python3.
- No npm, Node.js, Docker, login, AI key, or separate database server.
- Hosted at `http://T530-IP:CONQUER-PORT/microverse/` with zero additional web processes.
- 3 custom, browser-playable games: Snake, Memory Match, Reaction Lab; scores saved locally.
- 3 generated projects on first install: Orbit Notes, Pulse Lab, Reflex Lab. Generate more site/game/dashboard pages.
- Public RSS/Atom watcher including GitHub release feeds, anime schedule feed, and YouTube channel feed by channel ID.
- Free candidate catalog, optional public GitHub repository metadata, local-file jukebox, recipe/skill index, bookmark dock.
- SQLite persistence for feeds, entries, projects, recipes and events; read-only JSON output consumed by the browser.
- Lightweight systemd one-shot timer every ~30 minutes, not a permanent polling process.

## Install on existing Conquer host

```sh
curl -fsSLo /tmp/microverse.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/microverse-v1/scripts/install-microverse.sh && bash -n /tmp/microverse.sh && bash /tmp/microverse.sh
```

## Commands

```sh
micro status
micro refresh               # fetch public RSS + index media
micro refresh --offline     # regenerate everything without internet
micro refresh --discover    # also query public GitHub repository metadata
micro new nebula game       # self-contained mini-game site
micro new lighthouse site   # new standalone microsite
micro new observatory dashboard
micro youtube UC...         # add a YouTube channel Atom feed by channel ID
micro feed add https://example.com/feed.xml --name MyFeed
micro feed list
micro music                 # scan own music in the dedicated public music folder
micro skill list
micro skill add my-recipe 'Description' 'test command'
micro test
```

## Boundaries

The music directory is intentionally available to everyone who can reach the Conquer LAN site. Put only media you own or have permission to share there. Web feeds store titles, URLs and timestamps, not third-party videos/music. Source catalog entries are candidates, not installed apps. Generated pages are static prototypes, not fully featured media clients, AI systems, or a new browser engine. Because there is no login, keep the Conquer service on a trusted LAN or behind your existing access controls; do not publicly forward the port.