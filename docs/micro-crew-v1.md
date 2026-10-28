# LS Micro Crew v1

A self-contained non-AI, bounded multi-project operations engine for the existing Proxmox T530 installation. 30 KB Python standard-library engine, Bash installer, SQLite WAL receipts and two systemd units with timers/path triggers. It reuses the existing Conquer HTTP server when available. No account, API key, Docker, Node or separate database daemon.

## Install

```sh
curl -fsSLo /tmp/crew-install.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/micro-crew-v1/scripts/install-crew.sh && bash -n /tmp/crew-install.sh && bash /tmp/crew-install.sh
```

The installer checks a fixed SHA-256 for the downloaded Python engine. No existing Conquer, Factory or Arena units are overwritten.

## Immediately useful commands

```
crew eyes                          # 4 live tmux panes: status/jobs/research/projects
crew project list                  # installed project recipes
crew jobs                          # build/test/deploy/archive evidence
crew project new notes lab         # create a new template project
crew pipeline notes && crew run    # build, validate, deploy and preserve it
crew search 'tiny sqlite' --engine github
crew search 'proxmox lxc' --engine hn
crew fuel                          # recent fetched research
crew sources                       # RSS source list
crew cycle --online                # manually intake/produce/test/backup
crew submit pipeline notes         # asynchronous inbox job
crew submit research 'micro ci'    # asynchronous web research
crew stats                         # summary
crew backup                        # SQLite checkpoint
crew sync /mnt/backup set          # enable future snapshot+receipt syncing to existing dir
crew sync /mnt/backup              # immediate one-way copy, no deletion
crew route 'research Caddy'        # inspect router intent
```

## What is real / what is not

- Verified offline: parallel job execution, 4 stages per project, failure propagation, SQLite backups, RSS parsing/dedup, local sync, project page generation.
- Background systemd cycle is created at 12 minute intervals and an inbox watcher reacts to JSON requests.
- For online research, sources are public GitHub Atom feeds, Hacker News Algolia and unauthenticated GitHub repository search. These have rate limits, sometimes errors, and are not full-text search engines.
- Deploy stage copies **generated static prototype pages** into `/crew/apps/<project>/`. It does not run untrusted GitHub code, compile external projects, configure actual LXC services, deploy to production, or provision a network load balancer in v1.
- Dynamic concurrency: 1–4 workers depending on available RAM/load. systemd caps the scheduled worker to 384 MB and 1 CPU worth of quota.
- Auto snapshots and optional rsync copy existing receipts. No destructive remote file synchronization.

## Files

- `/opt/ls-crew/crew.sqlite` — projects/jobs/events/feeds
- `/opt/ls-crew/receipts` — artifact SHA receipts, inventories
- `/opt/ls-crew/snapshots` — SQLite backups, keeps 14 newest
- `/opt/ls-crew/inbox` — event-driven JSON job requests
- `/opt/ls-crew/processed` — received requests
- `/opt/ls-conquer/www/crew` — live read-only dashboard when Conquer is available

## Runtime tests

Run `crew test`, followed by `crew jobs`, `crew stats`, `curl -I http://127.0.0.1:$(cat /opt/ls-crew/port)/crew/` on the Conquer host. Inspect systemd with `systemctl list-timers --all | grep ls-crew`.

## Design constraint

This engine is light orchestration, not a replacement for full CI, OS-level isolation or real Kubernetes/autoscaling. Use a dedicated Proxmox LXC for executing arbitrary downloaded builds. Avoid spending 12 GB of RAM on many always-on services when event-driven tasks can do the same work.
