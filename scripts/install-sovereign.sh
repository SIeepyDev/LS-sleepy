#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Requires root'; exit 1; }
command -v systemctl >/dev/null && [ -r /etc/debian_version ] || { echo 'Requires Debian/Proxmox + systemd'; exit 1; }
command -v curl >/dev/null || { echo 'curl missing'; exit 1; }
if ! command -v python3 >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3
fi
ROOT=/opt/ls-sovereign
SRC=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/sovereign-control-v1/scripts/sovereign.py
mkdir -p "$ROOT"/{backups,logs}
curl -fSL --connect-timeout 8 --retry 2 "$SRC" -o "$ROOT/sovereign.py.new"
python3 -m py_compile "$ROOT/sovereign.py.new" 2>/dev/null || {
  cp "$ROOT/sovereign.py.new" "$ROOT/check.py";
  python3 -m py_compile "$ROOT/check.py";
  rm -f "$ROOT/check.py";
}
mv "$ROOT/sovereign.py.new" "$ROOT/sovereign.py"
chmod 644 "$ROOT/sovereign.py"
cat >/usr/local/bin/ctrl <<'SH'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-sovereign/sovereign.py "$@"
SH
chmod 755 /usr/local/bin/ctrl
cat >/etc/systemd/system/ls-sovereign-cycle.service <<'UNIT'
[Unit]
Description=LS Sovereign six-controller coordination cycle
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/ctrl tick
Nice=12
IOSchedulingClass=idle
CPUQuota=75%
MemoryMax=192M
TimeoutStartSec=180
UNIT
cat >/etc/systemd/system/ls-sovereign-cycle.timer <<'UNIT'
[Unit]
Description=LS Sovereign autonomous controller cycle
[Timer]
OnBootSec=1min
OnUnitInactiveSec=5min
RandomizedDelaySec=20s
Unit=ls-sovereign-cycle.service
[Install]
WantedBy=timers.target
UNIT
ctrl test
ctrl tick
systemctl daemon-reload
systemctl enable --now ls-sovereign-cycle.timer
systemctl list-timers --all --no-pager | grep ls-sovereign || true
if [ -s /opt/ls-conquer/port ]; then
  echo "CONTROL=http://$(hostname -I | awk '{print $1}'):$(cat /opt/ls-conquer/port)/control/"
else
  echo 'CONTROL_STATIC=/opt/ls-conquer/www/control/index.html (requires Conquer web server)'
fi
echo 'LS SOVEREIGN INSTALLED'
ctrl status