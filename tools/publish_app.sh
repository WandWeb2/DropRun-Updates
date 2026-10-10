#!/usr/bin/env bash
# Publishes a new DropRun version to every install (run from this repo):
#   tools/publish_app.sh 1.4 5 path/to/app-release.apk "What's new"
# The publish-app workflow turns it into a release and updates updates.json.
set -euo pipefail
name=$1; code=$2; apk=$3; notes=${4:-"DropRun $name"}
mkdir -p incoming
cp "$apk" "incoming/DropRun-$name-$code.apk"
printf '%s' "$notes" > incoming/notes.txt
git add incoming && git commit -m "Publish DropRun $name" && git push
