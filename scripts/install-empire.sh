#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Root required'; exit 1; }
command -v systemctl >/dev/null && [ -e /etc/debian_version ] || { echo 'Debian/Proxmox with systemd required'; exit 1; }
command -v curl >/dev/null || { echo 'curl required'; exit 1; }
if ! command -v python3 >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3
fi
ROOT=/opt/ls-empire
SRC=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/empire-controller-v1/scripts/empire.py
mkdir -p "$ROOT"
curl -fsSLo "$ROOT/empire.new" --connect-timeout 8 --retry 2 "$SRC"
cp "$ROOT/empire.new" "$ROOT/_check.py"
python3 -m py_compile "$ROOT/_check.py"
rm -f "$ROOT/_check.py"
mv -f "$ROOT/empire.new" "$ROOT/empire.py"
cat >/usr/local/bin/empire <<'CLI'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-empire/empire.py "$@"
CLI
chmod 755 /usr/local/bin/empire
cat >/etc/systemd/system/ls-empire-cycle.service <<'UNIT'
[Unit]
Description=LS Empire bounded multi-guild production cycle
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/empire auto
Nice=12
IOSchedulingClass=idle
CPUQuota=50%
MemoryMax=160M
TimeoutStartSec=120
UNIT
cat >/etc/systemd/system/ls-empire-cycle.timer <<'UNIT'
[Unit]
Description=LS Empire autonomous city and guild schedule
[Timer]
OnBootSec=3min
OnUnitInactiveSec=15min
AccuracySec=30s
Unit=ls-empire-cycle.service
[Install]
WantedBy=timers.target
UNIT
empire init
empire challenge
empire registry | head -18
for spec in 'beach sandcastle arcade' 'workshop command-city infra' 'workshop garden-city city'; do
  set -- $spec
  empire new "$1" "$2" "$3" 2>/dev/null || :
  empire queue "$1" "$2"
done
empire tick
empire tick
empire checkpoint
systemctl daemon-reload
systemctl enable --now ls-empire-cycle.timer
empire status
if [ -s /opt/ls-conquer/port ]; then
  printf 'WEB=http://%s:%s/empire/\n' "$(hostname -I | awk '{print $1}')" "$(cat /opt/ls-conquer/port)"
else
  echo 'Static page: /opt/ls-conquer/www/empire/index.html (requires Conquer)'
fi
echo 'EMPIRE=INSTALLED'