#!/usr/bin/env bash
# Run gemma4:e4b LLM hygiene scoring on a UCloud GPU box (or any Linux box with a
# CUDA GPU). Idempotent: rerun to resume from data/processed/llm_hygiene_review_predictions.csv.
#
# Usage:
#   bash src/analysis/run_llm_hygiene_cloud.sh              # score full filtered set
#   MAX_WORKERS=12 bash src/analysis/run_llm_hygiene_cloud.sh
#   SKIP_AGGREGATE=1 bash src/analysis/run_llm_hygiene_cloud.sh   # only score, no window features
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

MAX_WORKERS="${MAX_WORKERS:-8}"
OLLAMA_NUM_PARALLEL_VAL="${OLLAMA_NUM_PARALLEL:-$MAX_WORKERS}"
MODEL="${MODEL:-gemma4:e4b}"
VENV_DIR="${VENV_DIR:-.venv-modeling}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REVIEWS_CSV="${REVIEWS_CSV:-data/reviews/google_reviews_full_6k.csv}"

echo "=== smiley-predictor LLM hygiene scoring ==="
echo "repo:         $REPO_ROOT"
echo "model:        $MODEL"
echo "max-workers:  $MAX_WORKERS  (server OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL_VAL)"
echo "venv:         $VENV_DIR"
echo

# --- 1. sanity-check the scraped reviews are present (NOT in git, must be transferred) ---
if [[ ! -f "$REVIEWS_CSV" ]]; then
  echo "ERROR: $REVIEWS_CSV not found."
  echo "  This file is gitignored — transfer it from the source machine before running."
  echo "  Example:  rsync -avzP user@source:'<path>/$REVIEWS_CSV' '$REVIEWS_CSV'"
  exit 1
fi

# --- 2. install ollama if missing ---
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi

# --- 3. start ollama server (background) with the requested parallelism ---
if ! pgrep -x ollama >/dev/null 2>&1; then
  echo "Starting Ollama server with OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL_VAL..."
  mkdir -p data/logs
  OLLAMA_NUM_PARALLEL="$OLLAMA_NUM_PARALLEL_VAL" \
    OLLAMA_KEEP_ALIVE="-1" \
    nohup ollama serve >data/logs/ollama_server.log 2>&1 &
  OLLAMA_PID=$!
  echo "  ollama PID=$OLLAMA_PID, log=data/logs/ollama_server.log"
  # wait for it to come up
  for _ in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi
curl -sf http://localhost:11434/api/tags >/dev/null \
  || { echo "ERROR: Ollama did not come up on :11434"; exit 1; }

# --- 4. pull the model if missing ---
if ! ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "Pulling $MODEL..."
  ollama pull "$MODEL"
fi

# --- 5. modeling venv ---
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating $VENV_DIR..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r requirements-modeling.txt
fi
PY="$VENV_DIR/bin/python"

# --- 6. score (resumable; skips review_ids already in the predictions CSV) ---
echo
echo "=== scoring reviews (resumes from data/processed/llm_hygiene_review_predictions.csv) ==="
"$PY" -m src.features.llm_hygiene \
  --model "$MODEL" \
  --max-workers "$MAX_WORKERS" --ollama-keep-alive -1 \
  score-full-reviews

# --- 7. optional: aggregate to window-level features ---
if [[ "${SKIP_AGGREGATE:-0}" != "1" ]]; then
  if [[ -f data/processed/panel.parquet ]]; then
    echo
    echo "=== aggregating window features ==="
    "$PY" -m src.features.llm_hygiene aggregate-windows
  else
    echo "(skipping aggregate-windows: data/processed/panel.parquet not found)"
  fi
fi

echo
echo "=== done. ==="
echo "Don't forget to push data/processed/llm_hygiene_review_predictions.csv back to git"
echo "so you can resume on another machine if needed:"
echo "  git add data/processed/llm_hygiene_review_predictions.csv"
echo "  git commit -m \"...\""
echo "  git push"
