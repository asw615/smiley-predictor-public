#!/usr/bin/env bash
# Sanity-check the "4-5★ reviews carry no hygiene signal" assumption locally on
# an Apple Silicon Mac (tested on M4 Pro). Samples 500 random in-scope 4-5★
# reviews and runs them through the same Ollama hygiene classifier used in the
# main pipeline. Resumable — rerun to continue from the predictions CSV.
#
# Usage:
#   bash src/analysis/run_llm_hygiene_high_rating_check.sh
#   SAMPLE_SIZE=1000 bash src/analysis/run_llm_hygiene_high_rating_check.sh
#   MAX_WORKERS=6 bash src/analysis/run_llm_hygiene_high_rating_check.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

MAX_WORKERS="${MAX_WORKERS:-4}"
OLLAMA_NUM_PARALLEL_VAL="${OLLAMA_NUM_PARALLEL:-$MAX_WORKERS}"
MODEL="${MODEL:-gemma4:e4b}"
VENV_DIR="${VENV_DIR:-.venv-modeling}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REVIEWS_CSV="${REVIEWS_CSV:-data/reviews/google_reviews_full_6k.csv}"
SAMPLE_SIZE="${SAMPLE_SIZE:-500}"
SAMPLE_SEED="${SAMPLE_SEED:-20260518}"

echo "=== high-rating (4-5★) hygiene assumption check ==="
echo "repo:         $REPO_ROOT"
echo "model:        $MODEL"
echo "max-workers:  $MAX_WORKERS  (server OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL_VAL)"
echo "sample-size:  $SAMPLE_SIZE  (seed=$SAMPLE_SEED)"
echo "venv:         $VENV_DIR"
echo

if [[ ! -f "$REVIEWS_CSV" ]]; then
  echo "ERROR: $REVIEWS_CSV not found (gitignored — pull from source machine)."
  exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama not installed. Install from https://ollama.com/download"
  exit 1
fi

if ! pgrep -x ollama >/dev/null 2>&1; then
  echo "Starting Ollama server with OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL_VAL..."
  mkdir -p data/logs
  OLLAMA_NUM_PARALLEL="$OLLAMA_NUM_PARALLEL_VAL" \
    OLLAMA_KEEP_ALIVE="-1" \
    nohup ollama serve >data/logs/ollama_server.log 2>&1 &
  for _ in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi
curl -sf http://localhost:11434/api/tags >/dev/null \
  || { echo "ERROR: Ollama did not come up on :11434"; exit 1; }

if ! ollama list | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "Pulling $MODEL..."
  ollama pull "$MODEL"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating $VENV_DIR..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install -r requirements-modeling.txt
fi
PY="$VENV_DIR/bin/python"

echo
echo "=== classifying high-rated sample ==="
"$PY" -m src.features.llm_hygiene \
  --model "$MODEL" \
  --max-workers "$MAX_WORKERS" --ollama-keep-alive -1 \
  check-high-rating \
  --reviews "$REVIEWS_CSV" \
  --sample-size "$SAMPLE_SIZE" \
  --sample-seed "$SAMPLE_SEED"

echo
echo "=== done. ==="
echo "Predictions: data/processed/llm_hygiene_high_rating_check_predictions.csv"
echo "Summary:     data/processed/llm_hygiene_high_rating_check_summary.json"
