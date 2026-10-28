# LS ∞ ATLAS — Quality Forge v1

A small, Python-standard-library-only stage, challenge, inventory and signal engine for the Debian/Proxmox T530. No new web server, Node/Docker runtime or cloud API. Reuses Conquer static web root if present.

## Run

```sh
atlas map           # Full TOC + stage dashboard
atlas status        # All known projects and source states
atlas scan          # Import fingerprints of Empire/Crew/etc read-only
atlas new zen arcade
atlas upgrade zen   # Exactly one audited stage transition
atlas challenge zen moonshot
atlas verify zen    # Static checks only; browser is unverified
atlas atoms         # Reusable versioned components
atlas terms         # Literal/metaphor dictionary
atlas signals       # Event receipts and alerts
atlas bell          # Audible local terminal signal if warning exists
atlas next          # Next candidate for upgrading
atlas watch         # Compare published checksums
atlas checkpoint    # Integrity-checked database backup
atlas pause         # Pause scheduler actions
atlas resume
atlas cycle         # One bounded autonomous step
```

## Delivery gates

PLACEHOLDER → BUILT → HARDENED → POLISHED → VERIFIED (source-level only) → SHIPPED → WATCHED.

- Maximum 2 low-stage own prototypes simultaneously.
- Source checks cover SHA, small size, basic responsive/semantic/accessibility markers, offline dependencies, tokens, local storage code, deterministic output. These are **source-level**, not proof of browser correctness.
- Imported projects stay OBSERVED; never modified. The *impossible* challenge stays OPEN until measured browser/accessibility/reproducibility evidence is provided.
- Test and publish output is isolated to `/opt/ls-atlas` and `/opt/ls-conquer/www/atlas`.
- Watcher detects tampering and sends a local signal. No external notifications, credentials, package upgrades, or Proxmox host changes.
- Clock timer checks approximately every 15 min and advances at most one own project stage per cycle, without spawning background daemons.
- SQLite backups retain 7 snapshots; historical release copies are preserved.
- Static Atlas pages are intentionally LAN-only and inherit the security of Conquer's web server. Do not expose openly.

## Storage and evidence

`/opt/ls-atlas/atlas.sqlite`, `src/`, `releases/`, `backups/`, `docs/TABLE-OF-CONTENTS.md`, `docs/STATUS-MAP.json`, `docs/ATOMS.json`, `docs/GLOSSARY.json`, `alerts.log`.

## Test boundaries

Local regression: stage progress, SHA file integrity, corruption detection, duplicate alert suppression, glossary, low-stage cap, SQLite checkpoint, static site output, JavaScript syntax checked where Node is locally available. HTTP browser and real T530 runtime still require host verification.