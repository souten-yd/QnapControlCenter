#!/bin/sh
# QTS QPKG lifecycle. Persistent log stored in tmpfs, not on the HDD.
BASE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PIDFILE="/var/run/qnapcontrolcenter.pid"
LOG="/var/run/qnapcontrolcenter-startup.log"
PORT=8778
write_log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }
detect_python() {
  for candidate in /opt/bin/python3.11 /opt/bin/python3.12 /usr/local/bin/python3 /usr/bin/python3; do
    [ -x "$candidate" ] || continue
    "$candidate" -c 'import sys; assert sys.version_info >= (3, 9)' >/dev/null 2>&1 || continue
    PYTHON="$candidate"; return 0
  done
  write_log "ERROR: no usable Python >=3.9 found"
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
  if [ -f "$PIDFILE" ]; then
    old="$(cat "$PIDFILE" 2>/dev/null)"
    if owned_pid "$old" && kill -0 "$old" 2>/dev/null; then
      write_log "Already running pid=$old"; return 0
    fi
    rm -f "$PIDFILE"
  fi
  detect_python || return 1
  [ -f "$BASE/disk_inspector/server.py" ] || { write_log "ERROR: server.py missing under $BASE"; return 1; }
  cd "$BASE" || return 1
  write_log "Starting Python=$PYTHON base=$BASE port=$PORT"
  PYTHONPATH="$BASE" "$PYTHON" -B -m disk_inspector.server --host 0.0.0.0 --port "$PORT" >> "$LOG" 2>&1 &
  child=$!
  echo "$child" > "$PIDFILE"
  attempts=0
  while [ "$attempts" -lt 12 ]; do
    if ! owned_pid "$child" || ! kill -0 "$child" 2>/dev/null; then
      write_log "ERROR: process terminated before HTTP ready"
      rm -f "$PIDFILE"; return 1
    fi
    if "$PYTHON" -B -c 'from urllib.request import urlopen; import sys; r=urlopen("http://127.0.0.1:8778/api/status",timeout=1); sys.exit(0 if r.status == 200 else 1)' >/dev/null 2>&1; then
      write_log "Web UI ready at http://NAS-IP:$PORT/"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  write_log "ERROR: HTTP health check failed"
  if owned_pid "$child"; then kill "$child" 2>/dev/null || :; fi
  rm -f "$PIDFILE"
  return 1
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
  start) start_service;;
  stop) stop_service;;
  restart) stop_service && start_service;;
  status) if [ -f "$PIDFILE" ] && owned_pid "$(cat "$PIDFILE" 2>/dev/null)"; then echo running; else echo stopped; exit 1; fi ;;
  *) echo "Usage: $0 {start|stop|restart|status}"; exit 2;;
esac
