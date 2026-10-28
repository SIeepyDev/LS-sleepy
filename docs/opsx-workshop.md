# LS OpsX — Atomic Operations Atelier

Source: `scripts/opsx.py` + `scripts/install-opsx.sh`.
Target: Debian-based hosts including Proxmox VE. No account, external database, web framework or Python package installation.

## Existing stack integration

- Reuses the Conquer static web service when `/opt/ls-conquer/www` exists.
- Stores everything under `/opt/ls-workshop`.
- Adds independent `opsx` command; no replacement of `conquer`, `factory`, `crew`, `arena` or `micro`.
- Uses SQLite WAL for history, inventory, metrics, project receipts and checkpoint manifests.

## Command map

| Command | Effect |
|---|---|
| `opsx` | host facts, bundles, projects, dashboard, recent receipts |
| `opsx next` | next high-leverage commands |
| `opsx catalog` | inspect 43 bundle candidates |
| `opsx bundle list` | list eight bundles |
| `opsx bundle builder` | install missing APT packages in builder bundle |
| `opsx bundle discover` | install search, configuration and log explorers |
| `opsx apt scan` | APT metadata refresh and simulated full-upgrade plan |
| `opsx apt plan` | simulated full-upgrade, no install |
| `opsx apt install PKG` | install specified package (explicit) |
| `opsx apt remove PKG` | show planned removals, no install/removal |
| `opsx apt remove PKG --apply` | remove package after protected-package check |
| `opsx apt prune` | simulate autoremove |
| `opsx apt prune --apply` | autoremove after protected-package check |
| `opsx apt upgrade` | simulate full-upgrade; blocks actual removal of packages |
| `opsx apt upgrade --apply` | full-upgrade only if plan removes no packages |
| `opsx apt audit` | dpkg audit and apt check |
| `opsx apt repair --apply` | dpkg configuration and apt dependency repair |
| `opsx new arcade game` | create playable mini-game and publish to Conquer |
| `opsx new blueprints site` | generate static mini-site + Makefile |
| `opsx new LAB pipeline` | create tiny scaffold |
| `opsx skill example` | create self-contained editable shell skill + documentation |
| `opsx skills` | list local skills |
| `opsx roles` | six specialized non-AI operational roles |
| `opsx theme aurora` | switch dashboard aesthetics |
| `opsx db` | database integrity and table counts |
| `opsx checkpoint` | capture package list, service failures, LXC list and DB backup |
| `opsx sync /mnt/backup/opsx` | checkpoint and rsync to mounted folder; no deletion |
| `opsx schedules` | view LS systemd worker schedules |
| `opsx history` | recent actions and outcomes |

## Automatic cycles

- `ls-opsx-probe.timer`: every 20 minutes — lightweight host resource measurements and refreshed static dashboard.
- `ls-opsx-scan.timer`: daily ~03:15, randomized up to 15 minutes — APT metadata/catalog updates, NOT package upgrades.
- `ls-opsx-checkpoint.timer`: daily 03:40 — local package/host/SQLite snapshot.

The timers exit after completion; there is no new long-running daemon.

## Live pages after installation on known T530 Conquer host

- `http://192.168.1.236:8765/opsx/`
- `http://192.168.1.236:8765/opsx/projects/clicklab/`
- `http://192.168.1.236:8765/opsx/projects/launchpad/`

These are expected URLs based on a prior known LAN address. Confirm from actual installer output because IP or Conquer port may change.

## Evidence & operational scope

Tested locally: Python syntax, isolated database, full CRUD of projects/skills, Makefile assertions, themes, SQLite checkpoint+integrity, APT preview. Host installation and actual APT changes not yet tested on T530.

Host scope: Debian and Proxmox VE APT. No cross-distribution package installer, remote fleet SSH sync, live Google Calendar integration, active load balancer or arbitrary untrusted code runner in v1. No claim of those features.

Proxmox's own documentation recommends `apt update` + `apt full-upgrade`; `apt upgrade` can leave partial upgrade state, and full-upgrade can remove packages. This toolkit simulates first and refuses protected removals to avoid accidental damage to a running hypervisor.