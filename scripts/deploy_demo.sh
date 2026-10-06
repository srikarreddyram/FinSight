#!/bin/zsh
# Publish the hosted demo: build the web app in demo mode against the snapshot in web/public/demo (made by
# scripts/build_demo.py) and force-push the result to the gh-pages branch, which GitHub Pages serves at
# https://srikarreddyram.github.io/FinSight/.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f web/public/demo/recs/meta.json ] || { echo "No snapshot: run 'uv run python scripts/build_demo.py' first"; exit 1; }
AS_OF=$(python3 -c "import json; print(json.load(open('web/public/demo/moves/scan_1w.json'))['as_of'])")
REMOTE=$(git remote get-url origin)
NAME=$(git config user.name)
EMAIL=$(git config user.email)
cd web
VITE_DEMO=1 VITE_DEMO_AS_OF="$(date -j -f %Y-%m-%d "$AS_OF" '+%b %-d, %Y')" FINSIGHT_BASE=/FinSight/ npm run build
touch dist/.nojekyll  # serve files as they are (no Jekyll processing)
cd dist
rm -rf .git
git init -q -b gh-pages
git add -A
git -c user.name="$NAME" -c user.email="$EMAIL" commit -q -m "Demo snapshot, prices to $AS_OF"
git push -q -f "$REMOTE" gh-pages
rm -rf .git
echo "Published to the gh-pages branch."
