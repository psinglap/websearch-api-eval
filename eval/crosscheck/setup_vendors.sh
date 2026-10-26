#!/usr/bin/env bash
# Clone the two vendor-published harnesses at the commits we verified and give each its own venv.
#   youdotcom-oss/web-search-api-evals  2e3e1b5 (2026-10-08)  Python >=3.10,<3.14
#   tavily-ai/tavily-search-evals       99feb7d (2026-01-29)
set -euo pipefail
cd "$(dirname "$0")"
UV="${UV:-$HOME/.local/bin/uv}"
mkdir -p vendor && cd vendor
clone() { # repo dir commit
  if [ ! -d "$2/.git" ]; then git clone -q "https://github.com/$1.git" "$2"; fi
  git -C "$2" fetch -q --depth 50 origin || true
  git -C "$2" checkout -q "$3" 2>/dev/null || echo "WARN: commit $3 not found in $1; using $(git -C "$2" rev-parse --short HEAD)"
}
clone youdotcom-oss/web-search-api-evals web-search-api-evals 2e3e1b5
clone tavily-ai/tavily-search-evals tavily-search-evals 99feb7d
for d in web-search-api-evals tavily-search-evals; do
  "$UV" venv -q --python 3.12 "$d/.venv"
  "$UV" pip install -q --python "$d/.venv/bin/python" -r "$d/requirements.txt"
done
"$UV" pip install -q --python web-search-api-evals/.venv/bin/python -e web-search-api-evals
echo "vendor harnesses ready in crosscheck/vendor/ (each has its own .venv)"
