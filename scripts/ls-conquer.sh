#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
command -v apt-get >/dev/null && command -v systemctl >/dev/null || { echo 'Requires Debian/Proxmox + systemd'; exit 1; }
B=/opt/ls-conquer
mkdir -p "$B"/{inbox,sorted,reports,logs,www}
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
CORE=(busybox sqlite3 curl jq git tmux rsync ripgrep fd-find fzf task-spooler entr inotify-tools make shellcheck ncdu)
for p in "${CORE[@]}"; do
  if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed'; then continue; fi
  if apt-cache show "$p" >/dev/null 2>&1; then
    echo "INSTALL $p"
    apt-get install -y -qq --no-install-recommends "$p" || echo "SKIPPED $p (install failed)"
  else echo "UNAVAILABLE $p"; fi
done
command -v sqlite3 >/dev/null && command -v busybox >/dev/null || { echo 'Missing required sqlite3 or busybox'; exit 1; }
if ! busybox --list | grep -qx httpd; then echo 'BusyBox httpd applet unavailable'; exit 1; fi

cat >/usr/local/bin/conquer <<'CMD'
#!/usr/bin/env bash
set -Eeuo pipefail
B=/opt/ls-conquer
DB=$B/history.sqlite
mkdir -p "$B"/{inbox,sorted,reports,logs,www}
init(){ sqlite3 -cmd '.timeout 5000' "$DB" 'CREATE TABLE IF NOT EXISTS runs(ts TEXT,load1 REAL,available_mb INTEGER,disk_pct INTEGER,lxcs INTEGER);'; }
log(){ printf '%s %s\n' "$(date -Is)" "$*" >>"$B/logs/actions.log"; }
hunt(){
  cat >"$B/catalog.tsv" <<'LIST'
100|sqlite3|Tiny durable database
99|tmux|Persistent four-pane control
98|task-spooler|Tiny queued workers
97|git|Project version control
96|curl|HTTP integrations
95|jq|JSON automation
94|ripgrep|Fast source search
93|fd-find|Fast file search
92|fzf|Interactive selection
91|entr|File-triggered builds
90|inotify-tools|Filesystem event triggers
89|make|Reusable build commands
88|shellcheck|Shell CI quality
87|busybox|Micro-toolbox and web server
86|rsync|Efficient synchronization
85|ncdu|Interactive disk audit
84|just|Developer command launcher
83|duf|Visual disk report
82|lnav|Interactive log investigation
81|btop|Visual resource monitor
80|hyperfine|Repeatable benchmarks
79|restic|Encrypted deduplicating backups
78|parallel|Concurrent job execution
77|bats|Shell tests
76|zoxide|Smart navigation
75|yq|Structured YAML/JSON editing
74|age|File encryption
73|etckeeper|Track system configuration changes
72|smartmontools|Drive health
71|lsof|Open files and ports
70|strace|System call diagnosis
69|tcpdump|Network inspection
68|dnsutils|DNS checks
67|rclone|Remote and local file synchronization
66|mosh|Resilient remote shell
65|zstd|Fast compression
64|socat|Socket and network glue
63|tldr|Practical command examples
LIST
  : >"$B/reports/candidates.tsv"
  while IFS='|' read -r score pkg role; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'; then state=INSTALLED
    elif apt-cache show "$pkg" >/dev/null 2>&1; then state=AVAILABLE
    else state=UNAVAILABLE; fi
    printf '%s\t%s\t%s\t%s\n' "$score" "$state" "$pkg" "$role" >>"$B/reports/candidates.tsv"
  done <"$B/catalog.tsv"
  log "HUNT catalog refreshed"
}
sort_inbox(){
  exec 9>"$B/.sort.lock"
  flock -n 9 || exit 0
  shopt -s nullglob
  for f in "$B"/inbox/*; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    n=${f##*/}
    case "${n,,}" in
      *.json|*.jsonl) k=data;;
      *.sh|*.py|*.js|*.ts|*.go|*.rs) k=code;;
      *.zip|*.tar|*.gz|*.xz|*.zst|*.deb) k=packages;;
      *.png|*.jpg|*.jpeg|*.svg|*.webp) k=images;;
      *.log|*.txt|*.md) k=notes;;
      *) k=other;;
    esac
    mkdir -p "$B/sorted/$k"
    dest="$B/sorted/$k/$n"
    [ ! -e "$dest" ] || dest="$B/sorted/$k/$(date +%s)-$$-$n"
    sha=$(sha256sum -- "$f" | cut -d' ' -f1)
    mv -- "$f" "$dest"
    printf '%s\t%s\t%s\n' "$(date -Is)" "$k/$n" "$sha" >>"$B/logs/files.tsv"
    log "SORT $k/$n"
  done
}
probe(){
  init
  local load ram disk lxcs
  load=$(awk '{print $1}' /proc/loadavg)
  ram=$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)
  disk=$(df -P / | awk 'NR==2{gsub(/%/,"",$5);print $5}')
  lxcs=0
  if command -v pct >/dev/null; then lxcs=$(pct list 2>/dev/null | awk 'NR>1{n++}END{print n+0}'); fi
  sqlite3 -cmd '.timeout 5000' "$DB" "INSERT INTO runs VALUES('$(date -Is)',$load,$ram,$disk,$lxcs);"
  { date; uname -sr; uptime; free -h; df -h /; echo; ip -br addr 2>/dev/null || :;
    if command -v pct >/dev/null; then echo '=== LXCs ==='; pct list || :; fi
    if command -v pvesm >/dev/null; then echo '=== STORAGE ==='; pvesm status || :; fi
    echo '=== FAILED SERVICES ==='; systemctl --failed --no-pager --plain || :;
  } >"$B/reports/system.txt"
  [ -f "$B/reports/candidates.tsv" ] || hunt
  local installed available
  installed=$(awk -F '\t' '$2=="INSTALLED"{n++}END{print n+0}' "$B/reports/candidates.tsv")
  available=$(awk -F '\t' '$2=="AVAILABLE"{n++}END{print n+0}' "$B/reports/candidates.tsv")
  local uptimeTxt memTxt diskTxt
  uptimeTxt=$(uptime -p)
  memTxt=$(free -h | awk '/Mem:/{print $3" / "$2}')
  diskTxt=$(df -h / | awk 'NR==2{print $5}')
  cat >"$B/www/index.html.tmp" <<HTML
<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="35"><title>CONQUER / $(hostname)</title>
<style>body{background:#090d15;color:#e6edf6;font:16px system-ui;margin:0;padding:5vw;max-width:1100px}header{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}h1{font-size:clamp(32px,5vw,55px);margin:5px 0}small,.muted{color:#93a4bd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:25px 0}.card{padding:22px;border:1px solid #2b3548;background:#151e2d;border-radius:17px}.num{font-size:28px;font-weight:750;color:#a7f3d0}a{color:#7dd3fc}pre{background:#0d1523;border:1px solid #28364a;border-radius:12px;padding:20px;overflow:auto;font-size:12px;line-height:1.8}code{color:#a7f3d0}</style></head><body>
<header><div><small>LS ∞ / ATOMIC OPERATIONS</small><h1>CONQUER</h1><span class="muted">$(hostname) · $(date '+%F %H:%M')</span></div><div>● AUTO-REFRESH / 35s</div></header>
<div class="grid"><div class="card"><small>UPTIME</small><div class="num">$uptimeTxt</div></div><div class="card"><small>MEMORY</small><div class="num">$memTxt</div></div><div class="card"><small>DISK USED</small><div class="num">$diskTxt</div></div><div class="card"><small>LXC COUNT</small><div class="num">$lxcs</div></div><div class="card"><small>TOOLS INSTALLED</small><div class="num">$installed</div></div><div class="card"><small>NEXT CANDIDATES</small><div class="num">$available</div></div></div>
<h2>CONTROL VERBS</h2><div class="card"><code>conquer</code> status · <code>conquer hunt</code> discover · <code>conquer expand</code> upgrade · <code>conquer jobs</code> queue · <code>conquer labs</code> LXCs · <code>conquer logs</code> events</div>
<h2>FOUNDATIONS</h2><pre>
HTML
  head -24 "$B/reports/candidates.tsv" >>"$B/www/index.html.tmp"
  cat >>"$B/www/index.html.tmp" <<'HTML'
</pre><h2>LAST ACTIONS</h2><pre>
HTML
  tail -15 "$B/logs/actions.log" 2>/dev/null >>"$B/www/index.html.tmp" || :
  cat >>"$B/www/index.html.tmp" <<'HTML'
</pre><small>Read-only local UI · SQLite receipts · systemd timers · queued workers · no cloud login</small></body></html>
HTML
  mv "$B/www/index.html.tmp" "$B/www/index.html"
}
expand(){
  local pkgs=(just duf lnav btop hyperfine restic parallel bats zoxide yq age etckeeper smartmontools lsof strace tcpdump dnsutils rclone mosh zstd socat tldr)
  apt-get update -qq
  for p in "${pkgs[@]}"; do
    if dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed'; then continue; fi
    if apt-cache show "$p" >/dev/null 2>&1; then
      echo "INSTALL $p"
      apt-get install -y -qq --no-install-recommends "$p" || log "FAILED install $p"
    fi
  done
  hunt; probe
}
check(){
  local fail=0
  jq -n '{ok:true}' | jq -e '.ok' >/dev/null && echo 'PASS jq' || { echo 'FAIL jq'; fail=1; }
  sqlite3 "$DB" 'SELECT COUNT(*) FROM runs;' && echo 'PASS sqlite' || { echo 'FAIL sqlite'; fail=1; }
  command -v tsp >/dev/null && { tsp -S 2 >/dev/null; tsp -L ls-smoke /bin/sh -c 'echo JOB_OK' >/dev/null; echo 'PASS task queue'; } || echo 'SKIP queue'
  curl --max-time 3 -fsS "http://127.0.0.1:$(cat "$B/port")/" >/dev/null && echo 'PASS dashboard' || { echo 'FAIL dashboard'; fail=1; }
  [ "$fail" -eq 0 ]
}
case "${1:-status}" in
  status) probe; cat "$B/reports/system.txt"; echo; echo "DASHBOARD: http://$(hostname -I | awk '{print $1}'):$(cat "$B/port")";;
  probe) probe;;
  hunt) hunt; column -t -s $'\t' "$B/reports/candidates.tsv" 2>/dev/null || cat "$B/reports/candidates.tsv";;
  expand) expand;;
  sort) sort_inbox;;
  jobs) if command -v tsp >/dev/null; then tsp; else echo 'task-spooler unavailable'; fi;;
  run) shift; if command -v tsp >/dev/null; then tsp "$@"; else echo 'task-spooler unavailable'; exit 1; fi;;
  labs) if command -v pct >/dev/null; then pct list; else echo 'Not a Proxmox host; no LXCs here'; fi;;
  logs) tail -30 "$B/logs/actions.log";;
  test) check;;
  serve) exec busybox httpd -f -p "$(cat "$B/port")" -h "$B/www";;
  *) echo 'conquer {status|probe|hunt|expand|sort|jobs|run CMD|labs|logs|test|serve}';;
esac
CMD
chmod 755 /usr/local/bin/conquer

cat >/etc/systemd/system/ls-conquer-web.service <<'UNIT'
[Unit]
Description=LS Conquer read-only dashboard
After=network.target
[Service]
Type=simple
ExecStart=/usr/local/bin/conquer serve
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/ls-conquer-probe.service <<'UNIT'
[Unit]
Description=LS Conquer system inventory
[Service]
Type=oneshot
ExecStart=/usr/local/bin/conquer probe
UNIT
cat >/etc/systemd/system/ls-conquer-probe.timer <<'UNIT'
[Unit]
Description=LS Conquer system inventory timer
[Timer]
OnBootSec=30sec
OnUnitActiveSec=1min
AccuracySec=10sec
Unit=ls-conquer-probe.service
[Install]
WantedBy=timers.target
UNIT
cat >/etc/systemd/system/ls-conquer-sort.service <<'UNIT'
[Unit]
Description=LS Conquer inbox sorting
[Service]
Type=oneshot
ExecStart=/usr/local/bin/conquer sort
UNIT
cat >/etc/systemd/system/ls-conquer-sort.path <<'UNIT'
[Unit]
Description=LS Conquer inbox watcher
[Path]
PathChanged=/opt/ls-conquer/inbox
Unit=ls-conquer-sort.service
[Install]
WantedBy=multi-user.target
UNIT
cat >/etc/systemd/system/ls-conquer-hunt.service <<'UNIT'
[Unit]
Description=LS Conquer candidate discovery
[Service]
Type=oneshot
ExecStart=/usr/local/bin/conquer hunt
UNIT
cat >/etc/systemd/system/ls-conquer-hunt.timer <<'UNIT'
[Unit]
Description=LS Conquer daily option discovery
[Timer]
OnCalendar=daily
Persistent=true
Unit=ls-conquer-hunt.service
[Install]
WantedBy=timers.target
UNIT

# Choose a free local port without disturbing other services.
if [ -s "$B/port" ]; then
  PORT=$(cat "$B/port")
else
  PORT=8765
  for candidate in 8765 8766 8767 8768 8769; do
    if ! ss -lnt 2>/dev/null | grep -Eq ":${candidate}([[:space:]]|$)"; then PORT=$candidate; break; fi
  done
  printf '%s\n' "$PORT" >"$B/port"
fi
systemctl daemon-reload
systemctl enable --now ls-conquer-web.service ls-conquer-probe.timer ls-conquer-sort.path ls-conquer-hunt.timer
systemctl restart ls-conquer-web.service
conquer hunt >/dev/null
conquer probe
systemctl is-active --quiet ls-conquer-web.service || { journalctl -u ls-conquer-web.service -n 15 --no-pager; exit 1; }
conquer test
printf 'INSTALLED LS CONQUER\nDashboard: http://%s:%s\nInbox: %s/inbox\n' "$(hostname -I | awk '{print $1}')" "$(cat "$B/port")" "$B"