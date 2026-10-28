#!/usr/bin/env bash
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo 'root required'; exit 1; }
command -v apt-get >/dev/null && command -v systemctl >/dev/null || { echo 'Debian/systemd required'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
PKGS=(sqlite3 rsync fzf zoxide zsh-autosuggestions zsh-syntax-highlighting bash-completion)
apt-get update -qq
SIM=$(apt-get -s install --no-install-recommends "${PKGS[@]}")
if grep -Eq '^Remv (proxmox|pve-manager|pve-cluster|lxc-pve|qemu-server)' <<<"$SIM"; then
  echo 'Aborted: package solver proposes Proxmox removal'; exit 1
fi
apt-get install -y -qq --no-install-recommends "${PKGS[@]}"
mkdir -p /var/lib/ls-memory/{checkpoints,logs}
chmod 700 /var/lib/ls-memory /var/lib/ls-memory/checkpoints /var/lib/ls-memory/logs
cat >/usr/local/bin/lsmem <<'TOOL'
#!/usr/bin/env bash
set -Eeuo pipefail
B=${LSMEM_HOME:-/var/lib/ls-memory}
DB=$B/memory.sqlite
mkdir -p "$B"/{checkpoints,logs}
chmod 700 "$B" "$B/checkpoints" "$B/logs"
init(){
 sqlite3 -cmd '.timeout 5000' "$DB" '
 CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts TEXT DEFAULT CURRENT_TIMESTAMP,kind TEXT,detail TEXT);
 CREATE TABLE IF NOT EXISTS facts(ts TEXT DEFAULT CURRENT_TIMESTAMP,hostname TEXT,load REAL,ram_mb INTEGER,disk_pct INTEGER,lxcs INTEGER,failed_units INTEGER);'
}
record(){
 local kind=$1 detail=${2:-} safe
 safe=${detail//\'/\'\'}
 sqlite3 -cmd '.timeout 5000' "$DB" "INSERT INTO events(kind,detail) VALUES('$kind','$safe');"
}
lxcs(){ if command -v pct >/dev/null 2>&1; then pct list 2>/dev/null | awk 'NR>1{n++}END{print n+0}'; else echo '-'; fi; }
failures(){ (systemctl --failed --no-legend --plain --no-pager 2>/dev/null || :) | awk 'NF{n++}END{print n+0}'; }
facts(){
 local ld ram disk lxc failed
 ld=$(awk '{print $1}' /proc/loadavg)
 ram=$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)
 disk=$(df -P / | awk 'NR==2{gsub(/%/,"",$5);print $5}')
 lxc=$(lxcs); failed=$(failures)
 printf 'HOST       %s\nUPTIME     %s\nLOAD       %s\nRAM FREE   %s MB\nDISK USED  %s%%\nLXC COUNT  %s\nFAILED     %s\n' "$(hostname)" "$(uptime -p)" "$ld" "$ram" "$disk" "$lxc" "$failed"
 if command -v conquer >/dev/null; then echo 'CONQUER    installed'; fi
 if command -v arena >/dev/null; then echo 'ARENA      installed'; fi
 if [ -f "$B/sync-target" ]; then printf 'SYNC       %s\n' "$(cat "$B/sync-target")"; else echo 'SYNC       not configured'; fi
}
snapshot(){
 local ld ram disk lxc failed
 ld=$(awk '{print $1}' /proc/loadavg)
 ram=$(awk '/MemAvailable:/{print int($2/1024)}' /proc/meminfo)
 disk=$(df -P / | awk 'NR==2{gsub(/%/,"",$5);print $5}')
 lxc=$(lxcs); [ "$lxc" = '-' ] && lxc=0
 failed=$(failures)
 sqlite3 -cmd '.timeout 5000' "$DB" "INSERT INTO facts(hostname,load,ram_mb,disk_pct,lxcs,failed_units) VALUES('$(hostname)',$ld,$ram,$disk,$lxc,$failed);"
}
next(){
 local disk failed
 disk=$(df -P / | awk 'NR==2{gsub(/%/,"",$5);print $5}')
 failed=$(failures)
 echo 'NEXT / highest leverage'
 if [ "$failed" -gt 0 ]; then echo '1. systemctl --failed'; else echo '1. lsmem facts'; fi
 if [ "$disk" -ge 80 ]; then echo '2. ncdu /'; else echo '2. lsmem checkpoint manual'; fi
 if command -v conquer >/dev/null; then echo '3. conquer hunt'; else echo '3. lsmem db'; fi
 if command -v arena >/dev/null; then echo '4. arena score'; else echo '4. lsmem history'; fi
 if [ ! -s "$B/sync-target" ]; then echo '5. lsmem sync set /mnt/your-mounted-backup'; else echo '5. lsmem sync now'; fi
}
history(){
 local f
 for f in "$HOME/.zsh_history" "$HOME/.bash_history"; do
   [ -f "$f" ] || continue
   echo "== $f =="
   tail -n 120 "$f" | sed -E 's/^: [0-9]+:[0-9]+;//' | tail -n 35
 done
}
find_history(){
 local query=${1:-}; [ -n "$query" ] || { echo 'Usage: lsmem find WORD'; exit 2; }
 for f in "$HOME/.zsh_history" "$HOME/.bash_history"; do
   [ -f "$f" ] || continue
   grep -iF -- "$query" "$f" | tail -n 30 | sed -E 's/^: [0-9]+:[0-9]+;//' || :
 done
}
dbs(){
 local dir f check size
 for dir in /opt/ls-conquer /opt/ls-atoms /root/forge "$B"; do
   [ -d "$dir" ] || continue
   while IFS= read -r -d '' f; do
     size=$(stat -c%s "$f" 2>/dev/null || echo '?')
     check=$(sqlite3 -readonly -cmd '.timeout 2000' "$f" 'PRAGMA quick_check;' 2>/dev/null | head -1 || echo 'ERROR')
     printf '%-9s %-10s %s\n' "${check:-ERROR}" "$size" "$f"
   done < <(find "$dir" -maxdepth 3 -type f \( -name '*.db' -o -name '*.sqlite' \) -print0 2>/dev/null)
 done
}
checkpoint(){
 local typ=${1:-manual} tag=${2:-on-demand} ts target dir f short result
 case "$typ" in auto|manual) ;; *) echo 'checkpoint mode must be auto or manual'; exit 2;; esac
 tag=${tag//[^a-zA-Z0-9_-]/_}; tag=${tag:0:35}
 ts=$(date -u +%Y%m%dT%H%M%SZ)
 target="$B/checkpoints/$typ-$ts-$tag"
 mkdir -m 700 -p "$target/databases"
 { date -u; hostname; uname -a; uptime; free -m; df -h /;
   command -v pct >/dev/null && pct list || :;
   command -v qm >/dev/null && qm list || :;
   systemctl --failed --no-pager --plain || :;
   dpkg-query -W -f='${binary:Package}\t${Version}\n' 2>/dev/null || :;
 } >"$target/host-facts.txt"
 for dir in /opt/ls-conquer /opt/ls-atoms /root/forge "$B"; do
  [ -d "$dir" ] || continue
  while IFS= read -r -d '' f; do
    short=${f#/}; short=${short//\//__}
    # SQLite's online backup handles databases in active use.
    if result=$(sqlite3 -cmd '.timeout 5000' "$f" ".backup '$target/databases/$short'" 2>&1); then
      printf '%s\tPASS\n' "$f" >>"$target/databases.tsv"
    else
      printf '%s\tFAIL\t%s\n' "$f" "$result" >>"$target/databases.tsv"
      rm -f -- "$target/databases/$short"
    fi
  done < <(find "$dir" -maxdepth 3 -type f \( -name '*.db' -o -name '*.sqlite' \) -print0 2>/dev/null)
 done
 (cd "$target" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 -r sha256sum) >"$target/SHA256SUMS"
 record CHECKPOINT "$target"
 echo "$target"
}
sync_now(){
 local dest
 if [ ! -s "$B/sync-target" ]; then echo 'SYNC UNCONFIGURED: lsmem sync set DESTINATION'; return 2; fi
 dest=$(cat "$B/sync-target")
 # No deletion; destination only gets this host's LS memory tree.
 rsync -a --no-owner --no-group -- "$B/checkpoints/" "${dest%/}/$(hostname)-ls-memory/"
 record SYNC "$dest"
 echo "SYNCED to $dest"
}
sync_set(){
 local dest=${1:-}; [ -n "$dest" ] || { echo 'Usage: lsmem sync set DESTINATION'; exit 2; }
 case "$dest" in
  /*) [ -d "$dest" ] || { echo 'Destination directory does not exist'; exit 2; } ;;
  *@*:*) echo 'Remote rsync over SSH requires existing key-based access' ;;
  *) echo 'Use absolute directory or user@host:/path'; exit 2;;
 esac
 printf '%s\n' "$dest" >"$B/sync-target"
 chmod 600 "$B/sync-target"
 record SYNC_CONFIG "$dest"
 echo 'Sync configured';
}
overlap(){
 echo 'OVERLAP INSPECTION — no removals'
 for x in fdfind fd find rg grep just make entr watchexec parallel tsp; do
  command -v "$x" >/dev/null && printf '%-13s %s\n' "$x" "$(command -v "$x")"
 done
 systemctl list-unit-files --no-pager 2>/dev/null | grep -E 'ls-atomic|ls-conquer|forge' || :
}
notes(){ sqlite3 -header -column "$DB" 'SELECT ts,kind,detail FROM events ORDER BY id DESC LIMIT 25;'; }
choose(){
 local data
 data=$(printf '%s\n' 'lsmem facts' 'lsmem next' 'lsmem history' 'lsmem db' 'lsmem checkpoint' 'lsmem checkpoints' 'lsmem sync now' 'lsmem overlap' 'conquer hunt' 'conquer test' 'arena score' 'pct list' 'pvesm status' 'journalctl -p 3 -b')
 if command -v fzf >/dev/null; then printf '%s\n' "$data" | fzf --height 40% --reverse; else printf '%s\n' "$data"; fi
}
auto(){
 snapshot
 checkpoint auto daily >/dev/null
 if [ -s "$B/sync-target" ]; then sync_now || record SYNC_ERROR 'sync failed'; fi
 # Only prune our own auto snapshots; retain last 21, manual never pruned.
 mapfile -t dirs < <(find "$B/checkpoints" -mindepth 1 -maxdepth 1 -type d -name 'auto-*' | sort -r)
 for ((i=21;i<${#dirs[@]};i++)); do rm -rf -- "${dirs[$i]}"; done
 echo 'AUTO completed'
}
init
case "${1:-facts}" in
 facts|status) facts;; next) next;; history) history;; find) shift; find_history "$*";;
 db|databases) dbs;; checkpoint) checkpoint manual "${2:-on-demand}";;
 checkpoints) find "$B/checkpoints" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r | head -25;;
 sync) case "${2:-}" in set) sync_set "${3:-}";; now) sync_now;; *) echo 'lsmem sync {set DEST|now}';; esac;;
 overlap) overlap;; note) shift; record NOTE "$*";; notes) notes;;
 pick) choose;; record) snapshot;; auto) auto;;
 test) sqlite3 "$DB" 'PRAGMA integrity_check;'; bash -n /usr/local/bin/lsmem; command -v fzf; systemctl is-enabled ls-memory.timer;;
 *) echo 'lsmem {facts|next|history|find WORD|db|checkpoint|checkpoints|sync set DEST|sync now|overlap|pick|note|notes|test}'; exit 2;;
esac
TOOL
chmod 755 /usr/local/bin/lsmem
cat >/etc/systemd/system/ls-memory.service <<'UNIT'
[Unit]
Description=LS Memory fact collection and SQLite checkpointing
[Service]
Type=oneshot
ExecStart=/usr/local/bin/lsmem auto
Nice=15
IOSchedulingClass=idle
UNIT
cat >/etc/systemd/system/ls-memory.timer <<'UNIT'
[Unit]
Description=Daily LS Memory checkpoints, databases and optional sync
[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=15min
Unit=ls-memory.service
[Install]
WantedBy=timers.target
UNIT
# Add non-invasive shell integrations. Keep whatever prompt/theme the user already has.
cat >/etc/profile.d/ls-memory-bash.sh <<'SH'
# LS Memory: searchable history (interactive Bash only).
if [ -n "${BASH_VERSION:-}" ] && [[ $- == *i* ]]; then
 export HISTSIZE=100000 HISTFILESIZE=100000 HISTCONTROL=ignoredups:erasedups
 shopt -s histappend
 [ -f /usr/share/doc/fzf/examples/key-bindings.bash ] && . /usr/share/doc/fzf/examples/key-bindings.bash
 command -v zoxide >/dev/null && eval "$(zoxide init bash)"
fi
SH
cat >/usr/local/share/ls-memory-zsh.zsh <<'ZSH'
# LS Memory: auto-complete/predict from history. Loaded after user's theme.
if [[ -o interactive ]]; then
 HISTFILE=${HISTFILE:-$HOME/.zsh_history}
 HISTSIZE=100000
 SAVEHIST=100000
 setopt SHARE_HISTORY HIST_IGNORE_ALL_DUPS EXTENDED_HISTORY
 if [[ -r /usr/share/doc/fzf/examples/key-bindings.zsh ]]; then
   source /usr/share/doc/fzf/examples/key-bindings.zsh
 fi
 if (( $+commands[zoxide] )); then eval "$(zoxide init zsh)"; fi
 [[ -r /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh ]] && source /usr/share/zsh-autosuggestions/zsh-autosuggestions.zsh
 [[ -r /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]] && source /usr/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
fi
ZSH
chmod 644 /usr/local/share/ls-memory-zsh.zsh
ZSHRC=/root/.zshrc
[ -f "$ZSHRC" ] || touch "$ZSHRC"
if ! grep -Fq 'source /usr/local/share/ls-memory-zsh.zsh' "$ZSHRC"; then
 printf '\n# LS Memory: autosuggestions, fuzzy history, navigation\nsource /usr/local/share/ls-memory-zsh.zsh\n' >>"$ZSHRC"
fi
BASHRC=/root/.bashrc
[ -f "$BASHRC" ] || touch "$BASHRC"
if ! grep -Fq 'source /etc/profile.d/ls-memory-bash.sh' "$BASHRC"; then
 printf '\n# LS Memory: fuzzy history and navigation\nsource /etc/profile.d/ls-memory-bash.sh\n' >>"$BASHRC"
fi
systemctl daemon-reload
systemctl enable --now ls-memory.timer
bash -n /usr/local/bin/lsmem
/usr/local/bin/lsmem record
/usr/local/bin/lsmem checkpoint installed
/usr/local/bin/lsmem test
/usr/local/bin/lsmem facts
printf '\nREADY: lsmem next | lsmem pick | lsmem history | lsmem db\n'