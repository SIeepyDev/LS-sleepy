#!/bin/sh
set -e
B=/opt/ls-crew/lxcs
mkdir -p "$B"
need(){
 for c in pct pveam pvesm pvesh; do
   command -v "$c" >/dev/null 2>&1 || { echo "Missing $c (needs Proxmox)" >&2; exit 1; }
 done
}
probe(){
 need
 echo '== LXCs =='; pct list
 echo '== Template storage =='; pvesm status -content vztmpl
 echo '== Root storage =='; pvesm status -content rootdir
 echo '== Alpine =='; pveam available --section system | grep alpine | tail -3 || :
}
new(){
 need
 [ "$1" = alpine ] || { echo 'Use: crewlxc new alpine'; exit 2; }
 t=$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active"{print $1;exit}')
 r=$(pvesm status -content rootdir | awk 'NR>1 && $3=="active"{print $1;exit}')
 [ -n "$t" ] && [ -n "$r" ] || { echo 'No active template/root storage'; exit 1; }
 template=$(pveam available --section system | awk '$2~/^alpine-/ && $2~/amd64/{print $2}' | sort -V | tail -1)
 if [ -z "$template" ]; then
   pveam update
   template=$(pveam available --section system | awk '$2~/^alpine-/ && $2~/amd64/{print $2}' | sort -V | tail -1)
 fi
 [ -n "$template" ] || { echo 'No Alpine template'; exit 1; }
 id=$(pvesh get /cluster/nextid)
 echo "CREATING crew-$id using $template"
 pveam list "$t" | grep -Fq "$template" || pveam download "$t" "$template"
 pct create "$id" "$t:vztmpl/$template" --hostname "crew-$id" --cores 1 --memory 256 --swap 256 --rootfs "$r:2" --unprivileged 1 --onboot 0 --net0 name=eth0,bridge=vmbr0,ip=dhcp
 pct set "$id" --tags 'crewlab;disposable;atomic'
 pct start "$id"
 ip=pending
 n=0
 while [ "$n" -lt 25 ]; do
   got=$(pct exec "$id" -- sh -c 'ip -4 addr show eth0 2>/dev/null | awk "/inet /{print \$2;exit}"' 2>/dev/null || :)
   if [ -n "$got" ]; then ip="$got"; break; fi
   n=$((n+1)); sleep 1
 done
 echo "IP=$ip"
 pct exec "$id" -- sh -c 'apk update && apk add --no-cache git curl jq sqlite make ca-certificates && mkdir -p /lab/src /lab/data /lab/artifacts /lab/logs'
 pct config "$id" > "$B/$id.config"
 pct exec "$id" -- sh -c 'apk info -vv' > "$B/$id.packages"
 printf '%s VMID=%s IP=%s\n' "$(date -Is)" "$id" "$ip" | tee "$B/$id.receipt"
 echo "READY crewlxc enter $id | crewlxc test $id | crewlxc recycle $id"
}
cmd="$1"
case "$cmd" in
 probe|list) probe ;;
 new) new "$2" ;;
 enter) need; pct enter "$2" ;;
 test) need; pct status "$2"; pct exec "$2" -- sh -c 'test -d /lab/src && command -v curl && command -v git && command -v jq && command -v sqlite3' ;;
 recycle)
   need
   id="$2"
   case "$id" in *[!0-9]*|'') echo 'Invalid VMID'; exit 1;; esac
   tags=$(pct config "$id" | awk -F': ' '/^tags:/{print $2}')
   case ";$tags;" in *';crewlab;'*) :;; *) echo 'Refusing untagged LXC'; exit 1;; esac
   pct config "$id" > "$B/$id.last-config"
   pct exec "$id" -- sh -c 'apk info -vv' > "$B/$id.last-packages" 2>/dev/null || :
   pct stop "$id" || :
   pct destroy "$id"
   echo "$(date -Is) recycled $id" >> "$B/recycled.log"
   echo "RECYCLED $id"
   ;;
 *) echo 'crewlxc {probe|new alpine|enter ID|test ID|recycle ID}';exit 2;;
esac
