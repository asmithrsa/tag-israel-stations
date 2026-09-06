#!/usr/bin/env python3
"""Build a custom station list for JetLagHideAndSeek covering open Israeli
train, light rail and Carmelit stations.

Data source: OpenStreetMap via the Overpass API. Re-run to refresh.

Usage:  python3 generate.py [--refresh]
"""
from __future__ import annotations

import csv
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

# --- Overpass ---------------------------------------------------------------
# Clip to the Israel + Palestinian territory boundary relations rather than a
# bounding box: a bbox over this region drags in Hejaz-railway ruins across the
# Jordanian border, which are indistinguishable from open stations by tags alone.
AREA = """(
  area["ISO3166-1"="IL"][admin_level=2];
  area["ISO3166-1"="PS"][admin_level=2];
)->.searchArea;"""

QUERY_STATIONS = f"""[out:json][timeout:600];
{AREA}
nwr["railway"~"^(station|halt|tram_stop)$"](area.searchArea);
out center tags;
rel["type"="route"]["route"~"^(train|light_rail|tram|funicular|subway|monorail)$"](area.searchArea);
out body;
"""

QUERY_ROUTE_NODES = f"""[out:json][timeout:600];
{AREA}
rel["type"="route"]["route"~"^(train|light_rail|tram|funicular|subway|monorail)$"](area.searchArea)->.r;
node(r.r);
out body;
"""

# --- Tuning -----------------------------------------------------------------
# Merge radius, applied only *within* a mode family (see family()). Measured over
# every pair under 300 m: platform twins of one station are never more than 23 m
# apart, while the closest genuinely distinct same-mode stations are Central Station
# and Binyene Ha'Uma ICC at 115 m. 60 m sits safely between the two.
#
# Distance alone is not enough, because the closest pairs in the whole dataset are
# different systems sharing an interchange - Central Station (light rail) is 42 m
# from Jerusalem - Yitzhak Navon (heavy rail), and Kiryat Aryeh's light rail stop is
# 23 m from the Petah Tikva-Kiryat Aryeh train station. Those are distinct stations
# and must survive as separate rows, so merging never crosses a family boundary.
MERGE_M = 60
# Distance from a station to a route relation's stop node for it to count as served.
SERVED_M = 150
# Interchanges split across lines are mapped as "X" and "X - <line>" a few hundred
# metres apart. Merge those by name, but only within this radius.
NAME_MERGE_M = 600
# A train station and the light rail stops serving it are one hiding zone, so they
# merge despite being different mode families. A large station can be served by more
# than one stop - Yitzhak Navon has Central Station 44 m one way and Binyene Ha'Uma
# ICC 81 m the other - so the rail station acts as a hub and absorbs every light rail
# stop within this radius.
CROSS_MERGE_M = 150

# Lines that exist in OSM but are not (fully) open to passengers.
YELLOW = ("Jerusalem Light Rail Yellow Line - only the HaTurim to Manahat (Malha) "
          "segment is open")
CLOSED_ROUTES = [
    ("L3", YELLOW),
    ("הצהוב", YELLOW),
    ("נופית", "Haifa–Nazareth 'Nofit' light rail (under construction)"),
    ("מטרונית", "Metronit BRT (excluded by request)"),
]

# The Yellow Line opened in stages: as of August 2026 the HaTurim - Malha segment
# carries passengers, while the northern continuation towards Ramot is still being
# built. OSM happens to map only the open segment today, but pinning the open stops
# by id means that stops added later for the unopened section stay excluded instead
# of being swept in silently. HaTurim and Binyene Ha'Uma ICC are not listed here:
# they are Red Line stops already, and merge into a single row.
PARTIAL_OPEN = {
    "node/14110866504": "Government Complex",
    "node/14110785641": "Giv'at Ram",
    "node/14110785639": "Safra University Campus",
    "node/14110785637": "Hebrew Park",
    "node/14110228510": "Betsal'el Bazak",
    "node/14110805877": "Giv'at Mordekhay",
    "node/14110823308": "Pat Jct",
    "node/14110759300": "Gonenim",
    "node/14110791430": "Malha Sports Complex",
    "node/14110791431": "Ha'Ayal",
    "node/14106312634": "Manahat (Malha)",
}

LIFECYCLE = ("construction:", "proposed:", "disused:", "abandoned:", "razed:",
             "demolished:", "removed:", "planned:")

IR_OPERATORS = {"israel railways", "רכבת ישראל"}

# Names that mark a ruin rather than a working station. "שרידים" = "remains of".
RUIN_WORDS = ("שרידים", "ruins", "remains of", "former station", "old nablus")

# Israeli train routes in OSM reference *ways*, not stop nodes, so the
# route-proximity test used for light rail is meaningless for them (nearest route
# member sits 2-28 km away). Rail stations are confirmed by catalogue presence
# instead: 67 of 74 carry a wikidata ref and/or an Israel Railways operator tag.
# OSM node ids above this were created roughly 2025 onwards - a new-build station
# added to OSM before opening is the main way a closed station slips through.
RECENT_NODE_ID = 13_000_000_000

# Stations the heuristics above cannot confirm but that have been checked by hand.
# Without this, every regeneration would flag them again.
CONFIRMED_OPEN = {
    "node/13626956323": "Shomron - Tayyiba: confirmed open, September 2026",
    "node/13964778722": "Tira - Kokhav Ya'ir: confirmed open, September 2026",
}


def haversine(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def overpass(query: str, out: Path):
    print(f"  querying Overpass -> {out.name} ...", flush=True)
    res = subprocess.run(
        ["curl", "-s", "--data-urlencode", f"data@-",
         "https://overpass-api.de/api/interpreter"],
        input=query, capture_output=True, text=True, check=True,
    )
    json.loads(res.stdout)  # fail loudly on an HTML error page
    out.write_text(res.stdout)


def fetch(refresh: bool):
    raw, nodes = HERE / "raw.json", HERE / "routenodes.json"
    if refresh or not raw.exists():
        overpass(QUERY_STATIONS, raw)
    if refresh or not nodes.exists():
        overpass(QUERY_ROUTE_NODES, nodes)
    return json.loads(raw.read_text()), json.loads(nodes.read_text())


def coords(e):
    if e["type"] == "node":
        return (e["lat"], e["lon"])
    c = e.get("center")
    return (c["lat"], c["lon"]) if c else None


def label(tags):
    """English name preferred, Hebrew as fallback."""
    for k in ("name:en", "int_name", "name", "name:he"):
        v = (tags.get(k) or "").strip()
        if v:
            return v
    return ""


def route_status(tags):
    """Return (open: bool, reason: str) for a route relation."""
    blob = " ".join(str(tags.get(k, "")) for k in ("ref", "name", "network", "operator"))
    for needle, reason in CLOSED_ROUTES:
        if needle in blob:
            return False, reason
    return True, ""


def is_train(tags):
    return (tags.get("train") == "yes"
            or tags.get("station") == "train"
            or (tags.get("operator") or "").strip().lower() in IR_OPERATORS)


def family(tags):
    """Mode family. Merging only happens within one of these, so a train station is
    never absorbed into the light rail stop outside its entrance."""
    if tags.get("funicular") == "yes" or tags.get("station") == "funicular":
        return "funicular"
    if is_train(tags):
        return "train"
    return "light_rail"


def confirm(elem, tags, srv_open, srv_closed, member_ids=()):
    """Classify a merged station as include / exclude / flag-for-review."""
    if any(i in CONFIRMED_OPEN or i in PARTIAL_OPEN for i in member_ids):
        return "include", ""
    if is_train(tags):
        reasons = []
        catalogued = (tags.get("wikidata")
                      or (tags.get("operator") or "").strip().lower() in IR_OPERATORS)
        if not catalogued:
            reasons.append("no wikidata ref and no operator tag, so it is not a "
                           "catalogued Israel Railways station")
        if elem["type"] == "node" and elem["id"] > RECENT_NODE_ID:
            reasons.append("added to OSM recently (2025+), which usually means a "
                           "new build - confirm it has actually opened")
        return ("flag", "; ".join(reasons)) if reasons else ("include", "")
    if srv_open:
        return "include", ""
    if srv_closed:
        return "exclude", ("only served by a line that is not open: "
                           + "; ".join(sorted({r["reason"] for r in srv_closed})))
    return "flag", (f"no open light rail or funicular route passes within "
                    f"{SERVED_M} m, so service could not be confirmed")


def system_of(tags, open_routes):
    """Human-readable system name for the CSV's `system` column."""
    if tags.get("station") == "funicular" or tags.get("funicular") == "yes":
        return "Carmelit"
    op = (tags.get("operator") or "").strip().lower()
    if op in IR_OPERATORS or tags.get("train") == "yes":
        return "Israel Railways"
    for r in open_routes:
        n = r.get("name", "")
        if "ירושלים" in n:
            return "Jerusalem Light Rail"
        if "תל אביב" in n or r.get("network") == "Tel Aviv LRT":
            return "Tel Aviv Light Rail"
    if tags.get("station") in ("light_rail", "subway") or tags.get("light_rail") == "yes":
        return "Light Rail"
    return "Rail"


def main():
    refresh = "--refresh" in sys.argv
    print("Building Israeli station list from OpenStreetMap")
    data, routenodes = fetch(refresh)

    elements = data["elements"]
    stations = [e for e in elements if e["type"] != "relation"]
    relations = [e for e in elements if e["type"] == "relation"]
    node_pos = {n["id"]: (n["lat"], n["lon"]) for n in routenodes["elements"]}

    # Route relations, split into open and not-yet-open, with member stop coords.
    open_routes, closed_routes = [], []
    for r in relations:
        pts = [node_pos[m["ref"]] for m in r.get("members", [])
               if m["type"] == "node" and m["ref"] in node_pos]
        rec = {"tags": r["tags"], "pts": pts, "name": r["tags"].get("name", ""),
               "network": r["tags"].get("network", "")}
        ok, reason = route_status(r["tags"])
        rec["reason"] = reason
        (open_routes if ok else closed_routes).append(rec)
    print(f"  route relations: {len(open_routes)} open, {len(closed_routes)} not open")

    # --- Filter to plausible open passenger stations ------------------------
    dropped = []
    kept = []
    for e in stations:
        t = e.get("tags", {})
        pos = coords(e)
        if pos is None:
            dropped.append((e, t, "no coordinates"))
            continue
        if any(k.startswith(LIFECYCLE) for k in t):
            dropped.append((e, t, "lifecycle tag (construction/proposed/disused)"))
            continue
        if t.get("historic") or t.get("ruins") == "yes" or t.get("abandoned") == "yes":
            dropped.append((e, t, "historic / ruins"))
            continue
        blob = " ".join(str(v) for v in t.values()).lower()
        if any(w in blob for w in RUIN_WORDS):
            dropped.append((e, t, "name identifies it as a ruin, not a working station"))
            continue
        if not label(t):
            dropped.append((e, t, "no name"))
            continue
        is_rail = (
            t.get("train") == "yes" or t.get("light_rail") == "yes"
            or t.get("tram") == "yes" or t.get("subway") == "yes"
            or t.get("funicular") == "yes"
            or t.get("station") in ("train", "light_rail", "subway", "funicular")
            or (t.get("operator") or "").strip().lower() in IR_OPERATORS
            or t.get("railway") == "tram_stop"
        )
        if not is_rail:
            dropped.append((e, t, "no passenger-rail mode tag"))
            continue
        kept.append((e, t, pos))
    print(f"  stations: {len(kept)} kept, {len(dropped)} dropped pre-merge")

    # --- Which lines serve each element -------------------------------------
    for i, (e, t, pos) in enumerate(kept):
        srv_open = [r for r in open_routes
                    if any(haversine(pos, p) <= SERVED_M for p in r["pts"])]
        srv_closed = [r for r in closed_routes
                      if any(haversine(pos, p) <= SERVED_M for p in r["pts"])]
        kept[i] = (e, t, pos, srv_open, srv_closed)

    # --- Merge duplicates (union-find) --------------------------------------
    parent = list(range(len(kept)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def norm(s):
        """Strip decorative words wherever they appear, so that an interchange
        mapped as both "X Station" and "X Station - <line>" reduces to a common
        prefix. Trailing-only stripping misses the second form."""
        s = s.lower().replace("–", "-").replace("'", "")
        for word in ("railway station", "light rail station", "train station",
                     "station", "railway"):
            s = s.replace(word, " ")
        return " ".join(s.split())

    for i in range(len(kept)):
        for j in range(i + 1, len(kept)):
            if family(kept[i][1]) != family(kept[j][1]):
                continue
            d = haversine(kept[i][2], kept[j][2])
            if d <= MERGE_M:
                union(i, j)
                continue
            if d <= NAME_MERGE_M:
                ni, nj = norm(label(kept[i][1])), norm(label(kept[j][1]))
                # "HaMifrats Central" vs "HaMifrats Central - HaEmek Line"
                if ni and nj and (ni == nj or ni.startswith(nj + " -") or nj.startswith(ni + " -")):
                    union(i, j)

    # Cross-family interchanges, matched hub-and-spoke rather than by raw proximity.
    # A rail station may absorb several light rail stops, since a big interchange is
    # served from more than one side, but each light rail stop can be claimed only
    # once - otherwise two rail stations near one stop would chain into a single
    # cluster through it.
    groups = {}
    for i in range(len(kept)):
        groups.setdefault(find(i), []).append(i)

    def centroid(idxs):
        return (sum(kept[i][2][0] for i in idxs) / len(idxs),
                sum(kept[i][2][1] for i in idxs) / len(idxs))

    reps = {r: (centroid(idx), family(kept[idx[0]][1])) for r, idx in groups.items()}
    candidates = []
    for a, b in itertools.combinations(reps, 2):
        (pa, fa), (pb, fb) = reps[a], reps[b]
        if fa == fb:
            continue
        d = haversine(pa, pb)
        if d <= CROSS_MERGE_M:
            candidates.append((d, a, b))
    claimed = set()
    for d, a, b in sorted(candidates):
        fa, fb = reps[a][1], reps[b][1]
        if fa == "train" or fb == "train":
            hub, spoke = (a, b) if fa == "train" else (b, a)
            if spoke in claimed:
                continue
            claimed.add(spoke)
        else:
            if a in claimed or b in claimed:
                continue
            claimed.update((a, b))
            hub, spoke = a, b
        nh, ns = label(kept[groups[hub][0]][1]), label(kept[groups[spoke][0]][1])
        print(f"    interchange: {nh} absorbs {ns} ({d:.0f} m)")
        union(hub, spoke)

    clusters = {}
    for i in range(len(kept)):
        clusters.setdefault(find(i), []).append(i)
    print(f"  merged {len(kept)} elements into {len(clusters)} stations")

    # --- Build rows ---------------------------------------------------------
    RANK = {"station": 0, "tram_stop": 1, "halt": 2}
    rows, review = [], []
    for members in clusters.values():
        best = min(members, key=lambda i: (
            0 if family(kept[i][1]) == "train" else 1,
            RANK.get(kept[i][1].get("railway"), 3),
            0 if kept[i][1].get("name:en") else 1,
            -len(kept[i][1]),
        ))
        e, t, _, _, _ = kept[best]
        pts = [kept[i][2] for i in members]
        lat = sum(p[0] for p in pts) / len(pts)
        lng = sum(p[1] for p in pts) / len(pts)

        srv_open, srv_closed = [], []
        for i in members:
            srv_open += kept[i][3]
            srv_closed += kept[i][4]
        name = label(t)
        osm_id = f"{e['type']}/{e['id']}"

        member_ids = [f"{kept[i][0]['type']}/{kept[i][0]['id']}" for i in members]
        verdict, why = confirm(e, t, srv_open, srv_closed, member_ids)
        if verdict == "exclude":
            review.append({"name": name, "id": osm_id, "lat": lat, "lng": lng,
                           "issue": why, "action": "excluded"})
            continue
        if verdict == "flag":
            review.append({"name": name, "id": osm_id, "lat": lat, "lng": lng,
                           "issue": why, "action": "INCLUDED - please verify"})
        rows.append({
            "name": name,
            "lat": f"{lat:.6f}",
            "lng": f"{lng:.6f}",
            "id": osm_id,
            "system": system_of(t, srv_open + srv_closed),
        })

    # Hand-maintained additions (bus stops, corrections). Kept in a separate file
    # so that re-running this script never destroys them.
    extra_path = HERE / "extra-stations.csv"
    if extra_path.exists():
        seen = {r["id"] for r in rows}
        added = 0
        with extra_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r = {k.lower().strip(): (v or "").strip() for k, v in r.items()}
                if not r.get("name") or not r.get("lat") or not r.get("lng"):
                    continue
                rid = r.get("id") or f"extra/{r['lat']},{r['lng']}"
                if rid in seen:
                    continue
                seen.add(rid)
                rows.append({"name": r["name"], "lat": r["lat"], "lng": r["lng"],
                             "id": rid, "system": r.get("system") or "Custom"})
                added += 1
        print(f"  merged {added} hand-added stations from {extra_path.name}")

    rows.sort(key=lambda r: (r["system"], r["name"]))

    out = HERE / "stations.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "lat", "lng", "id", "system"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n  wrote {out.name}: {len(rows)} stations")

    from collections import Counter
    for sysname, n in sorted(Counter(r["system"] for r in rows).items()):
        print(f"    {n:4d}  {sysname}")

    # --- Review file --------------------------------------------------------
    lines = ["# Stations needing manual verification", "",
             "Generated by `generate.py`. Everything here was ambiguous in "
             "OpenStreetMap, so it is listed rather than silently dropped.", ""]
    incl = [r for r in review if r["action"].startswith("INCLUDED")]
    excl = [r for r in review if r["action"] == "excluded"]
    lines += [f"## Included but unconfirmed ({len(incl)})", "",
              "These are in `stations.csv`. Delete any that are not actually open.", ""]
    lines += ["| Station | OSM | Coords | Why flagged |", "|---|---|---|---|"]
    for r in sorted(incl, key=lambda x: x["name"]):
        lines.append(f"| {r['name']} | `{r['id']}` | {r['lat']:.5f}, {r['lng']:.5f} | {r['issue']} |")
    lines += ["", f"## Excluded as not-yet-open ({len(excl)})", "",
              "These are **not** in `stations.csv`. Add them back if any have opened.", ""]
    lines += ["| Station | OSM | Coords | Why excluded |", "|---|---|---|---|"]
    for r in sorted(excl, key=lambda x: x["name"]):
        lines.append(f"| {r['name']} | `{r['id']}` | {r['lat']:.5f}, {r['lng']:.5f} | {r['issue']} |")

    by_reason = {}
    for e, t, reason in dropped:
        by_reason.setdefault(reason, []).append(label(t) or f"(unnamed {e['type']}/{e['id']})")
    lines += ["", f"## Filtered out before merging ({len(dropped)})", ""]
    for reason, names in sorted(by_reason.items()):
        lines.append(f"- **{reason}** ({len(names)}): " + ", ".join(sorted(names)))
    lines.append("")
    (HERE / "REVIEW.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote REVIEW.md: {len(incl)} to verify, {len(excl)} excluded as unopened")


if __name__ == "__main__":
    main()
