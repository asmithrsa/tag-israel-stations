#!/usr/bin/env python3
"""Verify stations.csv against the rules JetLagHideAndSeek actually applies.

Mirrors src/maps/api/importers.ts (parseCustomStationsFromText / parseCSV) so we
can confirm how many stations the site will really load, instead of assuming.
"""
import csv
import io
import math
import sys
from pathlib import Path

CSV_PATH = Path(__file__).parent / "stations.csv"
text = CSV_PATH.read_text(encoding="utf-8")

failures, notes = [], []


def check(ok, msg):
    (notes if ok else failures).append(("PASS" if ok else "FAIL", msg))


# 1. Format sniffing. raw.githubusercontent.com serves .csv as text/plain, so the
#    hint never says "csv"; importers.ts then falls back to substring checks.
sniffed_csv = (",lat" in text) or bool(
    __import__("re").search(r"lat[,;\t ]+lon|latitude", text, __import__("re").I))
check(sniffed_csv, "detected as CSV via the text/plain fallback sniff (',lat' present)")
check(not text.lstrip().startswith("{"), "not mistaken for JSON")
check("<kml" not in text and "<Placemark" not in text, "not mistaken for KML")

# 2. Header detection, with Papa Parse's lowercase+trim transform.
rows = list(csv.DictReader(io.StringIO(text)))
headers = [h.lower().strip() for h in (rows[0].keys() if rows else [])]
lat_key = next((h for h in headers if h in ("lat", "latitude")), None)
lng_key = next((h for h in headers if h in ("lng", "lon", "long", "longitude")), None)
name_key = next((h for h in headers if h in ("name", "title", "station", "label")), None)
id_key = next((h for h in headers if h in ("id", "station_id", "osm_id")), None)
check(lat_key is not None, f"latitude column resolved -> {lat_key!r}")
check(lng_key is not None, f"longitude column resolved -> {lng_key!r}")
check(name_key is not None, f"name column resolved -> {name_key!r}")
check(id_key is not None, f"id column resolved -> {id_key!r} (enables id-based dedup)")

# 3. Replay the importer's row loop: it silently skips bad rows.
loaded = []
for r in rows:
    try:
        lat, lng = float(r[lat_key]), float(r[lng_key])
    except (TypeError, ValueError):
        continue
    if not (math.isfinite(lat) and math.isfinite(lng)):
        continue
    if not r.get(name_key):
        continue
    loaded.append({"id": r[id_key] or f"{lat},{lng}", "name": r[name_key],
                   "lat": lat, "lng": lng})
check(len(loaded) == len(rows),
      f"all {len(rows)} rows survive the importer's parse loop ({len(loaded)} loaded)")

# 4. Data sanity.
ids = [s["id"] for s in loaded]
check(len(set(ids)) == len(ids), "no duplicate ids")
check(all("/" in i for i in ids),
      "every id contains '/' so the app's id-based dedup keys on it, not coordinates")
coords = [(round(s["lat"], 5), round(s["lng"], 5)) for s in loaded]
check(len(set(coords)) == len(coords), "no duplicate coordinates")
check(all(s["name"].strip() for s in loaded), "no blank names")
oob = [s for s in loaded if not (29.4 <= s["lat"] <= 33.4 and 34.2 <= s["lng"] <= 35.9)]
check(not oob, f"all points inside Israel's bounds ({len(oob)} outside)")

# 5. No two stations of the same mode family closer than the 60 m merge threshold.
#    Cross-family pairs are expected: a train station and the light rail stop at its
#    entrance are distinct stations that legitimately sit metres apart.
def hav(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(h))

FAMILY = {"Israel Railways": "train", "Carmelit": "funicular"}
by_id = {r["id"]: r for r in rows}
pts = [(s["name"], (s["lat"], s["lng"]),
        FAMILY.get(by_id[s["id"]]["system"], "light_rail")) for s in loaded]
close, interchange = [], []
for i in range(len(pts)):
    for j in range(i + 1, len(pts)):
        d = hav(pts[i][1], pts[j][1])
        if d >= 150:
            continue
        if pts[i][2] == pts[j][2]:
            if d < 60:
                close.append((d, pts[i][0], pts[j][0]))
        else:
            interchange.append((d, pts[i][0], pts[j][0]))
check(not close, f"no unmerged same-mode duplicates within 60 m ({len(close)} found)")
for d, a, b in close[:5]:
    print(f"    {d:.0f}m  {a} <-> {b}")
if interchange:
    print(f"  [note] {len(interchange)} cross-system interchange pair(s) under 150 m, "
          "kept separate by design:")
    for d, a, b in sorted(interchange):
        print(f"    {d:5.0f}m  {a}  <->  {b}")

for status, msg in notes + failures:
    print(f"  [{status}] {msg}")
print(f"\n  {len(loaded)} stations will load into JetLagHideAndSeek")
if failures:
    print(f"  {len(failures)} CHECK(S) FAILED")
    sys.exit(1)
print("  all checks passed")
