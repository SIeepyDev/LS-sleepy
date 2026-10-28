# LS Atomic Arena — T530 micro-worker lab

Status: SOURCE COMMITTED / LOCAL TESTED / T530 RUNTIME PENDING
Date: 2026-10-28
Branch: feature/atomic-conquer-v1
Source: scripts/ls-arena.sh

## What it does

Four short-lived workers in a deterministic pipeline:
1. SCOUT — discover 20 local command capabilities and read Proxmox LXC inventory when available.
2. FORGE — generate a zero-framework website and a Makefile-built micro-prototype.
3. RUNNER — check JSON, SQLite, script syntax, build, dashboard, prototype, and optionally Proxmox and local HTTP.
4. ARCHIVIST — store SQLite cycle/check/collision history and SHA-256 receipt.

A small systemd timer runs a cycle every 30 minutes. No AI, hosted account, external API key, Docker daemon, or continuous polling process. Existing Conquer dashboard and units stay unchanged.

14 capability pairings are rotated with recorded integer seeds. Use 'arena go 42' to replay the same selection.

## Install on an existing LS Conquer machine

```sh
curl -fsSLo /tmp/ls-arena.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/atomic-conquer-v1/scripts/ls-arena.sh
bash -n /tmp/ls-arena.sh && bash /tmp/ls-arena.sh install
```

## Commands

```sh
arena eyes       # 4 tmux panes, supports existing tmux clients
arena go 42      # reproducible experiment
arena spin 5     # 5 varied runs
arena ideas      # 14 combinations and readiness
arena score      # SQLite history
arena lanes      # last 5 lines per worker
arena on         # periodic experiments
arena off        # disable timer, preserve receipts
```

View on a host already serving Conquer port 8765: http://HOST:8765/arena/

## Evidence

Local test (separate Debian execution container, 2026-10-28):
- bash -n passed
- worker pipeline completed
- 6 local checks passed, 0 failed (json, sqlite, shell, build, page, prototype)
- 14 recipes cataloged, 5 selected per cycle
- SQLite tables cycles/checks/collisions populated and receipt hash generated
- Host-specific Proxmox and live HTTP checks pending T530 execution

Runtime on the user's T530 is NOT verified until that host runs the installer and reports outcomes.

## Safety / operational boundary

No container is automatically created, stopped, deleted, or changed. The Proxmox interface is read-only in this version. The timer is enabled by the installer. The web page is static and served by the already-running Conquer HTTP listener. No credentials or secrets required.

To retire: `arena off` disables new cycles; preserve /opt/ls-conquer/arena/history.sqlite and /opt/ls-conquer/arena/runs for history.
