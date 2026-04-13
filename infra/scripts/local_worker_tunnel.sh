#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi
HOST="${RUNPOD_HOST:-}"
USER="${RUNPOD_USER:-root}"
SSH_KEY_PATH="${RUNPOD_SSH_KEY_PATH:-}"
SSH_PORT="${RUNPOD_SSH_PORT:-22}"
SOCKET_PATH="${RUNPOD_REVERSE_TUNNEL_SOCKET:-$ROOT_DIR/run/local-worker-tunnel.sock}"

LOCAL_POSTGRES_PORT="${LOCAL_POSTGRES_PORT:-5433}"
LOCAL_REDIS_PORT="${LOCAL_REDIS_PORT:-6380}"
LOCAL_API_PORT="${LOCAL_API_PORT:-18000}"

REMOTE_POSTGRES_PORT="${RUNPOD_REVERSE_TUNNEL_POSTGRES_PORT:-15432}"
REMOTE_REDIS_PORT="${RUNPOD_REVERSE_TUNNEL_REDIS_PORT:-16379}"
REMOTE_API_PORT="${RUNPOD_REVERSE_TUNNEL_API_PORT:-18000}"

if [[ -z "$HOST" || -z "$USER" || -z "$SSH_KEY_PATH" ]]; then
  echo "RUNPOD_HOST, RUNPOD_USER, and RUNPOD_SSH_KEY_PATH are required." >&2
  exit 1
fi

REMOTE="$USER@$HOST"
SSH_BASE_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=no
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -S "$SOCKET_PATH"
)

mkdir -p "$(dirname "$SOCKET_PATH")"

check_socket() {
  ssh "${SSH_BASE_OPTS[@]}" -O check "$REMOTE" >/dev/null 2>&1
}

start_tunnel() {
  if check_socket; then
    echo "local worker tunnel already running"
    return 0
  fi

  rm -f "$SOCKET_PATH"
  ssh "${SSH_BASE_OPTS[@]}" \
    -M \
    -fNT \
    -o ExitOnForwardFailure=yes \
    -R "${REMOTE_POSTGRES_PORT}:127.0.0.1:${LOCAL_POSTGRES_PORT}" \
    -R "${REMOTE_REDIS_PORT}:127.0.0.1:${LOCAL_REDIS_PORT}" \
    -R "${REMOTE_API_PORT}:127.0.0.1:${LOCAL_API_PORT}" \
    "$REMOTE"

  ssh "${SSH_BASE_OPTS[@]}" -O check "$REMOTE"
}

stop_tunnel() {
  if ! check_socket; then
    echo "local worker tunnel not running"
    rm -f "$SOCKET_PATH"
    return 0
  fi
  ssh "${SSH_BASE_OPTS[@]}" -O exit "$REMOTE"
  rm -f "$SOCKET_PATH"
}

status_tunnel() {
  if ! check_socket; then
    echo "local worker tunnel not running"
    return 1
  fi
  echo "local worker tunnel running"
  echo "remote postgres: 127.0.0.1:${REMOTE_POSTGRES_PORT} -> local 127.0.0.1:${LOCAL_POSTGRES_PORT}"
  echo "remote redis: 127.0.0.1:${REMOTE_REDIS_PORT} -> local 127.0.0.1:${LOCAL_REDIS_PORT}"
  echo "remote api: 127.0.0.1:${REMOTE_API_PORT} -> local 127.0.0.1:${LOCAL_API_PORT}"
}

case "${1:-status}" in
  start)
    start_tunnel
    ;;
  stop)
    stop_tunnel
    ;;
  restart)
    stop_tunnel
    start_tunnel
    ;;
  status)
    status_tunnel
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}" >&2
    exit 1
    ;;
esac
