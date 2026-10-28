#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run as root'; exit 1; }
[ -f /etc/debian_version ] && command -v systemctl >/dev/null || { echo 'Requires Debian/Proxmox with systemd'; exit 1; }
ROOT=/opt/ls-factory
SOURCE=https://raw.githubusercontent.com/SIeepyDev/LS-sleepy/feature/recursive-factory-v1/scripts/factory_core.py
mkdir -p "$ROOT"/{workers,receipts,www,snapshots}
if ! command -v python3 >/dev/null || ! command -v busybox >/dev/null; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends python3 busybox
fi
command -v curl >/dev/null || { echo 'curl missing'; exit 1; }
busybox --list | grep -qx httpd || { echo 'busybox httpd applet unavailable'; exit 1; }
curl -fsSL --retry 2 --connect-timeout 5 -o "$ROOT/factory_core.py.tmp" "$SOURCE"
python3 -m py_compile "$ROOT/factory_core.py.tmp" 2>/dev/null || { cp "$ROOT/factory_core.py.tmp" "$ROOT/_syntax_check.py"; python3 -m py_compile "$ROOT/_syntax_check.py"; rm -f "$ROOT/_syntax_check.py"; }
mv "$ROOT/factory_core.py.tmp" "$ROOT/factory_core.py"
chmod 644 "$ROOT/factory_core.py"
cat >/usr/local/bin/factory <<'CLI'
#!/bin/sh
exec /usr/bin/python3 /opt/ls-factory/factory_core.py "$@"
CLI
chmod 755 /usr/local/bin/factory
# Keep allocated port across reinstalls.
if [ ! -s "$ROOT/port" ]; then
  PORT=$(python3 - <<'PYPORT'
import socket
for port in range(8770,8780):
    with socket.socket() as s:
        try: s.bind(('0.0.0.0',port))
        except OSError: continue
        print(port); break
else: raise SystemExit('No free port in 8770-8779')
PYPORT
)
  printf '%s\n' "$PORT" >"$ROOT/port"
fi
PORT=$(cat "$ROOT/port")
cat >/etc/systemd/system/ls-factory-cycle.service <<'UNIT'
[Unit]
Description=LS recursive microfactory cycle
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/factory cycle 1
Nice=10
IOSchedulingClass=idle
CPUQuota=75%
MemoryMax=256M
TimeoutStartSec=120
UNIT
cat >/etc/systemd/system/ls-factory-cycle.timer <<'UNIT'
[Unit]
Description=LS microfactory scheduled intake + evolution
[Timer]
OnBootSec=2min
OnUnitInactiveSec=20min
RandomizedDelaySec=30s
Unit=ls-factory-cycle.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-factory-snapshot.service <<'UNIT'
[Unit]
Description=LS microfactory SQLite checkpoint
[Service]
Type=oneshot
ExecStart=/usr/local/bin/factory snapshot
Nice=10
UNIT
cat >/etc/systemd/system/ls-factory-snapshot.timer <<'UNIT'
[Unit]
Description=LS microfactory daily checkpoint
[Timer]
OnCalendar=daily
Persistent=true
Unit=ls-factory-snapshot.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-factory-web.service <<UNIT
[Unit]
Description=LS factory static read-only dashboard
After=network.target
[Service]
Type=simple
User=nobody
ExecStart=/usr/bin/busybox httpd -f -p $PORT -h /opt/ls-factory/www
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectHome=true
ProtectSystem=strict
ReadOnlyPaths=/opt/ls-factory/www
[Install]
WantedBy=multi-user.target
UNIT
factory test
factory offline 5
factory snapshot
systemctl daemon-reload
systemctl enable --now ls-factory-cycle.timer ls-factory-snapshot.timer ls-factory-web.service
systemctl restart ls-factory-web.service
systemctl is-active --quiet ls-factory-web.service || { journalctl -u ls-factory-web.service -n 20 --no-pager; exit 1; }
IP=$(hostname -I | awk '{print $1}')
echo "LS FACTORY INSTALLED — http://${IP}:${PORT}"
factory status
systemctl list-timers --all --no-pager | grep ls-factory || true