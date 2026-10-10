#!/usr/bin/env python3
"""
Builds DropRun's offline road map (roads.drg.gz) from an OpenStreetMap extract.

    python3 build_road_graph.py queensland-latest.osm.pbf roads.drg.gz
Also writes roads.drg.gz.json: build time, size, SHA-256 and the area covered (for the update list).

Source extract: https://download.openstreetmap.fr/extracts/oceania/australia/queensland-latest.osm.pbf
Map data © OpenStreetMap contributors, ODbL. The app must show this credit wherever the map is used.

Format (little-endian):
  "DRRG" | int32 version=1 | int32 N nodes | int32 E edges | int64 built (unix secs)
  int32 lat[N] (micro-degrees) | int32 lon[N] | int32 first[N+1] | int32 target[E] | uint16 time[E] (tenths of a second)
Edges for node i are target[first[i] .. first[i+1]).
Roads are simplified: points are kept at junctions and at least every SPACING metres, so snapping
an address to the nearest point is never more than ~SPACING/2 off along a road.
"""
import gzip, math, struct, sys, time
import numpy as np
import osmium

SPACING = 250.0
SPEED = {  # km/h when no maxspeed tag; rural QLD defaults, tuned so a van's times look right
    "motorway": 90, "trunk": 80, "primary": 72, "secondary": 65, "tertiary": 58,
    "unclassified": 50, "residential": 35, "living_street": 15, "road": 40,
    "motorway_link": 60, "trunk_link": 50, "primary_link": 45, "secondary_link": 40, "tertiary_link": 35,
    "service": 20, "track": 30,
}
BAD_ACCESS = {"no", "private", "agricultural", "forestry", "delivery"}

def speed_of(tags):
    hw = tags.get("highway")
    ms = tags.get("maxspeed", "")
    v = SPEED[hw]
    try:
        n = float(ms.split()[0])
        if 5 <= n <= 130: v = n * 0.8  # average over a road is well under the limit (bends, towns, trucks)
    except Exception:
        pass
    if tags.get("surface") in ("unpaved", "gravel", "dirt", "compacted", "ground", "fine_gravel"):
        v = min(v, 60)
    return max(v, 5)

def hav(a, b, c, d):
    r = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2 - p1, math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))

class Ways(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = []      # (node ids list, coords list, speed m/s, oneway)
        self.use = {}
    def way(self, w):
        t = w.tags
        hw = t.get("highway")
        if hw not in SPEED: return
        if hw == "service" and t.get("service") in ("parking_aisle", "drive-through", "emergency_access"): return
        if hw == "track" and t.get("motor_vehicle") not in ("yes", "designated", "permissive") and t.get("access") not in ("yes", "permissive"):
            return
        if t.get("access") in BAD_ACCESS and t.get("motor_vehicle") not in ("yes", "permissive"): return
        if t.get("motor_vehicle") in BAD_ACCESS or t.get("motorcar") in BAD_ACCESS: return
        if t.get("area") == "yes": return
        try:
            nodes = [(n.ref, n.location.lat, n.location.lon) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(nodes) < 2: return
        ow = t.get("oneway", "")
        oneway = 1 if ow in ("yes", "true", "1") or t.get("junction") in ("roundabout", "circular") or (hw == "motorway" and ow != "no") else (-1 if ow == "-1" else 0)
        self.ways.append(([n[0] for n in nodes], [(n[1], n[2]) for n in nodes], speed_of(t) / 3.6, oneway))
        for n in nodes:
            self.use[n[0]] = self.use.get(n[0], 0) + 1

def main(src, dst):
    t0 = time.time()
    h = Ways()
    h.apply_file(src, locations=True, idx="flex_mem")
    print(f"{len(h.ways)} ways read in {time.time()-t0:.0f}s", flush=True)

    index = {}
    lat, lon = [], []
    def idx(nid, la, lo):
        i = index.get(nid)
        if i is None:
            i = len(lat); index[nid] = i; lat.append(la); lon.append(lo)
        return i

    eu, ev, et = [], [], []
    for ids, coords, mps, oneway in h.ways:
        last = 0
        acc = 0.0
        for k in range(1, len(ids)):
            acc += hav(coords[k-1][0], coords[k-1][1], coords[k][0], coords[k][1])
            end = k == len(ids) - 1
            if end or h.use[ids[k]] > 1 or acc >= SPACING:
                a = idx(ids[last], *coords[last]); b = idx(ids[k], *coords[k])
                secs = acc / mps
                if oneway >= 0: eu.append(a); ev.append(b); et.append(secs)
                if oneway <= 0: eu.append(b); ev.append(a); et.append(secs)
                last = k; acc = 0.0
        # (ways that loop back on themselves are fine: the edge list just has a cycle)
    del h
    n = len(lat)
    eu = np.array(eu, dtype=np.int64); ev = np.array(ev, dtype=np.int64); et = np.array(et)
    print(f"{n} points, {len(eu)} road segments", flush=True)

    # Keep only the main connected network so every address snaps to a reachable road.
    parent = np.arange(n)
    def find(x):
        root = x
        while parent[root] != root: root = parent[root]
        while parent[x] != root:
            nx = parent[x]; parent[x] = root; x = nx
        return root
    for a, b in zip(eu.tolist(), ev.tolist()):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    roots = np.array([find(i) for i in range(n)])
    main_root = np.bincount(roots).argmax()
    keep = roots == main_root
    newid = -np.ones(n, dtype=np.int64); newid[keep] = np.arange(keep.sum())
    m = keep[eu] & keep[ev]
    eu, ev, et = newid[eu[m]], newid[ev[m]], et[m]
    lat = np.array(lat)[keep]; lon = np.array(lon)[keep]
    n = len(lat)

    order = np.argsort(eu, kind="stable")
    eu, ev, et = eu[order], ev[order], et[order]
    first = np.zeros(n + 1, dtype=np.int32)
    np.add.at(first, eu + 1, 1)
    first = np.cumsum(first).astype(np.int32)
    tenths = np.clip(np.round(et * 10), 1, 65535).astype("<u2")

    with gzip.open(dst, "wb", compresslevel=9) as f:
        f.write(b"DRRG" + struct.pack("<iiiq", 1, n, len(ev), int(time.time())))
        f.write(np.round(lat * 1e6).astype("<i4").tobytes())
        f.write(np.round(lon * 1e6).astype("<i4").tobytes())
        f.write(first.astype("<i4").tobytes())
        f.write(ev.astype("<i4").tobytes())
        f.write(tenths.tobytes())
    import hashlib, json
    sha = hashlib.sha256(open(dst, "rb").read()).hexdigest()
    built = int(time.time())
    meta = {"built": built, "nodes": int(n), "edges": int(len(ev)), "sha256": sha,
            "bytes": __import__("os").path.getsize(dst),
            "bbox": [round(float(lat.min()), 4), round(float(lon.min()), 4), round(float(lat.max()), 4), round(float(lon.max()), 4)]}
    json.dump(meta, open(dst + ".json", "w"))
    print(f"wrote {dst}: {n} points, {len(ev)} segments, {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
