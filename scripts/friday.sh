#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${FRIDAY_HOST:-127.0.0.1}"
PORT="${FRIDAY_PORT:-8765}"
PYTHON_BIN="${FRIDAY_PYTHON:-$ROOT_DIR/.venv/bin/python}"
PID_FILE="${TMPDIR:-/tmp}/friday-local-assistant.pid"
LOG_FILE="${TMPDIR:-/tmp}/friday-local-assistant.log"
LAUNCHD_LOG_FILE="${TMPDIR:-/tmp}/friday-local-assistant.launchd.log"
LAUNCHD_ERR_FILE="${TMPDIR:-/tmp}/friday-local-assistant.launchd.err"
STATUS_URL="http://$HOST:$PORT/api/status"
LAUNCH_LABEL="com.friday.local-assistant"
LAUNCH_DOMAIN="gui/$(id -u)"
LAUNCH_PLIST="$HOME/Library/LaunchAgents/$LAUNCH_LABEL.plist"
SCREEN_NAME="friday-local-assistant"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

is_http_ready() {
  curl -fsS --max-time 2 "$STATUS_URL" >/dev/null 2>&1
}

pid_is_alive() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi
  local pid_value
  pid_value="$(cat "$PID_FILE")"
  if [[ "$pid_value" == screen:* ]]; then
    screen_is_alive
    return $?
  fi
  kill -0 "$pid_value" >/dev/null 2>&1
}

screen_is_alive() {
  command -v screen >/dev/null 2>&1 || return 1
  screen -ls 2>/dev/null | grep -q "[.]$SCREEN_NAME[[:space:]]"
}

find_running_pid() {
  pgrep -f "$ROOT_DIR/main.py" | head -n 1 || true
}

start_friday() {
  if is_http_ready; then
    echo "FRIDAY is already online at http://$HOST:$PORT"
    return 0
  fi

  if [[ -f "$LAUNCH_PLIST" ]]; then
    launchctl kickstart -k "$LAUNCH_DOMAIN/$LAUNCH_LABEL" >/dev/null 2>&1 || true
    for _ in {1..40}; do
      if is_http_ready; then
        echo "FRIDAY is online at http://$HOST:$PORT"
        return 0
      fi
      sleep 0.5
    done
  fi

  local existing_pid
  existing_pid="$(find_running_pid)"
  if [[ -n "$existing_pid" ]]; then
    echo "$existing_pid" > "$PID_FILE"
    echo "FRIDAY process is already starting with pid $existing_pid"
  elif command -v screen >/dev/null 2>&1 && [[ "${FRIDAY_USE_SCREEN:-1}" != "0" ]]; then
    screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
    screen -dmS "$SCREEN_NAME" zsh -lc "cd \"$ROOT_DIR\" && exec \"$PYTHON_BIN\" \"$ROOT_DIR/main.py\" --host \"$HOST\" --port \"$PORT\" > \"$LOG_FILE\" 2>&1"
    echo "screen:$SCREEN_NAME" > "$PID_FILE"
    echo "Started FRIDAY in detached screen session $SCREEN_NAME"
  else
    cd "$ROOT_DIR"
    nohup "$PYTHON_BIN" "$ROOT_DIR/main.py" --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "Started FRIDAY with pid $(cat "$PID_FILE")"
  fi

  for _ in {1..40}; do
    if is_http_ready; then
      echo "FRIDAY is online at http://$HOST:$PORT"
      return 0
    fi
    sleep 0.5
  done

  echo "FRIDAY did not become ready. Last log lines:"
  tail -n 30 "$LOG_FILE" 2>/dev/null || true
  return 1
}

stop_friday() {
  local stopped=0
  if [[ -f "$LAUNCH_PLIST" ]]; then
    launchctl bootout "$LAUNCH_DOMAIN/$LAUNCH_LABEL" >/dev/null 2>&1 || true
  fi
  if screen_is_alive; then
    screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
    stopped=1
  fi
  if pid_is_alive; then
    kill "$(cat "$PID_FILE")" >/dev/null 2>&1 || true
    stopped=1
  fi
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" >/dev/null 2>&1 || true
    stopped=1
  done < <(pgrep -f "$ROOT_DIR/main.py" || true)
  rm -f "$PID_FILE"
  if [[ "$stopped" -eq 1 ]]; then
    echo "Stopped FRIDAY."
  else
    echo "FRIDAY was not running."
  fi
}

install_friday() {
  if [[ "$ROOT_DIR" == "$HOME/Documents/"* ]]; then
    echo "Cannot install LaunchAgent while FRIDAY lives under Documents."
    echo "macOS blocks background agents from reading protected Documents folders."
    echo "Move the project outside Documents or run: $0 start"
    return 1
  fi
  mkdir -p "$(dirname "$LAUNCH_PLIST")"
  stop_friday >/dev/null 2>&1 || true
  cat > "$LAUNCH_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LAUNCH_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$ROOT_DIR/main.py</string>
    <string>--host</string>
    <string>$HOST</string>
    <string>--port</string>
    <string>$PORT</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LAUNCHD_LOG_FILE</string>
  <key>StandardErrorPath</key>
  <string>$LAUNCHD_ERR_FILE</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST
  launchctl bootstrap "$LAUNCH_DOMAIN" "$LAUNCH_PLIST" >/dev/null 2>&1 || {
    launchctl bootout "$LAUNCH_DOMAIN/$LAUNCH_LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$LAUNCH_DOMAIN" "$LAUNCH_PLIST"
  }
  launchctl enable "$LAUNCH_DOMAIN/$LAUNCH_LABEL" >/dev/null 2>&1 || true
  launchctl kickstart -k "$LAUNCH_DOMAIN/$LAUNCH_LABEL" >/dev/null 2>&1 || true
  echo "Installed FRIDAY LaunchAgent: $LAUNCH_PLIST"
  start_friday
}

uninstall_friday() {
  launchctl bootout "$LAUNCH_DOMAIN/$LAUNCH_LABEL" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_PLIST" "$PID_FILE"
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" >/dev/null 2>&1 || true
  done < <(pgrep -f "$ROOT_DIR/main.py" || true)
  echo "Uninstalled FRIDAY LaunchAgent."
}

status_friday() {
  if is_http_ready; then
    echo "FRIDAY is online at http://$HOST:$PORT"
    curl -s "$STATUS_URL"
    echo
    return 0
  fi
  if screen_is_alive; then
    echo "FRIDAY screen session exists but the HTTP server is not ready yet: $SCREEN_NAME"
    return 1
  fi
  if pid_is_alive; then
    echo "FRIDAY process exists but the HTTP server is not ready yet. pid $(cat "$PID_FILE")"
    return 1
  fi
  echo "FRIDAY is not running."
  return 1
}

case "${1:-start}" in
  start)
    start_friday
    ;;
  stop)
    stop_friday
    ;;
  restart)
    stop_friday
    start_friday
    ;;
  install)
    install_friday
    ;;
  uninstall)
    uninstall_friday
    ;;
  status)
    status_friday
    ;;
  *)
    echo "Usage: $0 [start|stop|restart|status|install|uninstall]"
    exit 2
    ;;
esac
