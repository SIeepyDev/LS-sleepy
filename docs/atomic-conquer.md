# LS ∞ CONQUER — Atomic Operations Lab

A lightweight Debian / Proxmox ops launcher. One root-shell paste installs an actively useful tool belt and starts four small jobs: live metrics/HTML dashboard, filesystem sorter, daily discovery catalog, and job queue.

## Install

```bash
curl -fsSLo /tmp/ls-conquer.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/atomic-conquer-v1/scripts/ls-conquer.sh && bash -n /tmp/ls-conquer.sh && bash /tmp/ls-conquer.sh
```

## Command surface

- `conquer` — probes host, refreshes the dashboard and displays summary.
- `conquer hunt` — ranks 35 real Debian packages and reports INSTALLED / AVAILABLE / UNAVAILABLE.
- `conquer expand` — installs the useful second-wave packages when available, preserving existing tools.
- `conquer jobs` — lists queued Task Spooler jobs.
- `conquer run sleep 3` — queues a task.
- `conquer labs` — lists Proxmox LXCs if this is a Proxmox host.
- `conquer logs` — recent event receipts.
- `conquer test` — functional smoke test (jq, SQLite, queue, dashboard).

## Built-in long-running usefulness

- Read-only lightweight local HTML dashboard on a free port from 8765–8769 (selected once; stored at `/opt/ls-conquer/port`). No auth, so use only on a trusted LAN.
- Every-minute metrics captured in SQLite and displayed in the dashboard.
- systemd.path activated inbox sorting with SHA256 receipts.
- Daily candidate discovery; package installation requires `conquer expand`.
- Reboot-persistent systemd units; does not touch other containers or the existing Forge.

## Files

- `/opt/ls-conquer/inbox` → classified `/opt/ls-conquer/sorted/*`.
- `/opt/ls-conquer/history.sqlite` → samples.
- `/opt/ls-conquer/reports/` → inventory and package catalog.
- `/opt/ls-conquer/logs/` → events and file SHA256 receipts.

## Evidence and limitations

- Script syntax checked, core functions `hunt`, `probe` and `sort` tested in an isolated Linux container with SQLite CLI shim, valid HTML generated.
- Full `apt`/systemd/runtime is NOT tested on the user's Acer or ThinkPad; the install command runs acceptance checks there. Docker, Proxmox LXC creation and network setup are deliberately not assumed.
- Only Debian + systemd supported. Root required. Local read-only web UI should not be exposed to the public internet.