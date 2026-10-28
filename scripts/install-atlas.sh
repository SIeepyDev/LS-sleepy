#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run as root on the T530'; exit 1; }
[ -r /etc/debian_version ] && command -v systemctl >/dev/null || { echo 'Debian / Proxmox with systemd required'; exit 1; }
for x in python3 curl; do command -v "$x" >/dev/null || { echo "Missing $x: run Conquer installer first"; exit 1; }; done
BASE=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/atlas-quality-forge-v1
HOME=/opt/ls-atlas
mkdir -p "$HOME" /opt/ls-conquer/www/atlas
curl -fsSL --connect-timeout 7 --max-time 40 --retry 2 "$BASE/scripts/atlas.py" -o "$HOME/atlas.new"
cp "$HOME/atlas.new" "$HOME/_syntax.py"
python3 -m py_compile "$HOME/_syntax.py"
rm "$HOME/_syntax.py"
if [ -f "$HOME/atlas.py" ]; then
  cp -p "$HOME/atlas.py" "$HOME/atlas.py.previous"
fi
mv -f "$HOME/atlas.new" "$HOME/atlas.py"
cat >/usr/local/bin/atlas <<'CLI'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-atlas/atlas.py "$@"
CLI
chmod 755 /usr/local/bin/atlas
cat >/etc/systemd/system/ls-atlas-cycle.service <<'UNIT'
[Unit]
Description=LS Atlas map, challenge, quality-gate and watcher cycle
After=local-fs.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/atlas cycle
Nice=12
IOSchedulingClass=idle
CPUQuota=25%
MemoryMax=128M
TimeoutStartSec=90
NoNewPrivileges=true
UNIT
cat >/etc/systemd/system/ls-atlas-cycle.timer <<'UNIT'
[Unit]
Description=LS Atlas source inspector and game-upgrade cycle
[Timer]
OnBootSec=3min
OnUnitInactiveSec=15min
AccuracySec=1min
Unit=ls-atlas-cycle.service
[Install]
WantedBy=timers.target
UNIT
# First install produces visible and tested projects without waiting for the timer.
for n in 1 2 3 4 5 6 7 8 9 10 11 12 13; do atlas cycle; done
atlas checkpoint
systemctl daemon-reload
systemctl enable --now ls-atlas-cycle.timer
atlas status | head -25
if [ -s /opt/ls-conquer/port ]; then
  printf 'ATLAS=http://%s:%s/atlas/\n' "$(hostname -I | awk '{print $1}')" "$(cat /opt/ls-conquer/port)"
else
  echo 'ATLAS_STATIC=/opt/ls-conquer/www/atlas/index.html'
fi
echo 'ATLAS=INSTALLED'