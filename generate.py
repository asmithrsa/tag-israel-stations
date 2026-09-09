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
import re
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

QUERY_BUS = f"""[out:json][timeout:300];
{AREA}
nwr["amenity"="bus_station"](area.searchArea);
out center tags;
"""

QUERY_BUS_NAMED = f"""[out:json][timeout:300];
{AREA}
(
  nwr["name"~"תחנה מרכזית|התחנה המרכזית|מרכזית"](area.searchArea);
  nwr["name:he"~"תחנה מרכזית|התחנה המרכזית|מרכזית"](area.searchArea);
);
out center tags;
"""

QUERY_CABLE = """[out:json][timeout:180];
nwr["aerialway"="station"](32.75,34.95,32.82,35.06);
out center tags;
"""

QUERY_METRONIT = """[out:json][timeout:180];
(
  node["highway"="bus_stop"]["name"](32.74,34.92,32.92,35.14);
  node["public_transport"="platform"]["name"](32.74,34.92,32.92,35.14);
);
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
# A central bus station sharing a site with a rail station is the same hiding zone,
# so it is dropped rather than merged. Distances to the nearest rail station fall
# into two groups with a clean gap: collisions run up to 391 m (Lod's temporary
# terminal), and the next nearest is Tel Aviv New Central Bus Station at 523 m.
BUS_RAIL_M = 400

# Israel's intercity bus terminals are "תחנה מרכזית" (merkazit). Matched on name
# fields only: matching the whole tag set pulls in the individual platforms inside a
# station, whose gtfs:stop_name repeats the station name.
# Requires a station word, so that HaSdera HaMerkazit - "the central boulevard" -
# and similar street names do not match.
CENTRAL_BUS = re.compile(
    r"\bcentral\s+(bus\s+)?(station|sttn|sta\.)\b|\bCBS\b|\bmerkazit\b|"
    r"תחנה\s+מרכזית|התחנה\s+המרכזית|ת\.\s*מרכזית", re.I)
# A bare "Central Station" gives no clue which town it serves - 18 platforms across
# the country share that name - so a platform-derived name must carry a qualifier.
GENERIC_BUS = re.compile(
    r"^(the\s+)?(new\s+|old\s+)?central\s+(bus\s+)?(station|sttn)$|"
    r"^(ה)?תחנה\s+(ה)?מרכזית$", re.I)
BUS_NAME_FIELDS = ("name", "name:en", "name:he", "official_name", "alt_name",
                   "int_name")
# Platforms of one bus station spread out, and the same station is often mapped
# under spelling variants (Acko/Akko, Kfar Saba/Sava, Tzfat/Safed). Merging bus
# candidates within this radius folds those together.
BUS_MERGE_M = 500
NON_TRANSPORT = {"library", "post_office", "parking", "shelter", "bicycle_rental"}

# The Rakavlit (רכבלית), Haifa's transit gondola, opened 2022. Pinned by id because
# OSM offers no reliable handle on it: two of the six stations carry neither the
# operator nor the network tag, and there is no route relation. Four have no English
# name, so those are supplied here. generate.py warns if an id stops resolving.
# Haifa's other cable car, the Stella Maris tourist tramway, is deliberately absent.
RAKAVLIT = {
    "node/2645430236": "Merkazit HaMifrats",
    "node/7598996149": "Check Post",
    "node/2645430233": "Dori",
    "node/7598996148": "Technion (Lower)",
    "node/7598996146": "Technion Upper",
    "node/2645430237": "University of Haifa",
}
# Modes that ride on top of the rail network rather than extending it. One of these
# sitting on a rail station's site is the same hiding zone, so it is dropped.
SUPPRESS_NEAR_RAIL = {"bus", "aerialway", "metronit"}

# Metronit BRT transfer stations, pinned by OSM node id. Nothing in the data selects
# them: only 5 of 94 confirmed stops carry network=Metronit, the lines share the
# numbers 1-5 with ordinary Haifa buses, and the route relations are incomplete
# (line 3 has no stop members at all, line 4 has one). 11 of these 13 were verified
# as members of the Metronit route relations; Hallisa and Tsahal are matched on an
# exact, unqualified name on a Metronit line.
#
# Grouped by the name below rather than by distance: the two direction platforms of
# one station run up to 135 m apart here (Police Headquarters), well beyond MERGE_M.
METRONIT = {
    "node/1803062171": "Lin",                "node/1803062172": "Lin",
    "node/1803016988": "Hallisa",            "node/1803016991": "Hallisa",
    # OSM calls this צומת קרית אתא/מחלף מוטה גור; the Metronit calls it Mota Gur,
    # after the interchange. Not to be confused with the Kiryat Ata stop below.
    "node/5210715246": "Mota Gur",           "node/5210715247": "Mota Gur",
    "node/5210715274": "Ha'Atsma'ut",
    "node/5210715226": "Einstein",
    "node/5210715230": "Kiryat Ata",
    "node/5210715250": "Kiryat Haim",        "node/5210715251": "Kiryat Haim",
    "node/5210715272": "Goshen",             "node/5210715273": "Goshen",
    "node/5210715268": "Ha'Asor",            "node/5210715269": "Ha'Asor",
    "node/5210715263": "Tsur Shalom",        "node/5210715264": "Tsur Shalom",
    "node/5210715256": "Tsahal",             "node/5210715257": "Tsahal",
    "node/1803086107": "HaToren",            "node/5210715236": "HaToren",
    "node/5210715275": "Zevulun",            "node/5210715276": "Zevulun",
    "node/5210715223": "Savyone Yam",        "node/5210715224": "Savyone Yam",
    "node/5210715219": "HaPalmach",          "node/5210715220": "HaPalmach",
    "node/1803004883": "Grand Canyon",       "node/1803004884": "Grand Canyon",
    "node/1803080475": "Congress Center",
    "node/1803050903": "Neve David",         "node/1803086106": "Neve David",
    "node/1803070849": "Ha'Etsel",           "node/5210715234": "Ha'Etsel",
    "node/5210715235": "Shprinzak",          "node/10899338439": "Shprinzak",
    "node/1803021630": "Talpiyot Market",    "node/1803088998": "Talpiyot Market",
    "node/5210715205": "Talpiyot Market",
    "node/5210715187": "Halutzei HaTa'asiya",
    "node/5210715210": "Halutzei HaTa'asiya",
}

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

# Stations OSM still tags as open but which no longer see service. Nothing in the
# data marks them - both carry wikidata refs and no lifecycle tag - so a service
# change can only be recorded here.
CLOSED_STATIONS = {
    # Only three of the Rakavlit's six stations are in service: HaMifratz, Technion
    # (Lower) and University of Haifa. OSM maps all six identically, with nothing to
    # separate the built-but-unopened ones.
    "node/7598996149": "Check Post: Rakavlit station not in service as of "
                       "September 2026",
    "node/2645430233": "Dori: Rakavlit station not in service as of September 2026",
    "node/7598996146": "Technion Upper: Rakavlit station not in service as of "
                       "September 2026",
    "node/2930682108": "Biblical Zoo: Beit Shemesh-Jerusalem service ended; closed "
                       "for years as of September 2026",
    "node/2930682106": "Jerusalem Malcha: Beit Shemesh-Jerusalem service ended; "
                       "closed for years as of September 2026",
}

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
    raw, nodes, bus = HERE / "raw.json", HERE / "routenodes.json", HERE / "bus.json"
    if refresh or not raw.exists():
        overpass(QUERY_STATIONS, raw)
    if refresh or not nodes.exists():
        overpass(QUERY_ROUTE_NODES, nodes)
    if refresh or not bus.exists():
        overpass(QUERY_BUS, bus)
    named = HERE / "busname.json"
    if refresh or not named.exists():
        overpass(QUERY_BUS_NAMED, named)
    cable = HERE / "cable.json"
    if refresh or not cable.exists():
        overpass(QUERY_CABLE, cable)
    mstops = HERE / "mstops.json"
    if refresh or not mstops.exists():
        overpass(QUERY_METRONIT, mstops)
    return (json.loads(raw.read_text()), json.loads(nodes.read_text()),
            json.loads(bus.read_text()), json.loads(named.read_text()),
            json.loads(cable.read_text()), json.loads(mstops.read_text()))


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


def bus_name(tags):
    """The station's own name, dropping the '/platform detail' suffix OSM appends."""
    raw = tags.get("name:en") or tags.get("name") or ""
    base = raw.split("/")[0].strip()
    base = re.sub(r"\s*\d+(st|nd|rd|th)\s+Floor$", "", base, flags=re.I)
    # OSM appends the role of a particular platform to the station name.
    base = re.sub(r"\s+(Platforms?|Alight|Boarding|Drop-off|Terminals?)$", "",
                  base, flags=re.I)
    return base.strip()


def central_bus_stations(busdata, busnamed):
    """Central bus stations, consolidated from two OSM sources.

    amenity=bus_station is authoritative but incomplete: Kiryat Shmona, Ness Ziona,
    Rosh Pina and Beit She'an have a central bus station mapped only as named
    platforms. Those fill the gaps, but only when the name carries a place
    qualifier. Where both sources describe one station they are folded together,
    and a qualified platform name beats a vague station name - which is how the
    bus station named only "Central bus station" is identified as Kiryat Shmona's.
    """
    def usable(e, t):
        if t.get("amenity") in NON_TRANSPORT or t.get("landuse") == "construction":
            return False
        if any(k.startswith(LIFECYCLE) for k in t):
            return False
        return True

    primary, secondary = [], []
    for e in busdata["elements"]:
        t, pos = e.get("tags", {}), coords(e)
        if pos is None or t.get("amenity") != "bus_station" or not usable(e, t):
            continue
        if t.get("public_transport") == "platform" or t.get("highway") == "bus_stop":
            continue
        if CENTRAL_BUS.search(" ".join(t.get(k, "") for k in BUS_NAME_FIELDS)):
            primary.append((e, t, pos, bus_name(t) or label(t)))

    known = {(e["type"], e["id"]) for e, _, _, _ in primary}
    for e in busnamed["elements"]:
        t, pos = e.get("tags", {}), coords(e)
        if pos is None or (e["type"], e["id"]) in known or not usable(e, t):
            continue
        name = bus_name(t)
        transport = (t.get("amenity") == "bus_station"
                     or t.get("public_transport") in ("station", "platform",
                                                      "stop_position", "stop_area")
                     or t.get("highway") == "bus_stop"
                     # Beit She'an's terminal is mapped only as its building.
                     or (t.get("building")
                         and re.search(r"bus station|תחנה מרכזית", name, re.I)))
        if not transport:
            continue
        if not name or not CENTRAL_BUS.search(name) or GENERIC_BUS.match(name):
            continue
        secondary.append((e, t, pos, name))

    # Group primaries, then attach each secondary to the nearest group or start one.
    groups = []
    for item in primary:
        for g in groups:
            if haversine(item[2], g[0][2]) <= BUS_MERGE_M:
                g.append(item)
                break
        else:
            groups.append([item])
    n_primary_groups = len(groups)
    for item in secondary:
        for g in groups:
            if haversine(item[2], g[0][2]) <= BUS_MERGE_M:
                g.append(item)
                break
        else:
            groups.append([item])

    out = []
    for g in groups:
        pts = [it[2] for it in g]
        lat = sum(p[0] for p in pts) / len(pts)
        lng = sum(p[1] for p in pts) / len(pts)
        # Prefer a qualified name, then the most specific (longest) one.
        name = min((it[3] for it in g),
                   key=lambda n: (GENERIC_BUS.match(n) is not None, -len(n)))
        src = next((it for it in g if it[0]["type"] != "relation"), g[0])
        out.append((src[0], {"amenity": "bus_station", "name:en": name}, (lat, lng)))
    print(f"  central bus stations: {len(out)} "
          f"({n_primary_groups} from amenity=bus_station, "
          f"{len(out) - n_primary_groups} more found by name only)")
    return out


def rakavlit_stations(cabledata):
    """Haifa's Rakavlit gondola, matched against the pinned ids above."""
    out = []
    for e in cabledata["elements"]:
        oid = f"{e['type']}/{e['id']}"
        if oid not in RAKAVLIT or coords(e) is None:
            continue
        out.append((e, {"aerialway": "station", "name:en": RAKAVLIT[oid]}, coords(e)))
    missing = set(RAKAVLIT) - {f"{e['type']}/{e['id']}" for e, _, _ in out}
    if missing:
        print(f"    WARNING: Rakavlit ids no longer in OSM: {sorted(missing)}")
    print(f"  Haifa Rakavlit: {len(out)} of {len(RAKAVLIT)} stations found")
    return out


def metronit_stations(mstops):
    """Metronit transfer stations, grouped by the pinned name (see METRONIT)."""
    groups = {}
    for e in mstops["elements"]:
        oid = f"{e['type']}/{e['id']}"
        if oid not in METRONIT or coords(e) is None:
            continue
        groups.setdefault(METRONIT[oid], []).append((e, coords(e)))
    out = []
    for name, items in groups.items():
        pts = [p for _, p in items]
        lat = sum(p[0] for p in pts) / len(pts)
        lng = sum(p[1] for p in pts) / len(pts)
        out.append((items[0][0], {"metronit": "yes", "name:en": name}, (lat, lng)))
    missing = set(METRONIT) - {f"{e['type']}/{e['id']}"
                               for e in mstops["elements"]
                               if f"{e['type']}/{e['id']}" in METRONIT}
    if missing:
        print(f"    WARNING: Metronit ids no longer in OSM: {sorted(missing)}")
    print(f"  Metronit transfer stations: {len(out)} "
          f"from {len(METRONIT)} pinned platforms")
    return out


def is_train(tags):
    return (tags.get("train") == "yes"
            or tags.get("station") == "train"
            or (tags.get("operator") or "").strip().lower() in IR_OPERATORS)


def family(tags):
    """Mode family. Merging only happens within one of these, so a train station is
    never absorbed into the light rail stop outside its entrance."""
    if tags.get("amenity") == "bus_station":
        return "bus"
    if tags.get("aerialway") == "station":
        return "aerialway"
    if tags.get("metronit") == "yes":
        return "metronit"
    if tags.get("funicular") == "yes" or tags.get("station") == "funicular":
        return "funicular"
    if is_train(tags):
        return "train"
    return "light_rail"


def confirm(elem, tags, srv_open, srv_closed, member_ids=()):
    """Classify a merged station as include / exclude / flag-for-review."""
    shut = [CLOSED_STATIONS[i] for i in member_ids if i in CLOSED_STATIONS]
    if shut:
        return "exclude", shut[0]
    if any(i in CONFIRMED_OPEN or i in PARTIAL_OPEN for i in member_ids):
        return "include", ""
    if family(tags) in SUPPRESS_NEAR_RAIL:
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
    if tags.get("amenity") == "bus_station":
        return "Central Bus Station"
    if tags.get("aerialway") == "station":
        return "Haifa Rakavlit"
    if tags.get("metronit") == "yes":
        return "Metronit"
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
    data, routenodes, busdata, busnamed, cabledata, mstops = fetch(refresh)

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
    print(f"  rail stations: {len(kept)} kept, {len(dropped)} dropped pre-merge")

    kept.extend(central_bus_stations(busdata, busnamed))
    kept.extend(rakavlit_stations(cabledata))
    kept.extend(metronit_stations(mstops))

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
        if fa == fb or fa in SUPPRESS_NEAR_RAIL or fb in SUPPRESS_NEAR_RAIL:
            continue  # these are suppressed near rail, not merged into it
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

    def representative(members):
        return min(members, key=lambda i: (
            0 if family(kept[i][1]) == "train" else 1,
            RANK.get(kept[i][1].get("railway"), 3),
            0 if kept[i][1].get("name:en") else 1,
            -len(kept[i][1]),
        ))

    rep = {r: representative(m) for r, m in clusters.items()}
    mid = {}
    for r, m in clusters.items():
        pts = [kept[i][2] for i in m]
        mid[r] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    fam = {r: family(kept[rep[r]][1]) for r in clusters}
    rail_clusters = [r for r in clusters if fam[r] not in SUPPRESS_NEAR_RAIL]

    rows, review = [], []
    for root, members in clusters.items():
        best = rep[root]
        e, t, _, _, _ = kept[best]
        lat, lng = mid[root]

        # A bus or cable car station on a rail station's doorstep is the same
        # hiding zone, so drop it instead of adding a near-duplicate point.
        if fam[root] in SUPPRESS_NEAR_RAIL and rail_clusters:
            near, d = min(((r, haversine(mid[root], mid[r])) for r in rail_clusters),
                          key=lambda x: x[1])
            if d <= BUS_RAIL_M:
                review.append({
                    "name": label(t), "id": f"{e['type']}/{e['id']}",
                    "lat": lat, "lng": lng,
                    "issue": f"{d:.0f} m from {label(kept[rep[near]][1])}, which is "
                             "already in the list - same hiding zone",
                    "action": "suppressed",
                })
                continue

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
    supp = [r for r in review if r["action"] == "suppressed"]
    lines += ["", f"## Bus and cable car stations suppressed as duplicates ({len(supp)})", "",
              f"Within {BUS_RAIL_M} m of a station already in the list, so omitted "
              "to avoid two hiding zones on one site.", ""]
    lines += ["| Station | OSM | Why |", "|---|---|---|"]
    for r in sorted(supp, key=lambda x: x["name"]):
        lines.append(f"| {r['name']} | `{r['id']}` | {r['issue']} |")

    lines += ["", f"## Excluded as not in service ({len(excl)})", "",
              "Either not yet open, or closed. These are **not** in `stations.csv`; "
              "add them back if service resumes.", ""]
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
    print(f"  wrote REVIEW.md: {len(incl)} to verify, {len(excl)} not-yet-open, "
          f"{len(supp)} suppressed as duplicates of a rail station")


if __name__ == "__main__":
    main()
