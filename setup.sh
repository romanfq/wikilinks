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

echo "==> Downloading article content (~990 MB, one-time)"
ZIM=data/wikipedia.zim
if [ -s "$ZIM" ]; then
  echo "    $ZIM already present, skipping"
else
  # Kiwix doesn't publish a stable "latest" alias the way Wikimedia's dumps
  # do, so this filename is pinned to the current release. If it 404s, find
  # the current one at https://library.kiwix.org (search "simple english
  # wikipedia", nopic variant) and update the URL below.
  curl -fL --progress-bar -o "$ZIM" \
    "https://download.kiwix.org/zim/wikipedia/wikipedia_en-simple_all_nopic_2026-06.zim"
fi

echo
echo "Done. Start the game with:  python3 server.py"
