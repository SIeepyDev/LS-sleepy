# LS ∞ GOVERN — bounded autonomous multi-policy control

**Engine:** Python standard library + SQLite WAL + systemd timer; publishes static UI through the existing Conquer BusyBox HTTP server. No AI, API key, npm, container daemon, or separate database service.

## Three-layer governance

1. Constitution: immutable built-in execution limits (no arbitrary host command execution or modification of existing LXCs).
2. Regions: `citadel` (read-only), `workshop` (prototyping), `beach` (sandbox-oriented), `anarchy` (permissive approved built-ins; still constitution-bound).
3. Work receipts: every permission, build, test, publish, sandbox and policy decision is recorded to SQLite.

## One-paste installation

```sh
curl -fsSLo /tmp/govern.sh https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/policy-govern-v1/scripts/install-govern.sh && bash -n /tmp/govern.sh && bash /tmp/govern.sh
```

## Commands

- `gov` — status / resource-budgeted worker slots
- `gov constitution` — immutable operational boundaries
- `gov policy list` — permissions of each region
- `gov policy deny beach publish` — revoke permission (recorded)
- `gov policy permit beach publish` — grant an approved built-in action (recorded)
- `gov mode beach anarchy` — change sandbox region mode; no root bypass
- `gov council` — governing decisions & published projects
- `gov challenge` — simulated policy-break attempts, no destructive execution
- `gov world galaxy beach` — create a playable static project through BUILD → TEST → PUBLISH
- `gov add inspect system citadel` — queue host probe
- `gov tick` — execute next bounded batch; dependency-aware
- `gov jobs` / `gov events` / `gov ideas` — evidence and new ideas
- `gov checkpoint` — SQLite backup, SHA-256 integrity, retention of newest 10
- `gov jail probe` — inspect native Proxmox LXC availability
- `gov jail new` — create a tiny **unprivileged, no-network** Alpine LXC from an existing cached template, 1 core, 256MB RAM, 2GB rootfs, onboot=0, tagged `ls-govern;sandbox`
- `gov jail start VMID` / `gov jail test VMID` / `gov jail stop VMID` / `gov jail retire VMID` — manage **only** identity-verified GOV-created LXCs

Production services, unrelated LXCs and existing network settings are not modified. The program does not run downloaded third-party source code on the Proxmox host.

## Autonomous loop

The five-minute systemd cycle automatically queues a generated micro-world daily (up to 60 retained project identities), selects jobs by RAM/load/disk, builds, validates SHA-256, publishes through an independent second verification gate, and logs every outcome. Dependency order is guaranteed even when workers run concurrently. A second timer backs up SQLite daily.

## Local tested gates

Syntax; policy allow/deny and immutable boundaries; SQLite integrity; three projects through all three pipeline stages; output HTML; policy edits; project mode changes; checkpoint SHA-256; graceful no-Proxmox response. No remote LXC test has been performed.
