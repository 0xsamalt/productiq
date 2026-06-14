#!/usr/bin/env bash
# Quick start. Run from anywhere — the script cd's into productiq/backend/.
#
# What it does:
#   1. Auto-detects conda (anaconda3 / miniconda3 / miniforge3 / /opt/conda).
#      Falls back to a local .venv if no conda is installed.
#   2. Creates an env called 'productiq' (Python 3.11) on first run.
#   3. Installs requirements.txt into that env.
#   4. Loads backend/.env and launches uvicorn on $APP_HOST:$APP_PORT (default 0.0.0.0:8000).
#
# Prereqs (for judges):
#   - cp .env.example .env  → fill in MOSS_PROJECT_ID / MOSS_PROJECT_KEY / HF_TOKEN.
#   - bash run.sh           → open http://localhost:8000 once it says "Application startup complete".
set -euo pipefail

cd "$(dirname "$0")"

# Sanity check: .env must exist with credentials before we boot.
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "!! Created backend/.env from .env.example."
    echo "!! Open backend/.env and fill in:"
    echo "     MOSS_PROJECT_ID  (https://moss.dev dashboard)"
    echo "     MOSS_PROJECT_KEY (https://moss.dev dashboard)"
    echo "     HF_TOKEN         (huggingface.co/settings/tokens — fine-grained, with 'Inference Providers' scope)"
    echo "!! Then re-run: bash run.sh"
    exit 1
  fi
  echo "ERROR: neither .env nor .env.example found in $(pwd)" >&2
  exit 1
fi

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
  CONDA_BIN="$CONDA_BASE/bin/conda"

  # Look up the env's actual location via conda (handles custom envs_dirs).
  resolve_env_dir() {
    "$CONDA_BIN" env list 2>/dev/null \
      | awk -v n="$ENV_NAME" '$1==n {print $NF; exit}'
  }

  ENV_DIR="$(resolve_env_dir)"
  if [ -z "$ENV_DIR" ] || [ ! -x "$ENV_DIR/bin/python" ]; then
    echo ">> creating conda env '$ENV_NAME' (Python $PY_VERSION)"
    "$CONDA_BIN" create -n "$ENV_NAME" "python=$PY_VERSION" -y
    ENV_DIR="$(resolve_env_dir)"
  fi

  if [ -z "$ENV_DIR" ] || [ ! -x "$ENV_DIR/bin/python" ]; then
    echo "ERROR: could not locate conda env '$ENV_NAME' after creation." >&2
    "$CONDA_BIN" env list >&2
    exit 1
  fi
  ENV_PY="$ENV_DIR/bin/python"
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
