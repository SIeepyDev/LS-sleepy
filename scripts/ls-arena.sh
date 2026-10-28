#!/usr/bin/env bash
# LS Atomic Arena — four small, deterministic, evidence-backed workers.
set -Eeuo pipefail
B=${ARENA_BASE:-/opt/ls-conquer/arena}
W=${ARENA_WEB:-/opt/ls-conquer/www/arena}
D="$B/history.sqlite"
SELF=${ARENA_SELF:-/usr/local/bin/arena}
mkdir -p "$B"/{runs,logs,workspace} "$W"
log() { local lane=$1; shift; printf '%s | %s\n' "$(date -Is)" "$*" | tee -a "$B/logs/$lane.log"; }
sqlq() { printf %s "$1" | sed "s/'/''/g"; }
dbinit() {
  sqlite3 -cmd '.timeout 5000' "$D" 'PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS cycles(id TEXT PRIMARY KEY,stamp TEXT,seed INTEGER,passed INTEGER,failed INTEGER,bytes INTEGER);
  CREATE TABLE IF NOT EXISTS checks(cycle_id TEXT,name TEXT,state TEXT,ms INTEGER,detail TEXT);
  CREATE TABLE IF NOT EXISTS collisions(cycle_id TEXT,idea TEXT,available INTEGER,recipe TEXT);' >/dev/null
}
help() {
 cat <<'HELP'
ATOMIC ARENA — four tiny workers
  arena go [SEED]    Run discovery -> build -> test -> archive
  arena eyes         View SCOUT/FORGE/RUNNER/ARCHIVIST in tmux
  arena ideas        Show tool combinations and readiness
  arena score        Recent measured outcomes
  arena lanes        Live worker logs
  arena on|off       Enable/disable half-hourly cycle
  arena test         Run one new measured cycle
  arena spin [N]     Run N seeded experiments (max 20)
  arena install      Add commands, timer and first working run
HELP
}
ideas_file() {
 cat > "$B/ideas.tsv" <<'IDEAS'
JSON to durable ledger|jq,sqlite3|API ingestion with searchable history
Files to evidence|sha256sum,sqlite3|Automatically hash and register artifacts
Script to gate|bash,shellcheck|Syntax and quality checks before deploy
Code to website|make,busybox|Compile and serve a zero-framework prototype
Proxmox to inventory|pct,sqlite3|Track existing LXCs without modifying them
Filesystem to event|inotifywait,sqlite3|Wake on changes and keep a history
Source to live preview|git,entr|Rebuild on source change
Jobs to reproducible queue|tsp,sqlite3|Queue work and preserve outcomes
HTTP to API report|curl,jq|Fetch and extract structured service data
Backups to compressed archive|rsync,zstd|Efficient file archiving pipeline
Errors to searchable notes|journalctl,rg|Investigate real system failures
Static files to web|busybox,curl|HTTP test your own preview
Metrics to benchmark|hyperfine,sqlite3|Compare execution costs over time
LXC to micro appliance|pct,pveam|Lightweight disposable service platform
IDEAS
}
scout() {
  local r=$1 n=0 found=0
  log scout "DISCOVER $r"
  : > "$B/runs/$r/tools.tsv"
  for x in jq sqlite3 sha256sum bash shellcheck make busybox pct inotifywait git entr tsp curl rsync zstd journalctl rg hyperfine pveam tmux; do
    if command -v "$x" >/dev/null 2>&1; then state=YES; found=$((found+1)); else state=NO; fi
    printf '%s\t%s\n' "$x" "$state" >> "$B/runs/$r/tools.tsv"
    n=$((n+1))
  done
  printf '%s/%s\n' "$found" "$n" > "$B/runs/$r/toolcount"
  log scout "FOUND $found/$n tools; LXC inventory follows"
  if command -v pct >/dev/null; then
    pct list > "$B/runs/$r/lxcs.txt" 2>&1 || printf 'pct list unavailable\n' > "$B/runs/$r/lxcs.txt"
  else printf 'Not a Proxmox host\n' > "$B/runs/$r/lxcs.txt"; fi
  ideas_file
  local seed; seed=$(cat "$B/runs/$r/seed")
  awk -F'|' -v seed="$seed" '((NR-1)%14)>=((seed%14)) {print} END{}' "$B/ideas.tsv" > "$B/runs/$r/rotation.tmp"
  # Rotation is reproducible and has no RNG dependency.
  awk -v seed="$seed" 'NR>1 && NR<=1+(seed%14){print}' "$B/ideas.tsv" >> "$B/runs/$r/rotation.tmp"
  head -5 "$B/runs/$r/rotation.tmp" > "$B/runs/$r/selected.tsv"
  : > "$B/runs/$r/collisions.tsv"
  while IFS='|' read -r idea tools recipe; do
    ok=1
    IFS=',' read -ra req <<< "$tools"
    for x in "${req[@]}"; do command -v "$x" >/dev/null 2>&1 || ok=0; done
    printf '%s\t%s\t%s\n' "$idea" "$ok" "$recipe" >> "$B/runs/$r/collisions.tsv"
  done < "$B/runs/$r/selected.tsv"
  log scout "COLLISIONS: $(wc -l < "$B/runs/$r/collisions.tsv") reproducible combinations"
}
forge() {
  local r=$1
  log forge "BUILD prototype and status dashboard for $r"
  local source="$B/workspace/micro-web"
  mkdir -p "$source"
  cat > "$source/Makefile" <<'MAKE'
.PHONY: build check
build:
	@mkdir -p dist
	@printf '<!doctype html><meta charset="utf-8"><title>Micro-build</title><h1>Build verified</h1>\n' > dist/index.html
check:
	@grep -q 'Build verified' dist/index.html
MAKE
  make -s -C "$source" build
  mkdir -p "$W/prototype"
  install -m 644 "$source/dist/index.html" "$W/prototype/index.html"
  local host; host=$(hostname | tr -cd 'a-zA-Z0-9_.-')
  local stamp; stamp=$(date -Is)
  local load; load=$(awk '{print $1}' /proc/loadavg)
  local ram; ram=$(awk '/MemAvailable:/{printf "%d",$2/1024}' /proc/meminfo)
  local disk; disk=$(df -P / | awk 'NR==2{print $5}')
  local cards=''
  while IFS=$'\t' read -r idea available recipe; do
    local state='READY'; [ "$available" = 1 ] || state='DISCOVERY'
    cards="$cards<article><small>$state</small><h3>$idea</h3><p>$recipe</p></article>"
  done < "$B/runs/$r/collisions.tsv"
  cat > "$W/index.html.tmp" <<HTML
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><title>LS ATOMIC ARENA</title>
<style>:root{color-scheme:dark}body{font-family:system-ui,Arial;background:#080f19;color:#e8f1fb;margin:0;padding:34px;max-width:1200px;margin:auto}h1{font-size:clamp(2rem,5vw,4rem);margin:.1em 0}small{color:#8cd6ff;font-weight:700;letter-spacing:.1em}p{color:#b0c3d7}header{border-bottom:1px solid #344251;padding-bottom:20px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:13px;padding-top:24px}article{background:linear-gradient(140deg,#142338,#13202e);border:1px solid #344861;padding:20px;border-radius:14px;min-height:110px}article h3{margin:.65em 0}.metrics{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}.metrics span{border:1px solid #344861;border-radius:8px;padding:12px 15px;background:#13202e}a{color:#a6f3d0}</style></head><body><header><small>LS ∞ / T530 MICROSYSTEMS</small><h1>ATOMIC ARENA</h1><p>Workers that discover, combine, build, verify and preserve · $host · $stamp</p><div class="metrics"><span>LOAD $load</span><span>FREE RAM ${ram} MB</span><span>DISK $disk</span><span>RUN $r</span></div></header><main>$cards</main><p><a href="/">← CONQUER</a> · <a href="prototype/">Live micro-build ↗</a></p></body></html>
HTML
  mv -f "$W/index.html.tmp" "$W/index.html"
  log forge "BUILT ${W}/index.html ($(wc -c < "$W/index.html") bytes)"
}
runner() {
  local r=$1; local result="$B/runs/$r/checks.tsv"
  : > "$result"
  log runner "TESTING $r"
  check() {
    local name=$1; shift; local start end state detail
    start=$(date +%s%3N)
    if "$@" >"$B/runs/$r/check-output.txt" 2>&1; then state=PASS; else state=FAIL; fi
    end=$(date +%s%3N)
    detail=$(head -c 130 "$B/runs/$r/check-output.txt" | tr '\t\n' '  ')
    printf '%s\t%s\t%s\t%s\n' "$name" "$state" "$((end-start))" "$detail" >> "$result"
    log runner "$state $name $((end-start))ms"
  }
  check json jq -n -e '{live:true} | .live == true'
  check sqlite sqlite3 "$B/runs/$r/probe.sqlite" 'CREATE TABLE IF NOT EXISTS k (v TEXT);INSERT INTO k VALUES("PASS");SELECT v FROM k LIMIT 1;'
  check shell bash -n "$SELF"
  check build make -s -C "$B/workspace/micro-web" build check
  check page grep -q 'ATOMIC ARENA' "$W/index.html"
  check prototype grep -q 'Build verified' "$W/prototype/index.html"
  if command -v pct >/dev/null; then check proxmox pct list; fi
  if command -v curl >/dev/null && [ -r /opt/ls-conquer/port ]; then
    local port; port=$(cat /opt/ls-conquer/port)
    check http curl -fsS --max-time 2 "http://127.0.0.1:$port/arena/"
  fi
  log runner "FINISHED: $(grep -c $'\tPASS\t' "$result" || :) passing"
}
archivist() {
  local r=$1 seed; seed=$(cat "$B/runs/$r/seed")
  dbinit
  log archivist "ARCHIVE $r"
  local passed failed bytes
  passed=$(awk -F '\t' '$2=="PASS"{n++}END{print n+0}' "$B/runs/$r/checks.tsv")
  failed=$(awk -F '\t' '$2=="FAIL"{n++}END{print n+0}' "$B/runs/$r/checks.tsv")
  bytes=$(du -sb "$B/runs/$r" | awk '{print $1}')
  sqlite3 -cmd '.timeout 5000' "$D" "INSERT OR REPLACE INTO cycles VALUES('$(sqlq "$r")','$(date -Is)',$seed,$passed,$failed,$bytes);"
  while IFS=$'\t' read -r name state ms detail; do
    sqlite3 -cmd '.timeout 5000' "$D" "INSERT INTO checks VALUES('$(sqlq "$r")','$(sqlq "$name")','$(sqlq "$state")',$ms,'$(sqlq "$detail")');"
  done < "$B/runs/$r/checks.tsv"
  while IFS=$'\t' read -r idea ready recipe; do
    sqlite3 -cmd '.timeout 5000' "$D" "INSERT INTO collisions VALUES('$(sqlq "$r")','$(sqlq "$idea")',$ready,'$(sqlq "$recipe")');"
  done < "$B/runs/$r/collisions.tsv"
  cat > "$B/runs/$r/RECEIPT.txt" <<RECEIPT
LS ATOMIC ARENA · $r
SEED $seed
PASSED $passed
FAILED $failed
BYTES $bytes
TOOLS $(cat "$B/runs/$r/toolcount")
WEB /arena/
RECEIPT
  sha256sum "$B/runs/$r/RECEIPT.txt" > "$B/runs/$r/RECEIPT.sha256"
  ln -sfn "$B/runs/$r" "$B/latest"
  log archivist "STORED ${passed} pass, ${failed} fail, receipt SHA-256"
  cat "$B/runs/$r/RECEIPT.txt"
}
cycle() {
  exec 8>"$B/.cycle.lock"
  if ! flock -n 8; then echo 'Another Arena cycle is running'; exit 0; fi
  local seed=${1:-$(date +%s)}
  [[ "$seed" =~ ^[0-9]+$ ]] || { echo 'Seed must be a nonnegative integer'; exit 2; }
  local id; id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  mkdir -p "$B/runs/$id"
  printf '%s\n' "$seed" > "$B/runs/$id/seed"
  scout "$id"
  forge "$id"
  runner "$id"
  archivist "$id"
  echo "OPEN http://$(hostname -I 2>/dev/null | awk '{print $1}'):$(cat /opt/ls-conquer/port 2>/dev/null || echo 8765)/arena/"
}
eye() {
  command -v tmux >/dev/null || { echo 'tmux required'; exit 1; }
  for lane in scout forge runner archivist; do touch "$B/logs/$lane.log"; done
  if ! tmux has-session -t atomic-arena 2>/dev/null; then
    tmux new-session -d -s atomic-arena -n WORKERS "tail -n 24 -F '$B/logs/scout.log'"
    tmux split-window -h -t atomic-arena:WORKERS "tail -n 24 -F '$B/logs/forge.log'"
    tmux split-window -v -t atomic-arena:WORKERS.0 "tail -n 24 -F '$B/logs/runner.log'"
    tmux split-window -v -t atomic-arena:WORKERS.2 "tail -n 24 -F '$B/logs/archivist.log'"
    tmux select-layout -t atomic-arena:WORKERS tiled
    tmux set-option -t atomic-arena pane-border-status top
    for x in '0 SCOUT' '1 FORGE' '2 RUNNER' '3 ARCHIVIST'; do
      read -r num title <<< "$x"; tmux select-pane -t "atomic-arena:WORKERS.$num" -T "$title"
    done
  fi
  tmux attach-session -t atomic-arena
}
score() {
  dbinit
  sqlite3 -header -column "$D" 'SELECT stamp,seed,passed,failed,bytes FROM cycles ORDER BY stamp DESC LIMIT 12;'
}
ideas() {
  ideas_file
  while IFS='|' read -r name req purpose; do
    status=READY
    IFS=',' read -ra tools <<< "$req"
    for tool in "${tools[@]}"; do command -v "$tool" >/dev/null || status=PENDING; done
    printf '%-9s %-33s %s\n' "$status" "$name" "$purpose"
  done < "$B/ideas.tsv"
}
install_arena() {
  [ "$(id -u)" -eq 0 ] || { echo 'Run as root'; exit 1; }
  command -v conquer >/dev/null || { echo 'Install LS Conquer first'; exit 1; }
  if [ "$SELF" != "$0" ]; then install -m 755 "$0" "$SELF"; fi
  local missing=()
  for tool in sqlite3 jq make tmux curl; do command -v "$tool" >/dev/null || missing+=("$tool"); done
  if ((${#missing[@]})); then
    apt-get update -qq
    apt-get install -y --no-install-recommends "${missing[@]}"
  fi
  dbinit
  cat >/etc/systemd/system/ls-arena-cycle.service <<'UNIT'
[Unit]
Description=LS Atomic Arena micro-experiment cycle
After=local-fs.target
[Service]
Type=oneshot
ExecStart=/usr/local/bin/arena go
Nice=10
IOSchedulingClass=idle
UNIT
  cat >/etc/systemd/system/ls-arena-cycle.timer <<'UNIT'
[Unit]
Description=LS Atomic Arena periodic experiment timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=30min
AccuracySec=30s
Unit=ls-arena-cycle.service
[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now ls-arena-cycle.timer
  "$SELF" go
  echo 'READY: arena eyes | arena ideas | arena score | arena go 42'
}
case "${1:-help}" in
  go|test) shift; cycle "${1:-}";;
  spin) count=${2:-5}; [[ "$count" =~ ^[0-9]+$ ]] && ((count>=1 && count<=20)) || { echo 'N must be 1..20'; exit 2; }; seed=$(date +%s); for ((i=0;i<count;i++)); do cycle "$((seed+i))"; done;;
  worker) shift; "${1:-}" "${2:-}";;
  install) install_arena;;
  eyes) eye;;
  ideas) ideas;;
  score) score;;
  lanes) for x in scout forge runner archivist; do echo "=== $x ==="; tail -n 5 "$B/logs/$x.log" 2>/dev/null || :; done;;
  on|off) [ "$(id -u)" -eq 0 ] || exit 1; if [ "$1" = on ]; then systemctl enable --now ls-arena-cycle.timer; else systemctl disable --now ls-arena-cycle.timer; fi;;
  help|-h|--help) help;;
  *) help; exit 2;;
esac
