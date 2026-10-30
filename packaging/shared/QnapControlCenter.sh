#!/bin/sh
# QTS QPKG service: bounded dependency readiness at boot; no HDD logging.
QPKG_NAME=QnapControlCenter
QPKG_CONF="${QCC_QPKG_CONF:-/etc/config/qpkg.conf}"
PIDFILE="${QCC_PIDFILE:-/var/run/qnapcontrolcenter.pid}"
LOG="${QCC_LOG:-/var/run/qnapcontrolcenter-startup.log}"
BASE=""
PYTHON=""
write_log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
config_value() {
  key="$1"
  if [ "$QPKG_CONF" = /etc/config/qpkg.conf ] && [ -x /sbin/getcfg ]; then
    /sbin/getcfg "$QPKG_NAME" "$key" -d "" -f "$QPKG_CONF" 2>/dev/null
    return
  fi
  [ -r "$QPKG_CONF" ] || return 1
  awk -v wanted="$key" '
    /^\[QnapControlCenter\][[:space:]]*$/ { active=1; next }
    /^\[/ { active=0 }
    active && index($0,"=") {
      k=substr($0,1,index($0,"=")-1); gsub(/^[[:space:]]+|[[:space:]]+$/,"",k)
      if (k==wanted) {
        v=substr($0,index($0,"=")+1); gsub(/^[[:space:]]+|[[:space:]]+$/,"",v)
        gsub(/^"|"$/,"",v); print v; exit
      }
    }
  ' "$QPKG_CONF"
}
enabled() { [ "$(config_value Enable)" = TRUE ]; }
resolve_base() {
  BASE="$(config_value Install_Path)"
  [ -n "$BASE" ] && [ -d "$BASE/disk_inspector" ] && [ -r "$BASE/disk_inspector/server.py" ]
}
detect_python() {
  for candidate in /opt/bin/python3.11 /opt/bin/python3.12 /opt/bin/python3 /usr/local/bin/python3 /usr/bin/python3 /usr/bin/python3.11; do
    [ -x "$candidate" ] || continue
    "$candidate" -B -c 'import sys; assert sys.version_info >= (3, 9)' >/dev/null 2>&1 || continue
    PYTHON="$candidate"; return 0
  done
  return 1
}
owned_pid() {
  pid="$1"
  case "$pid" in ''|*[!0-9]*) return 1;; esac
  [ -r "/proc/$pid/cmdline" ] || return 1
  case "$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" in
    *"disk_inspector.server"*) return 0 ;;
    *) return 1 ;;
  esac
}
start_service() {
  if ! enabled; then
    write_log "INFO: QPKG Enable is not TRUE; refusing auto-start"
    return 1
  fi
  if [ -f "$PIDFILE" ]; then
    old="$(cat "$PIDFILE" 2>/dev/null)"
    if owned_pid "$old" && kill -0 "$old" 2>/dev/null; then
      write_log "Already running pid=$old"; return 0
    fi
    rm -f "$PIDFILE"
  fi
  attempt=0
  until resolve_base && detect_python; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
      write_log "ERROR: dependency timeout (60s): Install_Path=$BASE Python=$PYTHON; check mounted QPKG volume and Python >=3.9"
      return 1
    fi
    if [ "$attempt" -eq 1 ] || [ $((attempt % 15)) -eq 0 ]; then
      write_log "INFO: waiting for QPKG volume / Python (attempt=$attempt)"
    fi
    sleep 1
  done
  cd "$BASE" || { write_log "ERROR: cannot cd to $BASE"; return 1; }
  if [ ! -s /var/run/qnapcontrolcenter-update-token ]; then
    umask 077
    "$PYTHON" -B -c 'import secrets;open("/var/run/qnapcontrolcenter-update-token","w").write(secrets.token_urlsafe(32))' ||
      { write_log "ERROR: could not create admin update token"; return 1; }
  fi
  write_log "Starting Python=$PYTHON base=$BASE port=8778"
  PYTHONPATH="$BASE" "$PYTHON" -B -m disk_inspector.server --host 0.0.0.0 --port 8778 >> "$LOG" 2>&1 &
  child=$!
  echo "$child" > "$PIDFILE"
  attempt=0
  while [ "$attempt" -lt 20 ]; do
    if ! owned_pid "$child" || ! kill -0 "$child" 2>/dev/null; then
      write_log "ERROR: process terminated before HTTP ready"
      rm -f "$PIDFILE"; return 1
    fi
    if "$PYTHON" -B -c 'from urllib.request import urlopen; import sys; r=urlopen("http://127.0.0.1:8778/api/status",timeout=1); sys.exit(0 if r.status == 200 else 1)' >/dev/null 2>&1; then
      write_log "Web UI ready at http://NAS-IP:8778/"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  write_log "ERROR: HTTP health check timeout (20s)"
  if owned_pid "$child"; then kill "$child" 2>/dev/null || :; fi
  rm -f "$PIDFILE"; return 1
}
stop_service() {
  [ -f "$PIDFILE" ] || return 0
  pid="$(cat "$PIDFILE" 2>/dev/null)"
  if owned_pid "$pid"; then
    kill "$pid" 2>/dev/null || :
    write_log "Stopped pid=$pid"
  else
    write_log "PID owner mismatch; no process killed"
  fi
  rm -f "$PIDFILE"
}
case "$1" in
  start) start_service ;;
  stop) stop_service ;;
  restart) stop_service && start_service ;;
  status)
    if [ -f "$PIDFILE" ] && owned_pid "$(cat "$PIDFILE" 2>/dev/null)"; then
      echo running
    elif ! enabled; then
      echo disabled; exit 1
    else
      echo stopped; exit 1
    fi ;;
  *) echo "Usage: $0 {start|stop|restart|status}"; exit 2 ;;
esac
