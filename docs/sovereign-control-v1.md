# LS ∞ Sovereign Control — Controller-of-Controllers v1

**Scope:** Debian/Proxmox host; integrates with existing `/opt/ls-conquer` and its static HTTP dashboard. Standard-library-only Python + SQLite WAL + one systemd oneshot/timer. No AI, no accounts, no Docker, no new web server.

## Controllers

| Controller | What it really does |
|---|---|
| INSPECTOR | Reads host memory, load, free disk, LXCs, failed services; logs fact changes |
| GOVERNOR | Derives 0–3 worker slots from live memory/disk/load; pauses dispatch under pressure |
| ROUTER | Creates a durable, bounded job queue; parallel dispatch, receipts, retries |
| HEALER | Cooldown-limited recovery of explicitly allowlisted Conquer web service; reconciles jobs interrupted by reboot |
| ARCHIVIST | Verifies and backs up the SQLite ledger; keeps latest 14 controller-owned backups |
| ADVISOR | Calculates actionable next steps from the actual host and queue |

Six logical controllers share one process when the timer fires. Jobs are bounded to predeclared actions. No subprocess remains running permanently after the cycle exits.

## Install

```sh
curl -fsSLo /tmp/sovereign.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/sovereign-control-v1/scripts/install-sovereign.sh && bash -n /tmp/sovereign.sh && bash /tmp/sovereign.sh
```

## Commands

```sh
ctrl                 # quick controller status
ctrl tick            # run all controller stages now
ctrl eyes            # 4 live tmux panes (status, jobs, facts, journal)
ctrl add storage     # enqueue a small one-off worker
ctrl add lxc mylab   # label a queued Proxmox inventory task
ctrl add probe       # queue Conquer probe
ctrl add hunt        # queue Conquer tool discovery
ctrl add factory     # explicitly queue Factory offline cycle
ctrl add crew        # explicitly queue Crew job runner
ctrl jobs            # durable job states / retry receipts
ctrl events          # recent decisions
ctrl facts           # machine data and governor decisions
ctrl checkpoint      # verified SQLite snapshot now
ctrl pause           # suspend scheduled cycles without removing timer
ctrl resume
ctrl queue-off       # stop dispatch, keep monitoring
ctrl queue-on
ctrl test            # basic local self-check
ctrl config          # current resource limits and repair allowlist
```

## Automation behavior

- Single `ls-sovereign-cycle.timer`: first run ~1m after boot, then every ~5m after completion.
- AUTO: read-only Proxmox inventory every ~30m, port scan every ~60m. They are skipped when their binaries aren't installed.
- AUTO: service restart only if `ls-conquer-web.service` is enabled **and failed**, with 60m cooldown.
- AUTO: cancel dispatch when free RAM drops below 768 MB, free disk <12%, or load/cpu is too high.
- AUTO: SQLite verified checkpoint daily, rotating only the 14 backups that this controller created.
- AUTO: interrupted read-only job receipts may be retried after 10m; external `crew`/`factory` actions become `UNCERTAIN`, never blindly replayed.
- MANUAL: `factory` and `crew` trigger work only when explicitly queued.
- NEVER: modifies running LXCs, changes SSH/firewall/network, upgrades APT, deletes projects, or touches Proxmox management services.

**Dashboard:** `<T530-IP>:<Conquer-port>/control/`, generally `http://192.168.1.236:8765/control/` if that IP/port remains assigned.

**Evidence:** v1 locally exercised: Python compile, shell syntax, fresh database, six-controller bootstrap, concurrent queue, controlled retries/recovery, SQLite checkpoint+integrity, pause/resume, generated HTML. T530 installation is not confirmed until command output is provided.