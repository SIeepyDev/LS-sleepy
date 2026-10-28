# LS ∞ Facilities v1 — atomic departments

A tiny Python-standard-library + SQLite CLI extending LS Conquer on Debian/Proxmox. No new web daemon, account, containers, or JavaScript build tools.

## Install

```sh
curl -fsSLo /tmp/fac-install.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/atomic-facilities-v1/scripts/install-facilities.sh && bash -n /tmp/fac-install.sh && bash /tmp/fac-install.sh
```

## Commands

- `fac` — current system status; `fac glasses` — Proxmox + host overview
- `fac clock`, `fac resources`, `fac storage`, `fac services`, `fac ports`, `fac bathroom` — time, usage, storage, unit state, socket mapping, diagnostics
- `fac apt plan` — full-upgrade simulation; `fac apt install jq` — installation simulation; add `--apply` to explicitly run install; `fac apt upgrade --apply` for upgrade with removal-blocking; `fac apt update --apply` to refresh metadata
- `fac kitchen new demo game` — generate static mini-game; `fac oven demo` — run tests; `fac stove demo` — publish it under existing Conquer server
- `fac water add https://github.com/community-scripts/ProxmoxVE/releases.atom`; `fac water refresh` — ingest RSS/Atom metadata, deduplicated in SQLite
- `fac universe 10 530` — deterministic concepts combining roles/objects/mechanisms (ideas, not deployed solutions)
- `fac skill list`; `fac skill new myprobe glasses`; `fac skill run myprobe` — reusable allowlisted atomic recipes
- `fac headphones /srv/media` — catalog local audio (index only, not a streamer)
- `fac microwave` — local smoke tests; `fac burner` — bounded hash benchmark
- `fac porter` — list project deployment paths; `fac sink` — report cleanup candidates without deletion
- `fac search TERM` — search stored events, feed titles and ideas
- `fac checkpoint` — consistent SQLite backup; `fac db` — check SQLite integrity; `fac timers` — show timers
- `fac snapshot` — refresh static dashboard at `/facilities/`

The installer builds `forgeboard` and verifies/publishes its static site, seeds five reproducible ideas, and enables systemd: a 20-minute snapshot timer and hourly feed timer. Both are oneshot and release resources when complete. 

## Limits and provenance

Designed for Proxmox host use only with known local project templates. It does not spin up or take over LXCs, and never auto-executes content fetched from the web. APT writes only on explicit `--apply` and refuse transactions where dependencies would be removed (removal requests can only remove packages explicitly named and never core infrastructure). No `sudo` process needed when launched from root; on other users root permissions still apply. Static dashboard is read-only and intended only on a trusted network; it shares the existing Conquer port (e.g. 8765). No always-running worker was added. Feed collection is best effort.

Evidence states: locally tested for project generation, smoke tests, skill creation, scoring, SQLite integrity/backup, APT simulation, snapshot. Actual T530 installation and timer state await host output.