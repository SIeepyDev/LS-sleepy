#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run as root'; exit 1; }
[ -r /etc/debian_version ] && command -v systemctl >/dev/null || { echo 'Debian/Proxmox + systemd required'; exit 1; }
command -v curl >/dev/null || { echo 'curl required'; exit 1; }
command -v python3 >/dev/null || {
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends python3
}
ROOT=/opt/ls-govern
SRC=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/policy-govern-v1/scripts/govern.py
mkdir -p "$ROOT"/backups
curl -fsSL --connect-timeout 8 --retry 2 "$SRC" -o "$ROOT/govern.new"
cp "$ROOT/govern.new" "$ROOT/_check.py"
python3 -m py_compile "$ROOT/_check.py"
rm -f "$ROOT/_check.py"
mv -f "$ROOT/govern.new" "$ROOT/govern.py"
chmod 644 "$ROOT/govern.py"
cat >/usr/local/bin/gov <<'CLI'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-govern/govern.py "$@"
CLI
chmod 755 /usr/local/bin/gov
cat >/etc/systemd/system/ls-govern-cycle.service <<'UNIT'
[Unit]
Description=LS Govern policy-governed micro-factory cycle
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/gov tick
Nice=12
IOSchedulingClass=idle
CPUQuota=60%
MemoryMax=180M
TimeoutStartSec=100
UNIT
cat >/etc/systemd/system/ls-govern-cycle.timer <<'UNIT'
[Unit]
Description=LS Govern controller schedule
[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
AccuracySec=30s
Unit=ls-govern-cycle.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-govern-checkpoint.service <<'UNIT'
[Unit]
Description=LS Govern database backup
[Service]
Type=oneshot
ExecStart=/usr/local/bin/gov checkpoint
Nice=15
UNIT
cat >/etc/systemd/system/ls-govern-checkpoint.timer <<'UNIT'
[Unit]
Description=LS Govern daily SQLite checkpoint
[Timer]
OnCalendar=daily
Persistent=true
Unit=ls-govern-checkpoint.service
[Install]
WantedBy=timers.target
UNIT

gov test
for _ in 1 2 3 4; do gov tick; done
gov checkpoint
systemctl daemon-reload
systemctl enable --now ls-govern-cycle.timer ls-govern-checkpoint.timer
systemctl list-timers --all --no-pager | grep ls-govern || true
if [ -s /opt/ls-conquer/port ]; then
 printf 'GOVERN=http://%s:%s/govern/\n' "$(hostname -I | awk '{print $1}')" "$(cat /opt/ls-conquer/port)"
else
 echo 'STATIC=/opt/ls-conquer/www/govern/index.html (Conquer web server required)'
fi
echo 'GOVERN=INSTALLED'
