#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

APP_DIR="${RUNPOD_APP_DIR:-/opt/image-platform}"
HOST="${RUNPOD_HOST:-}"
USER="${RUNPOD_USER:-}"
SSH_KEY_PATH="${RUNPOD_SSH_KEY_PATH:-}"
SSH_PORT="${RUNPOD_SSH_PORT:-22}"
WORKER_ID="${WORKER_ID:-runpod-worker}"
RUNPOD_SKIP_SYNC="${RUNPOD_SKIP_SYNC:-false}"
MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-${APP_DIR}/model-cache}"
FLUX_MODEL_ID="${FLUX_MODEL_ID:-black-forest-labs/FLUX.1-Krea-dev}"
FLUX_DTYPE="${FLUX_DTYPE:-bfloat16}"
FLUX_DEVICE="${FLUX_DEVICE:-cuda}"
FLUX_ENABLE_MODEL_CPU_OFFLOAD="${FLUX_ENABLE_MODEL_CPU_OFFLOAD:-true}"
FLUX_NUM_INFERENCE_STEPS="${FLUX_NUM_INFERENCE_STEPS:-30}"
FLUX_GUIDANCE_SCALE="${FLUX_GUIDANCE_SCALE:-4.5}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cu124}"
TORCH_VERSION="${TORCH_VERSION:-2.6.0}"
CHECKPOINT_S3_BUCKET="${CHECKPOINT_S3_BUCKET:-}"
CHECKPOINT_S3_PREFIX="${CHECKPOINT_S3_PREFIX:-flux1-krea-dev}"
CHECKPOINT_S3_ENDPOINT_URL="${CHECKPOINT_S3_ENDPOINT_URL:-${S3_ENDPOINT_URL:-}}"
CHECKPOINT_S3_REGION="${CHECKPOINT_S3_REGION:-${S3_REGION:-auto}}"
CHECKPOINT_S3_ACCESS_KEY_ID="${CHECKPOINT_S3_ACCESS_KEY_ID:-${S3_ACCESS_KEY_ID:-}}"
CHECKPOINT_S3_SECRET_ACCESS_KEY="${CHECKPOINT_S3_SECRET_ACCESS_KEY:-${S3_SECRET_ACCESS_KEY:-}}"
CHECKPOINT_S3_USE_SSL="${CHECKPOINT_S3_USE_SSL:-${S3_USE_SSL:-false}}"
RUNPOD_REVERSE_TUNNEL_POSTGRES_PORT="${RUNPOD_REVERSE_TUNNEL_POSTGRES_PORT:-15432}"
RUNPOD_REVERSE_TUNNEL_REDIS_PORT="${RUNPOD_REVERSE_TUNNEL_REDIS_PORT:-16379}"

REMOTE_DATABASE_URL="${DATABASE_URL}"
REMOTE_REDIS_URL="${REDIS_URL}"

if [[ "${DATABASE_URL}" =~ @127\.0\.0\.1:5433/ || "${DATABASE_URL}" =~ @localhost:5433/ ]]; then
  REMOTE_DATABASE_URL="$(printf '%s' "${DATABASE_URL}" | sed -E "s/@(127\\.0\\.0\\.1|localhost):5433\//@127.0.0.1:${RUNPOD_REVERSE_TUNNEL_POSTGRES_PORT}\//")"
fi

if [[ "${REDIS_URL}" =~ redis://127\.0\.0\.1:6380/ || "${REDIS_URL}" =~ redis://localhost:6380/ ]]; then
  REMOTE_REDIS_URL="$(printf '%s' "${REDIS_URL}" | sed -E "s#redis://(127\\.0\\.0\\.1|localhost):6380/#redis://127.0.0.1:${RUNPOD_REVERSE_TUNNEL_REDIS_PORT}/#")"
fi

if [[ -z "$HOST" || -z "$USER" || -z "$SSH_KEY_PATH" ]]; then
  echo "RUNPOD_HOST, RUNPOD_USER and RUNPOD_SSH_KEY_PATH are required." >&2
  exit 1
fi

required_env=(
  DATABASE_URL
  REDIS_URL
  S3_ENDPOINT_URL
  S3_BUCKET
  S3_ACCESS_KEY_ID
  S3_SECRET_ACCESS_KEY
  PUBLIC_API_BASE_URL
  HF_TOKEN
)
for key in "${required_env[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "$key is required for remote worker deployment." >&2
    exit 1
  fi
done

SSH_OPTS=(
  -i "$SSH_KEY_PATH"
  -p "$SSH_PORT"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=no
)
REMOTE="$USER@$HOST"

ssh "${SSH_OPTS[@]}" "$REMOTE" 'if ! command -v rsync >/dev/null 2>&1; then export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y rsync; fi'

if [[ "$RUNPOD_SKIP_SYNC" != "true" ]]; then
  rsync -az \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'node_modules' \
    --exclude '.next' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.mypy_cache' \
    --exclude '.ruff_cache' \
    --exclude 'outputs' \
    --exclude 'storage' \
    --exclude 'tmp' \
    --exclude 'run' \
    --no-owner \
    --no-group \
    -e "ssh ${SSH_OPTS[*]}" \
    "$ROOT_DIR/" "$REMOTE:$APP_DIR/"
fi

ssh "${SSH_OPTS[@]}" "$REMOTE" bash <<EOF_REMOTE
set -euo pipefail

if [[ "\$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

\${SUDO} apt-get update
\${SUDO} apt-get install -y python3 python3-venv python3-pip git supervisor build-essential curl rsync
\${SUDO} mkdir -p "$APP_DIR" "$APP_DIR/logs" "$APP_DIR/run" "$MODEL_CACHE_DIR"
if [[ -n "$USER" ]]; then
  \${SUDO} chown -R "$USER":"$USER" "$APP_DIR"
fi
cd "$APP_DIR"

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --break-system-packages uv
fi

export PATH="/root/.local/bin:/usr/local/bin:\$PATH"
export UV_LINK_MODE=copy
uv sync --all-packages
uv pip install --python "$APP_DIR/.venv/bin/python" --reinstall --index-url "$PYTORCH_INDEX_URL" "torch==${TORCH_VERSION}"

if [[ -n "$CHECKPOINT_S3_BUCKET" ]]; then
  export SYNC_S3_BUCKET="$CHECKPOINT_S3_BUCKET"
  export SYNC_S3_PREFIX="$CHECKPOINT_S3_PREFIX"
  export SYNC_S3_ENDPOINT_URL="$CHECKPOINT_S3_ENDPOINT_URL"
  export SYNC_S3_REGION="$CHECKPOINT_S3_REGION"
  export SYNC_S3_ACCESS_KEY_ID="$CHECKPOINT_S3_ACCESS_KEY_ID"
  export SYNC_S3_SECRET_ACCESS_KEY="$CHECKPOINT_S3_SECRET_ACCESS_KEY"
  export SYNC_S3_USE_SSL="$CHECKPOINT_S3_USE_SSL"
  export SYNC_LOCAL_ROOT="$MODEL_CACHE_DIR"
  "$APP_DIR/.venv/bin/python" "$APP_DIR/infra/scripts/sync_s3_directory.py" download || true
fi

HF_HUB_DISABLE_XET="1" \
HF_HUB_ENABLE_HF_TRANSFER="0" \
HF_TOKEN="${HF_TOKEN}" \
FLUX_MODEL_ID="${FLUX_MODEL_ID}" \
MODEL_CACHE_DIR="${MODEL_CACHE_DIR}" \
"$APP_DIR/.venv/bin/python" "$APP_DIR/infra/scripts/download_flux_model.py"

if [[ -n "$CHECKPOINT_S3_BUCKET" ]]; then
  "$APP_DIR/.venv/bin/python" "$APP_DIR/infra/scripts/sync_s3_directory.py" upload
fi

python3 - <<'PY'
from pathlib import Path

template = Path("infra/scripts/worker.supervisord.conf.template").read_text()
values = {
    "APP_DIR": Path("$APP_DIR").as_posix(),
    "DATABASE_URL": "${REMOTE_DATABASE_URL}",
    "REDIS_URL": "${REMOTE_REDIS_URL}",
    "REDIS_QUEUE_NAME": "${REDIS_QUEUE_NAME:-image_jobs:v1}",
    "S3_ENDPOINT_URL": "${S3_ENDPOINT_URL}",
    "S3_REGION": "${S3_REGION:-auto}",
    "S3_BUCKET": "${S3_BUCKET}",
    "S3_ACCESS_KEY_ID": "${S3_ACCESS_KEY_ID}",
    "S3_SECRET_ACCESS_KEY": "${S3_SECRET_ACCESS_KEY}",
    "S3_USE_SSL": "${S3_USE_SSL:-false}",
    "PUBLIC_API_BASE_URL": "${PUBLIC_API_BASE_URL}",
    "HF_TOKEN": "${HF_TOKEN}",
    "FLUX_MODEL_ID": "${FLUX_MODEL_ID}",
    "MODEL_CACHE_DIR": "${MODEL_CACHE_DIR}",
    "FLUX_DTYPE": "${FLUX_DTYPE}",
    "FLUX_DEVICE": "${FLUX_DEVICE}",
    "FLUX_ENABLE_MODEL_CPU_OFFLOAD": "${FLUX_ENABLE_MODEL_CPU_OFFLOAD}",
    "FLUX_NUM_INFERENCE_STEPS": "${FLUX_NUM_INFERENCE_STEPS}",
    "FLUX_GUIDANCE_SCALE": "${FLUX_GUIDANCE_SCALE}",
    "WORKER_ID": "${WORKER_ID}",
    "HEARTBEAT_INTERVAL_SECONDS": "${HEARTBEAT_INTERVAL_SECONDS:-10}",
    "HEARTBEAT_TIMEOUT_SECONDS": "${HEARTBEAT_TIMEOUT_SECONDS:-60}",
    "PROGRESS_TIMEOUT_SECONDS": "${PROGRESS_TIMEOUT_SECONDS:-300}",
    "ENABLE_PROMPT_ENHANCER": "${ENABLE_PROMPT_ENHANCER:-false}",
}
for key, value in values.items():
    template = template.replace("{{" + key + "}}", value.replace('"', '\\"'))
Path("$APP_DIR/run/worker.conf").write_text(template)
PY

\${SUDO} ln -sf "$APP_DIR/run/worker.conf" /etc/supervisor/conf.d/image-platform-worker.conf
\${SUDO} mkdir -p /var/run/supervisor
if ! \${SUDO} service supervisor status >/dev/null 2>&1; then
  \${SUDO} service supervisor start || \${SUDO} supervisord -c /etc/supervisor/supervisord.conf
fi
\${SUDO} supervisorctl reread || true
\${SUDO} supervisorctl update || true
\${SUDO} supervisorctl restart image-platform-worker || \${SUDO} supervisorctl start image-platform-worker
\${SUDO} supervisorctl status image-platform-worker || true
EOF_REMOTE
