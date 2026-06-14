#!/usr/bin/env bash
# Quick start. Run from productiq/backend/.
set -euo pipefail

CONDA_BASE="/home/shivank_g/anaconda3"
ENV_NAME="productiq"
ENV_DIR="$CONDA_BASE/envs/$ENV_NAME"
ENV_PY="$ENV_DIR/bin/python"
ENV_PIP="$ENV_DIR/bin/pip"

if [ ! -x "$ENV_PY" ]; then
  echo ">> creating conda env '$ENV_NAME' (Python 3.11)"
  "$CONDA_BASE/bin/conda" create -n "$ENV_NAME" python=3.11 -y
fi

echo ">> installing requirements with $ENV_PIP"
"$ENV_PIP" install -q --upgrade pip
"$ENV_PIP" install -q -r requirements.txt

# Load .env into environment so uvicorn child inherits MOSS/HF tokens
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo ">> launching uvicorn on ${APP_HOST:-0.0.0.0}:${APP_PORT:-8000}"
exec "$ENV_PY" -m uvicorn app.main:app \
  --host "${APP_HOST:-0.0.0.0}" \
  --port "${APP_PORT:-8000}" \
  --reload
