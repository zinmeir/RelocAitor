#!/usr/bin/env bash
# RelocAitor: one-command setup & run for macOS / Linux.
#   ./run.sh          set up venv, install deps, start the app, open the browser
#   ./run.sh test     same setup, then run the test suite instead
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || { echo "ERROR: $PY not found. Install Python 3.10+."; exit 1; }

for f in app.py data/countries.csv data/visas.json templates/index.html static/js/app.js; do
  [ -f "$f" ] || { echo "ERROR: missing $f"; exit 1; }
done

if [ ! -f venv/bin/activate ]; then
  echo "Creating virtual environment…"
  "$PY" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

if ! python -c "import flask, pandas, numpy" >/dev/null 2>&1 || [ "${1:-}" = "test" ]; then
  echo "Installing dependencies…"
  python -m pip install --upgrade pip --quiet
  pip install -r requirements-dev.txt --quiet
fi

if [ ! -f ml/models/all-MiniLM-L6-v2/model.onnx ]; then
  echo "Downloading the sentence-embedding model for semantic search (~90 MB, once)…"
  python -m ml.build_semantic_index --model-only || echo "  (skipped: semantic search will use keywords until the model is downloaded)"
fi

if [ "${1:-}" = "test" ]; then
  exec python -m pytest -q
fi

URL="http://localhost:${PORT:-5000}"
echo "Starting RelocAitor at $URL  (Ctrl+C to stop)"
( sleep 2; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) >/dev/null 2>&1 &
exec python app.py
