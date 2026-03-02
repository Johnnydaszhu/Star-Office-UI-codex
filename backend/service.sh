#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$ROOT_DIR/backend/server.pid"
LOG_FILE="$ROOT_DIR/backend/server.log"
PYTHON_BIN="${STAR_OFFICE_PYTHON:-$ROOT_DIR/.venv/bin/python}"
PORT="${STAR_OFFICE_PORT:-18791}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

is_running() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  ps -p "$pid" >/dev/null 2>&1
}

start_service() {
  if is_running; then
    echo "Star Office already running (pid=$(cat "$PID_FILE"))."
    return 0
  fi

  if lsof -ti "tcp:${PORT}" >/dev/null 2>&1; then
    echo "Port ${PORT} is already in use. Stop the other process first."
    return 1
  fi

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Python runtime not found: $PYTHON_BIN"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
    return 1
  fi

  if [[ ! -f "$ROOT_DIR/state.json" ]] && [[ -f "$ROOT_DIR/state.sample.json" ]]; then
    cp "$ROOT_DIR/state.sample.json" "$ROOT_DIR/state.json"
  fi

  nohup "$PYTHON_BIN" "$ROOT_DIR/backend/app.py" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  for _ in {1..30}; do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      echo "Star Office started: $HEALTH_URL (pid=$(cat "$PID_FILE"))"
      return 0
    fi
    sleep 0.5
  done

  echo "Failed to start Star Office. Last logs:"
  tail -n 60 "$LOG_FILE" || true
  return 1
}

stop_service() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "Star Office is not running."
    return 0
  fi

  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" >/dev/null 2>&1 || true

  for _ in {1..10}; do
    if ! ps -p "$pid" >/dev/null 2>&1; then
      rm -f "$PID_FILE"
      echo "Star Office stopped."
      return 0
    fi
    sleep 0.5
  done

  kill -9 "$pid" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
  echo "Star Office force stopped."
}

status_service() {
  if is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    echo "Star Office running (pid=${pid})"
    curl -fsS "$HEALTH_URL" || true
    echo
    return 0
  fi
  echo "Star Office is not running."
  return 1
}

show_logs() {
  if [[ ! -f "$LOG_FILE" ]]; then
    echo "No log file yet: $LOG_FILE"
    return 0
  fi
  tail -n 80 "$LOG_FILE"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") <start|stop|restart|status|logs>
EOF
}

cmd="${1:-}"
case "$cmd" in
  start)
    start_service
    ;;
  stop)
    stop_service
    ;;
  restart)
    stop_service
    start_service
    ;;
  status)
    status_service
    ;;
  logs)
    show_logs
    ;;
  *)
    usage
    exit 1
    ;;
esac
