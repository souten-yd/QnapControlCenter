#!/bin/sh
# QDK service lifecycle; no downloads or builds at startup.
BASE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PIDFILE="/var/run/qnapcontrolcenter.pid"
PYTHON="/opt/bin/python3.11"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3 2>/dev/null)"
start() {
  [ -n "$PYTHON" ] && [ -x "$PYTHON" ] || { echo "Python3 missing" >&2; return 1; }
  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE" 2>/dev/null)"
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && return 0
    rm -f "$PIDFILE"
  fi
  cd "$BASE" || return 1
  PYTHONPATH="$BASE" "$PYTHON" -m disk_inspector.server --host 0.0.0.0 --port 8778 >/dev/null 2>&1 &
  echo "$!" > "$PIDFILE"
}
stop() {
  [ -f "$PIDFILE" ] || return 0
  pid="$(cat "$PIDFILE" 2>/dev/null)"
  if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ]; then
    case "$(tr '\000' ' ' < "/proc/$pid/cmdline")" in
      *disk_inspector.server*) kill "$pid" 2>/dev/null || : ;;
      *) echo "PID ownership mismatch" >&2; return 1 ;;
    esac
  fi
  rm -f "$PIDFILE"
}
case "$1" in start) start;; stop) stop;; restart) stop && start;; *) exit 2;; esac
