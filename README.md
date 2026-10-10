# DropRun updates

Public home for DropRun's automatic updates. **No app source code lives here.**

- `updates.json`: what every DropRun install reads (whenever a run is scanned, and daily) to find the latest app version and the latest road map for its area.
- **Road maps** rebuild every week from OpenStreetMap for every Australian state (`.github/workflows/build-maps.yml`). Map data © OpenStreetMap contributors, available under the [Open Database License](https://www.openstreetmap.org/copyright).
- **App releases** are published with `tools/publish_app.sh`.

Each download is checked against its SHA-256 fingerprint before an install uses it. A map never switches over in the middle of a run.
