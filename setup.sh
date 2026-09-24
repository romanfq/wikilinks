#!/usr/bin/env bash
# Download the Simple English Wikipedia dumps and build the link graph.
# Roughly 150 MB of downloads and under a minute of processing.
set -euo pipefail
cd "$(dirname "$0")"

BASE=https://dumps.wikimedia.org/simplewiki/latest
mkdir -p data

echo "==> Checking Python dependencies"
python3 -c "import numpy" 2>/dev/null || {
  echo "numpy is missing. Install it with:  pip3 install -r requirements.txt" >&2
  exit 1
}

echo "==> Downloading dumps (~150 MB)"
for f in page pagelinks linktarget redirect; do
  if [ -s "data/simplewiki-$f.sql.gz" ]; then
    echo "    data/simplewiki-$f.sql.gz already present, skipping"
  else
    echo "    $f"
    curl -fL --progress-bar -o "data/simplewiki-$f.sql.gz" \
      "$BASE/simplewiki-latest-$f.sql.gz"
  fi
done

echo "==> Building the link graph"
python3 build_graph.py
python3 build_redirects.py

echo
echo "Done. Start the game with:  python3 server.py"
