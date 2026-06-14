#!/usr/bin/env bash
# Quick start. Run from productiq/backend/.
#
# Portable across machines: uses conda if it's available on this machine,
# otherwise falls back to a project-local virtualenv at ./.venv.
set -euo pipefail

cd "$(dirname "$0")"

ENV_NAME="productiq"
PY_VERSION="3.11"

# Resolve a conda base from whatever this machine actually has, instead of a
# hardcoded path. Empty if conda isn't installed here.
detect_conda_base() {
  if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
    dirname "$(dirname "$CONDA_EXE")"; return
  fi
  if command -v conda >/dev/null 2>&1; then
    conda info --base 2>/dev/null && return
  fi
  for d in "$HOME/anaconda3" "$HOME/miniconda3" "$HOME/miniforge3" /opt/conda; do
    [ -x "$d/bin/conda" ] && { echo "$d"; return; }
  done
}

CONDA_BASE="$(detect_conda_base || true)"

if [ -n "$CONDA_BASE" ]; then
  # --- conda path ---
  ENV_DIR="$CONDA_BASE/envs/$ENV_NAME"
  ENV_PY="$ENV_DIR/bin/python"
  if [ ! -x "$ENV_PY" ]; then
    echo ">> creating conda env '$ENV_NAME' (Python $PY_VERSION)"
    "$CONDA_BASE/bin/conda" create -n "$ENV_NAME" "python=$PY_VERSION" -y
  fi
else
  # --- venv fallback (no conda on this machine) ---
  ENV_DIR=".venv"
  ENV_PY="$ENV_DIR/bin/python"
  if [ ! -x "$ENV_PY" ]; then
    echo ">> no conda found; creating local virtualenv at $ENV_DIR"
    python3 -m venv "$ENV_DIR"
  fi
fi

echo ">> installing requirements into $ENV_DIR"
"$ENV_PY" -m pip install -q --upgrade pip
"$ENV_PY" -m pip install -q -r requirements.txt

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
