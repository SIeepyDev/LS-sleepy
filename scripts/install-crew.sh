#!/usr/bin/env bash
# LS Micro Crew: install alongside Conquer and Factory, without replacing their units.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
command -v systemctl >/dev/null && command -v apt-get >/dev/null || { echo 'Debian/Proxmox with systemd required'; exit 1; }
ROOT=/opt/ls-crew
SRC=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/micro-crew-v1/scripts/ls-crew.py
EXPECTED_SHA256=c4ba73c86935e19aba97ddcc970894c3206fac0b7b40aabf12ffa197acefe0c0
mkdir -p "$ROOT"/{inbox,processed,artifacts,receipts,logs,snapshots}
if ! command -v python3 >/dev/null || ! command -v curl >/dev/null || ! command -v busybox >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 curl busybox
fi
curl -fsSL --retry 2 --connect-timeout 8 --max-time 40 "$SRC" -o "$ROOT/crew.py.tmp"
printf '%s  %s\n' "$EXPECTED_SHA256" "$ROOT/crew.py.tmp" | sha256sum -c -
python3 -m py_compile "$ROOT/crew.py.tmp"
mv -f "$ROOT/crew.py.tmp" "$ROOT/crew.py"
chmod 644 "$ROOT/crew.py"

PORT=''
WEB='/opt/ls-conquer/www/crew'
if [ -r /opt/ls-conquer/port ] && systemctl is-active -q ls-conquer-web.service; then
  PORT=$(cat /opt/ls-conquer/port)
  echo "Using existing Conquer web server on port $PORT"
else
  WEB="$ROOT/www"
  command -v busybox >/dev/null && busybox --list | grep -qx httpd || { echo 'BusyBox httpd applet required'; exit 1; }
  for p in 8780 8781 8782 8783 8784; do
    if ! ss -ltn 2>/dev/null | grep -Eq ":${p}([[:space:]]|$)";then PORT=$p;break;fi
  done
  [ -n "$PORT" ] || { echo 'No free dedicated HTTP port';exit 1; }
  mkdir -p "$WEB"
  cat >/etc/systemd/system/ls-crew-web.service <<UNIT
[Unit]
Description=LS Micro Crew local read-only HTTP dashboard
After=network.target
[Service]
Type=simple
ExecStart=/usr/bin/busybox httpd -f -p $PORT -h $WEB
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
[Install]
WantedBy=multi-user.target
UNIT
fi
printf '%s\n' "$WEB" >"$ROOT/webpath"
printf '%s\n' "$PORT" >"$ROOT/port"
cat >/usr/local/bin/crew <<'WRAP'
#!/bin/sh
export LS_CREW_WWW="$(cat /opt/ls-crew/webpath)"
exec /usr/bin/python3 /opt/ls-crew/crew.py "$@"
WRAP
chmod 755 /usr/local/bin/crew
cat >/etc/systemd/system/ls-crew-cycle.service <<'UNIT'
[Unit]
Description=LS Micro Crew bounded parallel production and research
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/crew cycle --online
Nice=12
IOSchedulingClass=idle
CPUQuota=100%
MemoryMax=384M
TimeoutStartSec=210
UNIT
cat >/etc/systemd/system/ls-crew-cycle.timer <<'UNIT'
[Unit]
Description=LS Micro Crew recurring work cycle
[Timer]
OnBootSec=90s
OnUnitInactiveSec=12min
RandomizedDelaySec=20s
Unit=ls-crew-cycle.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-crew-inbox.service <<'UNIT'
[Unit]
Description=LS Micro Crew event-driven job intake
[Service]
Type=oneshot
ExecStart=/usr/local/bin/crew inbox
Nice=10
CPUQuota=90%
MemoryMax=256M
TimeoutStartSec=120
UNIT
cat >/etc/systemd/system/ls-crew-inbox.path <<'UNIT'
[Unit]
Description=LS Micro Crew incoming job watcher
[Path]
PathChanged=/opt/ls-crew/inbox
Unit=ls-crew-inbox.service
[Install]
WantedBy=multi-user.target
UNIT

crew test
crew demo
crew backup
systemctl daemon-reload
systemctl enable --now ls-crew-cycle.timer ls-crew-inbox.path
if [ "$WEB" = "$ROOT/www" ];then
  systemctl enable --now ls-crew-web.service
fi
crew board
curl -fsS --max-time 3 "http://127.0.0.1:$PORT/$(if [ "$WEB" = "$ROOT/www" ];then :;else printf 'crew/';fi)" >/dev/null || echo 'WARN: Dashboard HTTP not yet reachable, inspect service'
echo
printf 'CREW INSTALLED: http://%s:%s%s\n' "$(hostname -I | awk '{print $1}')" "$PORT" "$(if [ "$WEB" = "$ROOT/www" ];then printf '/';else printf '/crew/';fi)"
echo 'NEXT: crew eyes | crew jobs | crew cycle --online | crew search sqlite --engine github'
