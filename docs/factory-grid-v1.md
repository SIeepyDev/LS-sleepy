# LS Factory Grid v1 — recursive micro-worker engine

**State:** Built, locally runtime-tested, GitHub readback verified; deployment to T530 pending.
**Target:** Debian 13 / Proxmox VE T530, independent of existing Conquer/Arena/Memory.
**Branch:** feature/recursive-factory-v1.

## Install
```sh
curl -fsSLo /tmp/factory.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/recursive-factory-v1/scripts/install-factory.sh
bash -n /tmp/factory.sh && bash /tmp/factory.sh
```

## Architecture
Kernel (generation 0) -> intake/builder/verifier/archivist (1) -> micro-worker templates (2) -> combined descendants (3). Every generated worker is saved as a concrete Python executable and tested by subprocess, with timing + success/failure receipts.

No untrusted RSS code is ever executed. External fuel consists of item titles, links and summaries only. A failed test is marked FAILED or DEGRADED. Repeated checks update running scores.

**Bounds:** 3 generations, 40 maximum design nodes, 4 build/tests per cycle, 2 recurring worker checks/cycle, 3 initial RSS sources, 4 fetched sources/cycle, 12 source registrations maximum, 5s network timeout/source, 300KB/source. Retain newest 800 execution receipts, 720 cycles, 2000 fuel records, 14 SQLite snapshots. Installer caps service memory to 256MB and CPU to 75% of a core, runs every ~20 minutes plus jitter.

## Commands
- `factory`, `factory status` — current states
- `factory offline 5` — run 5 generations/rounds without network
- `factory cycle 1` — local inventory + RSS intake + build/test/re-score
- `factory tree`, `factory workers`, `factory receipts` — inspect lineage and evidence
- `factory ideas` — built-in recipe combinations
- `factory sources` — source status
- `factory add https://github.com/systemd/systemd/releases.atom` — register a public RSS/Atom source
- `factory ingest /path/to/text-file` — locally index file lines into durable fuel
- `factory search sqlite` — search collected sources
- `factory tokens /path/to/file` — rough character-based token budget (**not exact BPE/LLM tokens**)
- `factory snapshot` — SQLite consistent backup (hash receipt)
- `factory test` — local functional checks

## Files
`/opt/ls-factory/factory.sqlite` — live knowledge/receipts; `/opt/ls-factory/workers` — generated child scripts; `/opt/ls-factory/receipts` — machine-readable test results; `/opt/ls-factory/www` — static, read-only dashboard; `/opt/ls-factory/snapshots` — daily backups; `/opt/ls-factory/port` — selected available port (8770–8779).

## Systemd
- `ls-factory-cycle.timer` / `ls-factory-cycle.service` — unattended intake and experiment cycles
- `ls-factory-snapshot.timer` / `ls-factory-snapshot.service` — daily SQLite backup
- `ls-factory-web.service` — BusyBox HTTPD serving read-only LAN dashboard as nobody

## Validation evidence
Local clean-room 6-round run: 20 nodes created (1 kernel + 19 descendants); 19 generated executable workers passed individual tests; 0 failures. End-to-end parsing, DB integrity, generation bounds, SHA-256, receipt creation, search, text ingestion, token estimation, snapshot, command discovery and persistent reruns tested with an alternate root directory. Footprint after one test pass ~376 KB (runtime files only, no package dependencies); T530 measurements pending.

## Current limits
No auto-creation of LXCs, no cloning random internet code, no automatic upgrades, and no magical AI learning. 'Learning' here means empirical scoring, deduplication, live source ingestion, and incremental recipe selection. Growth is intentionally bounded instead of runaway recursive container creation. For real CI/CD, integrate a separate sandboxed LXC runner after host deployment is measured.
