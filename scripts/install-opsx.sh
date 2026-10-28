#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
command -v apt-get >/dev/null && command -v systemctl >/dev/null || { echo 'Requires Debian/Proxmox with systemd'; exit 1; }
ROOT=/opt/ls-workshop
SRC='https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/atomic-opsx-v1/scripts/opsx.py'
mkdir -p "$ROOT"/{projects,skills,reports,checkpoints}
if ! command -v python3 >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3
fi
command -v curl >/dev/null || { echo 'curl needed (existing Conquer dependency)'; exit 1; }
curl -fsSL --connect-timeout 8 --retry 2 "$SRC" -o "$ROOT/opsx.py.new"
python3 -m py_compile "$ROOT/opsx.py.new" 2>/dev/null || {
  cp "$ROOT/opsx.py.new" "$ROOT/_opsx_check.py"
  python3 -m py_compile "$ROOT/_opsx_check.py"
  rm -f "$ROOT/_opsx_check.py"
}
mv "$ROOT/opsx.py.new" "$ROOT/opsx.py"
chmod 644 "$ROOT/opsx.py"
cat >/usr/local/bin/opsx <<'EXEC'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-workshop/opsx.py "$@"
EXEC
chmod 755 /usr/local/bin/opsx

cat >/etc/systemd/system/ls-opsx-probe.service <<'UNIT'
[Unit]
Description=LS OpsX compact host probe
[Service]
Type=oneshot
ExecStart=/usr/local/bin/opsx routine
Nice=10
IOSchedulingClass=idle
MemoryMax=192M
UNIT
cat >/etc/systemd/system/ls-opsx-probe.timer <<'UNIT'
[Unit]
Description=LS OpsX host probe schedule
[Timer]
OnBootSec=1min
OnUnitInactiveSec=20min
AccuracySec=30s
Unit=ls-opsx-probe.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-opsx-scan.service <<'UNIT'
[Unit]
Description=LS OpsX daily APT metadata and catalog scan
[Service]
Type=oneshot
ExecStart=/usr/local/bin/opsx routine --online
Nice=15
IOSchedulingClass=idle
MemoryMax=384M
TimeoutStartSec=600
UNIT
cat >/etc/systemd/system/ls-opsx-scan.timer <<'UNIT'
[Unit]
Description=LS OpsX daily package scan
[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=15min
Persistent=true
Unit=ls-opsx-scan.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-opsx-checkpoint.service <<'UNIT'
[Unit]
Description=LS OpsX daily config and SQLite checkpoint
[Service]
Type=oneshot
ExecStart=/usr/local/bin/opsx checkpoint
Nice=15
IOSchedulingClass=idle
UNIT
cat >/etc/systemd/system/ls-opsx-checkpoint.timer <<'UNIT'
[Unit]
Description=LS OpsX daily checkpoint
[Timer]
OnCalendar=*-*-* 03:40:00
Persistent=true
Unit=ls-opsx-checkpoint.service
[Install]
WantedBy=timers.target
UNIT

opsx catalog >/dev/null
opsx routine >/dev/null
[ -d "$ROOT/projects/launchpad" ] || opsx new launchpad site >/dev/null
[ -d "$ROOT/projects/clicklab" ] || opsx new clicklab game >/dev/null
[ -d "$ROOT/skills/system-health" ] || opsx skill system-health >/dev/null
opsx checkpoint >/dev/null
systemctl daemon-reload
systemctl enable --now ls-opsx-probe.timer ls-opsx-scan.timer ls-opsx-checkpoint.timer
opsx db
opsx status | head -5
if [ -d /opt/ls-conquer/www ]; then
  echo "DASHBOARD=http://$(hostname -I | awk '{print $1}'):$(cat /opt/ls-conquer/port)/opsx/"
  echo "GAME=http://$(hostname -I | awk '{print $1}'):$(cat /opt/ls-conquer/port)/opsx/projects/clicklab/"
else
  echo "DASHBOARD_FILE=/opt/ls-workshop/www/index.html"
fi
echo 'OPSX=INSTALLED'