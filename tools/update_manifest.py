#!/usr/bin/env python3
"""Updates updates.json: the list every DropRun install reads to keep itself current.

  update_manifest.py map  <region> <name> <download-url> <meta.json>
  update_manifest.py app  <versionCode> <versionName> <download-url> <apk-file> "<notes>"
"""
import hashlib, json, os, sys

PATH = "updates.json"
m = json.load(open(PATH)) if os.path.exists(PATH) else {"format": 1, "app": None, "maps": []}

kind = sys.argv[1]
if kind == "map":
    region, name, url, meta = sys.argv[2:6]
    info = json.load(open(meta))
    entry = {"region": region, "name": name, "url": url, "built": info["built"], "sha256": info["sha256"],
             "bytes": info["bytes"], "bbox": info["bbox"]}
    m["maps"] = [x for x in m["maps"] if x["region"] != region] + [entry]
    m["maps"].sort(key=lambda x: x["region"])
elif kind == "app":
    code, name, url, apk, notes = sys.argv[2:7]
    sha = hashlib.sha256(open(apk, "rb").read()).hexdigest()
    m["app"] = {"versionCode": int(code), "versionName": name, "url": url, "sha256": sha, "notes": notes}
else:
    sys.exit("usage: map|app ...")
json.dump(m, open(PATH, "w"), indent=2)
print(f"updated {PATH}")
