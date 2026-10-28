#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
BASE=/opt/ls-microverse
WEB=/opt/ls-conquer/www/microverse
URL=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/microverse-v1
[ -d /opt/ls-conquer/www ] || { echo 'Requires existing LS Conquer on this host (/opt/ls-conquer/www).'; exit 1; }
command -v curl >/dev/null || { echo 'curl is required'; exit 1; }
if ! command -v python3 >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends python3
fi
mkdir -p "$BASE" "$WEB"/data "$WEB"/projects "$WEB"/music
curl --connect-timeout 8 --retry 2 -fsSLo "$BASE/microverse.py.tmp" "$URL/scripts/microverse.py"
curl --connect-timeout 8 --retry 2 -fsSLo "$WEB/index.html.tmp" "$URL/web/microverse/index.html"
python3 -m py_compile "$BASE/microverse.py.tmp" 2>/dev/null || {
  cp "$BASE/microverse.py.tmp" "$BASE/_syntax_check.py"
  python3 -m py_compile "$BASE/_syntax_check.py"
  rm -f "$BASE/_syntax_check.py"
}
[ "$(wc -c <"$WEB/index.html.tmp")" -ge 8000 ] || { echo 'Downloaded web file too small'; exit 1; }
mv "$BASE/microverse.py.tmp" "$BASE/microverse.py"
mv "$WEB/index.html.tmp" "$WEB/index.html"
cat >/usr/local/bin/micro <<'CLI'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-microverse/microverse.py "$@"
CLI
chmod 755 /usr/local/bin/micro
cat >/etc/systemd/system/ls-microverse-refresh.service <<'UNIT'
[Unit]
Description=LS Microverse feed/music/research publisher
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/micro refresh
Nice=10
IOSchedulingClass=idle
CPUQuota=50%
MemoryMax=128M
TimeoutStartSec=130
UNIT
cat >/etc/systemd/system/ls-microverse-refresh.timer <<'UNIT'
[Unit]
Description=LS Microverse automatic collection (30m)
[Timer]
OnBootSec=2min
OnUnitInactiveSec=30min
RandomizedDelaySec=1min
Unit=ls-microverse-refresh.service
[Install]
WantedBy=timers.target
UNIT
micro init
micro test
systemctl daemon-reload
systemctl enable --now ls-microverse-refresh.timer
if systemctl is-active --quiet ls-conquer-web.service; then
  PORT=$(cat /opt/ls-conquer/port 2>/dev/null || echo 8765)
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo "MICROVERSE_READY http://${IP:-127.0.0.1}:${PORT}/microverse/"
else
  echo 'MICROVERSE_FILES_READY; Conquer web service is not running. Check: systemctl status ls-conquer-web'
fi
echo 'NEXT: micro refresh ; micro new nebula game ; micro youtube CHANNEL_ID ; micro skill list'