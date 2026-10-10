#!/usr/bin/env bash
# Publishes a new DropRun version to every install:  tools/publish_app.sh 4 1.3 DropRun-1.3.apk "What's new"
set -euo pipefail
code=$1; name=$2; apk=$3; notes=${4:-}
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
tag="app-$name"
gh release create "$tag" "$apk#DropRun-$name.apk" --title "DropRun $name" --notes "$notes"
python3 tools/update_manifest.py app "$code" "$name" "https://github.com/$repo/releases/download/$tag/$(basename "$apk")" "$apk" "$notes"
git add updates.json && git commit -m "DropRun $name" && git push
