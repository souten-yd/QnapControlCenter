#!/bin/sh
# QTS QPKG service. All normal logs are in volatile /var/run.
# Reconcile stale/orphaned *owned* server processes on upgrade.
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
  [ -n "$BASE" ] && [ -d "$BASE/disk_inspector" ] &&
    [ -r "$BASE/disk_inspector/server.py" ]
}
detect_python() {
  for candidate in /opt/bin/python3.11 /opt/bin/python3.12 /opt/bin/python3 /usr/local/bin/python3 /usr/bin/python3 /usr/bin/python3.11; do
    [ -x "$candidate" ] || continue
    "$candidate" -B -c 'import sys; assert sys.version_info >= (3, 9)' >/dev/null 2>&1 || continue
    PYTHON="$candidate"
    return 0
  done
  return 1
}
pid_live() {
  pid="$1"
  case "$pid" in ''|*[!0-9]*) return 1;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  [ -r "/proc/$pid/stat" ] || return 1
  state="$(sed 's/^.*) //' "/proc/$pid/stat" 2>/dev/null | cut -c1)"
  [ "$state" != Z ] && [ -n "$state" ]
}
# Only the exact QPKG installation root AND exact service command are trusted.
# Never terminate a PID based on a stale pidfile or shared module name alone.
owned_pid() {
  pid="$1"
  case "$pid" in ''|*[!0-9]*) return 1;; esac
  [ -n "$BASE" ] || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  # First cheaply filter by QPKG cwd: only inspect cmdline and liveness of
  # processes that actually started inside this installation.
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)" || return 1
  # QTS may replace/remove the old package directory during an upgrade.
  # A still-live former service then has cwd exactly "$BASE (deleted)".
  # Only accept this single kernel readlink suffix, never a prefix/substring.
  case "$cwd" in
    "$BASE"|"$BASE (deleted)") ;;
    *) return 1 ;;
  esac
  # Read NUL-separated argv without BusyBox tr quoting/escape differences.
  # This is invoked only for PIDs whose cwd matches the exact QPKG directory.
  [ -n "$PYTHON" ] || return 1
  "$PYTHON" -B -c '
import os, re, sys
try:
    with open("/proc/%s/cmdline" % sys.argv[1], "rb") as file:
        argv = [x.decode("utf-8", "strict") for x in file.read().split(b"\x00") if x]
    expected = ["-B", "-m", "disk_inspector.server",
                "--host", "0.0.0.0", "--port", "8778"]
    valid = (len(argv) == 1 + len(expected)
             and re.fullmatch(r"python3(?:\.[0-9]+)?", os.path.basename(argv[0]))
             and argv[1:] == expected)
    sys.exit(0 if valid else 1)
except (OSError, UnicodeError, ValueError):
    sys.exit(1)
' "$pid" >/dev/null 2>&1 || return 1
  pid_live "$pid"
}
owned_processes() {
  for dir in /proc/[0-9]*; do
    candidate="${dir##*/}"
    if owned_pid "$candidate"; then
      printf '%s\n' "$candidate"
    fi
  done
}
# Successful HTTP from an OLD listener is not health.
# Require that the responding process is the new child and its build_id
# agrees with the QPKG metadata. No network resource other than loopback.
serving_expected_build() {
  expected_pid="$1"
  [ -r "$BASE/disk_inspector/build_info.json" ] || return 1
  QCC_EXPECTED_INFO="$BASE/disk_inspector/build_info.json" \
  QCC_EXPECTED_PID="$expected_pid" "$PYTHON" -B -c '
import json, os, sys
from urllib.request import urlopen
try:
    with open(os.environ["QCC_EXPECTED_INFO"], encoding="utf-8") as file:
        expected = json.load(file)
    with urlopen("http://127.0.0.1:8778/api/runtime", timeout=1) as response:
        running = json.load(response)
    matching = (
        expected.get("build_id")
        and running.get("build_id") == expected["build_id"]
        and running.get("pid") == int(os.environ["QCC_EXPECTED_PID"])
        and running.get("features", {}).get("write_diagnostics") is True
    )
    sys.exit(0 if matching else 1)
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(1)
' >/dev/null 2>&1
}
port_available() {
  "$PYTHON" -B -c '
import socket, sys
s = socket.socket()
try:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 8778))
except OSError:
    sys.exit(1)
finally:
    s.close()
' >/dev/null 2>&1
}
stop_owned() {
  target="$1"
  owned_pid "$target" || return 0
  write_log "Stopping owned QnapControlCenter server PID=$target"
  kill "$target" 2>/dev/null || return 1
  wait_count=0
  while owned_pid "$target"; do
    if [ "$wait_count" -ge 8 ]; then
      write_log "ERROR: owned server PID=$target did not stop after 8s"
      return 1
    fi
    wait_count=$((wait_count + 1))
    sleep 1
  done
  return 0
}
reconcile_owned() {
  # An orphan process may own port 8778 even when the pidfile is stale.
  # Scan /proc only on service lifecycle operations, never on sampling ticks.
  for candidate in $(owned_processes); do
    if [ "$1" = start ] && serving_expected_build "$candidate"; then
      write_log "Reusing verified running build pid=$candidate"
      echo "$candidate" > "$PIDFILE"
      return 2
    fi
    stop_owned "$candidate" || return 1
  done
  return 0
}
start_service() {
  if ! enabled; then
    write_log "INFO: QPKG Enable is not TRUE; refusing auto-start"
    return 1
  fi
  count=0
  until resolve_base && detect_python; do
    count=$((count + 1))
    if [ "$count" -ge 60 ]; then
      write_log "ERROR: dependency timeout (60s): Install_Path=$BASE Python=$PYTHON"
      return 1
    fi
    if [ "$count" -eq 1 ] || [ $((count % 15)) -eq 0 ]; then
      write_log "Waiting for QPKG volume / Python (attempt=$count)"
    fi
    sleep 1
  done
  if [ -f "$PIDFILE" ]; then
    recorded="$(cat "$PIDFILE" 2>/dev/null)"
    if ! owned_pid "$recorded"; then
      write_log "Stale PID file ($recorded); reconciling /proc before startup"
    fi
  fi
  result=0
  reconcile_owned start || result=$?
  if [ "$result" -eq 2 ]; then return 0; fi
  [ "$result" -eq 0 ] || return 1
  rm -f "$PIDFILE"
  if ! port_available; then
    write_log "ERROR: port 8778 is occupied by a non-owned process or lingering listener; refusing false startup success"
    return 1
  fi
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
  count=0
  while [ "$count" -lt 20 ]; do
    if ! pid_live "$child"; then
      write_log "ERROR: new server PID=$child terminated before HTTP ready"
      rm -f "$PIDFILE"
      return 1
    fi
    if owned_pid "$child" && serving_expected_build "$child"; then
      write_log "Web UI ready with verified PID=$child build; http://NAS-IP:8778/"
      return 0
    fi
    count=$((count + 1))
    sleep 1
  done
  write_log "ERROR: new server PID=$child failed PID/build identity check (20s); refusing false ready"
  if owned_pid "$child"; then stop_owned "$child" || :; fi
  rm -f "$PIDFILE"
  return 1
}
stop_service() {
  if ! resolve_base || ! detect_python; then
    write_log "ERROR: cannot identify installed QPKG root; refusing to kill unknown PIDs"
    return 1
  fi
  recorded="$(cat "$PIDFILE" 2>/dev/null)"
  if [ -n "$recorded" ] && ! owned_pid "$recorded"; then
    write_log "Stale PID file ($recorded); searching for orphaned owned server"
  fi
  reconcile_owned stop || return 1
  rm -f "$PIDFILE"
  write_log "QnapControlCenter servers stopped"
}
status_service() {
  if ! enabled; then echo disabled; return 1; fi
  resolve_base && detect_python || { echo stopped; return 1; }
  for candidate in $(owned_processes); do
    echo running
    return 0
  done
  echo stopped
  return 1
}
case "$1" in
  start) start_service ;;
  stop) stop_service ;;
  restart) stop_service && start_service ;;
  status) status_service ;;
  *) echo "Usage: $0 {start|stop|restart|status}"; exit 2 ;;
esac
