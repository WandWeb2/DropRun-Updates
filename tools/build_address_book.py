#!/usr/bin/env python3
"""Builds a compact offline address book (DRAD) for one state from the open G-NAF release.

  build_address_book.py <g-naf.zip> <STATE e.g. QLD> <out.drad.gz> [bbox "minLat,minLng,maxLat,maxLng"]

Data: Geoscape G-NAF, Open G-NAF licence (CC BY 4.0 + no-mailing restriction). DropRun uses it only to
place a delivery pin on the map, never to send mail.

File (little endian, gzip'd): "DRAD" u32 version u64 builtEpoch 4*f64 bbox
  u32 nTypes {str code, str abbreviation}   (street type table, e.g. ROAD -> RD)
  u32 nLoc {str name, u16 postcode}
  u32 nStreet {u32 locIdx, str key, u32 firstRecord, u32 count}   key = "BERONNE RD" (name, type, suffix)
  u32 nRec {i32 numKey (number<<8 | suffix letter), i32 lat*1e6, i32 lng*1e6}   sorted by street, then numKey
str = u16 length + UTF-8
"""
import gzip, hashlib, io, json, struct, sys, time, zipfile
import numpy as np
import pandas as pd

zpath, state, out = sys.argv[1:4]
zf = zipfile.ZipFile(zpath)
names = {n.split("/")[-1]: n for n in zf.namelist()}
def read(name, **kw):
    with zf.open(names[name]) as f:
        return pd.read_csv(f, sep="|", dtype=str, keep_default_na=False, **kw)

types = read("Authority_Code_STREET_TYPE_AUT_psv.psv")
tmap = dict(zip(types.CODE, types.NAME))
loc = read(f"{state}_LOCALITY_psv.psv", usecols=["LOCALITY_PID", "LOCALITY_NAME", "DATE_RETIRED"])
loc = loc[loc.DATE_RETIRED == ""].reset_index(drop=True)
loc_idx = {p: i for i, p in enumerate(loc.LOCALITY_PID)}

st = read(f"{state}_STREET_LOCALITY_psv.psv", usecols=["STREET_LOCALITY_PID", "STREET_NAME", "STREET_TYPE_CODE", "STREET_SUFFIX_CODE", "LOCALITY_PID", "DATE_RETIRED"])
st = st[(st.DATE_RETIRED == "") & st.LOCALITY_PID.isin(loc_idx)]
def key(r):
    parts = [r.STREET_NAME.upper()]
    if r.STREET_TYPE_CODE: parts.append(tmap.get(r.STREET_TYPE_CODE, r.STREET_TYPE_CODE).upper())
    if r.STREET_SUFFIX_CODE: parts.append(r.STREET_SUFFIX_CODE.upper())
    return " ".join(parts)
st["KEY"] = [key(r) for r in st.itertuples()]
st = st.sort_values(["LOCALITY_PID", "KEY"]).reset_index(drop=True)
st_idx = {p: i for i, p in enumerate(st.STREET_LOCALITY_PID)}

det = read(f"{state}_ADDRESS_DETAIL_psv.psv", usecols=["ADDRESS_DETAIL_PID", "DATE_RETIRED", "NUMBER_FIRST", "NUMBER_FIRST_SUFFIX",
        "STREET_LOCALITY_PID", "ALIAS_PRINCIPAL", "POSTCODE"])
det = det[(det.DATE_RETIRED == "") & (det.ALIAS_PRINCIPAL == "P") & (det.NUMBER_FIRST != "") & det.STREET_LOCALITY_PID.isin(st_idx)]
geo = read(f"{state}_ADDRESS_DEFAULT_GEOCODE_psv.psv", usecols=["ADDRESS_DETAIL_PID", "DATE_RETIRED", "LONGITUDE", "LATITUDE"])
geo = geo[(geo.DATE_RETIRED == "") & (geo.LATITUDE != "")]
d = det.merge(geo[["ADDRESS_DETAIL_PID", "LONGITUDE", "LATITUDE"]], on="ADDRESS_DETAIL_PID")
d["street"] = d.STREET_LOCALITY_PID.map(st_idx)
d["num"] = pd.to_numeric(d.NUMBER_FIRST).astype(np.int64).clip(0, 8_000_000)
d["suf"] = np.array([ord(x[0].upper()) if x else 0 for x in d.NUMBER_FIRST_SUFFIX], dtype=np.int64)
d["numKey"] = (d.num.to_numpy(np.int64) << 8) | d.suf.to_numpy(np.int64)
d["lat"] = (d.LATITUDE.astype(float) * 1e6).round().astype(np.int64)
d["lng"] = (d.LONGITUDE.astype(float) * 1e6).round().astype(np.int64)
d = d.sort_values(["street", "numKey"]).drop_duplicates(["street", "numKey"]).reset_index(drop=True)

# postcode per locality (most common among its addresses)
pc = det.merge(st[["STREET_LOCALITY_PID", "LOCALITY_PID"]], on="STREET_LOCALITY_PID").groupby("LOCALITY_PID").POSTCODE.agg(lambda s: s.value_counts().index[0] if len(s) else "")

streets = d.street.values
first = np.searchsorted(streets, np.arange(len(st)), side="left")
last = np.searchsorted(streets, np.arange(len(st)), side="right")
bbox = [float(d.lat.min()) / 1e6, float(d.lng.min()) / 1e6, float(d.lat.max()) / 1e6, float(d.lng.max()) / 1e6]
if len(sys.argv) > 4: bbox = [float(x) for x in sys.argv[4].split(",")]

def s(b, text):
    e = text.encode(); b.write(struct.pack("<H", len(e))); b.write(e)
buf = io.BytesIO()
buf.write(b"DRAD"); buf.write(struct.pack("<IQ4d", 1, int(time.time()), *bbox))
buf.write(struct.pack("<I", len(tmap)))
for c, n in tmap.items(): s(buf, c); s(buf, n)
buf.write(struct.pack("<I", len(loc)))
for r in loc.itertuples():
    s(buf, r.LOCALITY_NAME.upper()); p = pc.get(r.LOCALITY_PID, ""); buf.write(struct.pack("<H", int(p) if p.isdigit() else 0))
buf.write(struct.pack("<I", len(st)))
for i, r in enumerate(st.itertuples()):
    buf.write(struct.pack("<I", loc_idx[r.LOCALITY_PID])); s(buf, r.KEY); buf.write(struct.pack("<II", int(first[i]), int(last[i] - first[i])))
buf.write(struct.pack("<I", len(d)))
rec = np.empty((len(d), 3), dtype="<i4")
rec[:, 0] = d.numKey.values; rec[:, 1] = d.lat.values; rec[:, 2] = d.lng.values
buf.write(rec.tobytes())
raw = buf.getvalue()
with gzip.GzipFile(out, "wb", compresslevel=9, mtime=0) as g: g.write(raw)
h = hashlib.sha256(open(out, "rb").read()).hexdigest()
import os
json.dump({"built": int(time.time()), "sha256": h, "bytes": os.path.getsize(out), "bbox": bbox, "addresses": len(d)}, open(out + ".json", "w"))
print(f"{state}: {len(d):,} addresses, {len(st):,} streets, {len(loc):,} localities, raw {len(raw)/1e6:.1f} MB, gz {os.path.getsize(out)/1e6:.1f} MB")
