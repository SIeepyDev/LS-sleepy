# LS Empire v1 — Cities, Guilds, Policies, Treasury, Factories

A bounded, stdlib-only coordination layer for an existing Debian/Proxmox Conquer host. One SQLite database, one systemd oneshot timer, no new web server, no accounts, no AI.

## Installation

`curl -fsSLo /tmp/empire.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/empire-controller-v1/scripts/install-empire.sh && bash -n /tmp/empire.sh && bash /tmp/empire.sh`

## Commands

- `empire` / `empire status` — registry totals
- `empire cities` / `empire guilds` / `empire projects` — inventory
- `empire registry` — discover which prior LS tools actually exist on the host
- `empire city nebula sandbox` — establish a city with region budget + policies
- `empire guild cartographers research` — register a specialist role
- `empire new nebula atlas city` — create a browser-city project
- `empire new beach reaction arcade` — create a mini-game
- `empire new workshop status infra` — create a micro infra site
- `empire build nebula atlas` — enqueue, build, test, publish with SHA evidence
- `empire queue beach reaction` / `empire tick` — batch two concurrent pipelines
- `empire policy beach publish deny` — block publishing in the Beach region
- `empire challenge` — run four policy/namespace assertions
- `empire grant beach 10` — explicitly grant 10 simulated compute credits (not real money)
- `empire ledger` — list compute-credit budget transactions
- `empire ideas` — list 12 deterministic city/guild concept collisions
- `empire checkpoint` — atomic SQLite backup, SHA-256, quick-check, 7-backup retention
- `empire merge-audit` — audit legacy LS timers; does not delete services
- `empire pause` / `empire resume` — control scheduled production
- `empire jobs` / `empire events` — inspect detailed job results and audit events

## On first install

Generates three live mini-pages: Beach Sandcastle reaction arcade, Workshop Command City infra page, and Workshop Garden City interactive city builder. They are available at `/empire/apps/<city>/<name>/` under the existing Conquer web server.

## Autonomous work

A systemd oneshot timer runs every ~15 minutes and exits. It inventories installed tools and machine capacity; may create at most one deterministic starter project per UTC day; caps total projects at 30; runs at most 2 concurrently; maintains finite compute credits and daily SQLite checkpoints. It never installs or runs downloaded code, mutates Proxmox guests, or silently upgrades the host.

## Verification scope

Engine tested locally with SQLite integrity check, project generation and static publishing. Actual T530 installation requires the provided one-liner and is not yet confirmed.