#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
[ -r /etc/debian_version ] && command -v systemctl >/dev/null || { echo 'Requires Debian/Proxmox + systemd'; exit 1; }
ROOT=/opt/ls-facilities
SRC=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/atomic-facilities-v1/scripts/facility.py
mkdir -p "$ROOT"
command -v python3 >/dev/null || { apt-get update && apt-get install -y --no-install-recommends python3; }
command -v make >/dev/null || { apt-get update && apt-get install -y --no-install-recommends make; }
command -v curl >/dev/null || { echo 'curl is required'; exit 1; }
curl -fsSLo "$ROOT/facility.new" --retry 2 --connect-timeout 8 "$SRC"
python3 -m py_compile "$ROOT/facility.new" 2>/dev/null || { cp "$ROOT/facility.new" "$ROOT/_syntax.py"; python3 -m py_compile "$ROOT/_syntax.py"; rm "$ROOT/_syntax.py"; }
mv -f "$ROOT/facility.new" "$ROOT/facility.py"
cat >/usr/local/bin/fac <<'CLI'
#!/bin/sh
exec python3 /opt/ls-facilities/facility.py "$@"
CLI
chmod +x /usr/local/bin/fac
cat >/etc/systemd/system/ls-facilities-snapshot.service <<'UNIT'
[Unit]
Description=LS Facilities lightweight system and project snapshot
[Service]
Type=oneshot
ExecStart=/usr/local/bin/fac snapshot
Nice=12
IOSchedulingClass=idle
MemoryMax=128M
UNIT
cat >/etc/systemd/system/ls-facilities-snapshot.timer <<'UNIT'
[Unit]
Description=LS Facilities system snapshot timer
[Timer]
OnBootSec=45s
OnUnitInactiveSec=20min
AccuracySec=30s
Unit=ls-facilities-snapshot.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-facilities-feed.service <<'UNIT'
[Unit]
Description=LS Facilities RSS feed collection
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/fac water refresh
Nice=12
IOSchedulingClass=idle
MemoryMax=128M
TimeoutStartSec=120
UNIT
cat >/etc/systemd/system/ls-facilities-feed.timer <<'UNIT'
[Unit]
Description=LS Facilities information intake timer
[Timer]
OnBootSec=4min
OnUnitInactiveSec=1h
AccuracySec=1min
Unit=ls-facilities-feed.service
[Install]
WantedBy=timers.target
UNIT
fac water add https://github.com/proxmox/pve-docs/commits/master.atom >/dev/null
fac water add https://github.com/community-scripts/ProxmoxVE/releases.atom >/dev/null
[ -d "$ROOT/projects/forgeboard" ] || fac kitchen new forgeboard site
fac oven forgeboard
fac stove forgeboard
fac universe 5 530
fac snapshot
fac db
systemctl daemon-reload
systemctl enable --now ls-facilities-snapshot.timer ls-facilities-feed.timer
if [ -s /opt/ls-conquer/port ]; then
 echo "WEB=http://$(hostname -I | awk '{print $1}'):$(cat /opt/ls-conquer/port)/facilities/"
else
 echo "WEB_STATIC=/opt/ls-conquer/www/facilities/index.html (requires Conquer HTTP server)"
fi
echo 'LS FACILITIES=INSTALLED'