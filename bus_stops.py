#!/usr/bin/env python3
"""Select Israeli bus stops worth adding to the Jet Lag station list.

Reads the Ministry of Transport GTFS feed and keeps stops that have genuinely
all-day service and do not require advance booking. Writes bus-candidates.csv;
the 250 m spacing rule is applied later, by generate.py, against the finished map.

See docs/superpowers/specs/2026-09-09-nationwide-bus-stops-design.md

Usage:  python3 bus_stops.py [--refresh]
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import io
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
GTFS_DIR = HERE / "gtfs"
GTFS_ZIP = GTFS_DIR / "israel.zip"
FEED_URL = "https://gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip"

# The service window the frequency rule is measured over.
WINDOW_START = 7 * 3600           # 07:00
WINDOW_END = 22 * 3600            # 22:00
MAX_GAP = 30 * 60                 # a bus at least every 30 minutes
# Edge tolerances: service must already be running by 07:30 and still be running at
# 21:30, otherwise a route that starts at 09:00 would qualify on a technicality.
FIRST_BY = WINDOW_START + MAX_GAP
LAST_FROM = WINDOW_END - MAX_GAP

# GTFS pickup_type 2 means "must phone the agency to arrange" - advance booking.
# In this feed nothing uses it, and no route is named הזמנה מראש either; both checks
# are kept as belt and braces but the mechanism that actually works is route_type.
PICKUP_PHONE_AGENCY = "2"
BOOKING_WORDS = ("הזמנ",)          # הזמנה מראש / בהזמנה

# Only ordinary buses. The feed also carries rail (2), tram (0), funicular (5),
# shared taxis (8) and demand-response buses (715). Counting those would be wrong
# twice over: 715 is precisely the advance-booking service to exclude, shared taxis
# are not buses, and rail/tram/funicular stops are already on the map as stations -
# leaving them in let train stations qualify on *train* frequency.
BUS_ROUTE_TYPE = "3"
DEMAND_RESPONSE_TYPE = "715"       # "Demand and Response Bus Service"


def qualifies(departure_secs) -> bool:
    """True when a route serves a stop continuously across 07:00-22:00.

    Departures outside the window are ignored; the list need not be sorted.
    """
    times = sorted(t for t in departure_secs if WINDOW_START <= t <= WINDOW_END)
    if not times:
        return False
    if times[0] > FIRST_BY or times[-1] < LAST_FROM:
        return False
    return all(b - a <= MAX_GAP for a, b in zip(times, times[1:]))


def parse_time(s: str) -> int | None:
    """GTFS times can exceed 24:00:00 for trips running past midnight."""
    try:
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + int(sec)
    except (ValueError, AttributeError):
        return None


def rows(zf: zipfile.ZipFile, name: str):
    """Stream one member as dicts without materialising it."""
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))


def download(refresh: bool):
    if GTFS_ZIP.exists() and not refresh:
        return
    GTFS_DIR.mkdir(exist_ok=True)
    import subprocess
    print(f"  downloading {FEED_URL} ...", flush=True)
    subprocess.run(["curl", "-s", "--max-time", "1800", "-o", str(GTFS_ZIP), FEED_URL],
                   check=True)


def pick_service_day(zf) -> tuple[dt.date, set[str]]:
    """The in-coverage Sunday-Thursday date with the most services running.

    calendar.txt is short-dated, so an arbitrary weekday may fall outside coverage.
    Friday and Saturday are excluded: Israeli bus service on those days would
    distort every frequency measurement.
    """
    weekday_col = ["monday", "tuesday", "wednesday", "thursday", "friday",
                   "saturday", "sunday"]
    cals = []
    for r in rows(zf, "calendar.txt"):
        cals.append((
            r["service_id"],
            dt.datetime.strptime(r["start_date"], "%Y%m%d").date(),
            dt.datetime.strptime(r["end_date"], "%Y%m%d").date(),
            [r[c] == "1" for c in weekday_col],
        ))
    counts = collections.Counter()
    for _, start, end, days in cals:
        d = start
        while d <= end:
            # date.weekday(): Monday=0 .. Sunday=6, matching weekday_col
            if days[d.weekday()] and d.weekday() not in (4, 5):   # skip Fri, Sat
                counts[d] += 1
            d += dt.timedelta(days=1)
    if not counts:
        raise SystemExit("no Sunday-Thursday service dates found in calendar.txt")
    best = max(counts.items(), key=lambda kv: (kv[1], -kv[0].toordinal()))[0]
    active = {sid for sid, start, end, days in cals
              if start <= best <= end and days[best.weekday()]}
    print(f"  service day: {best:%Y-%m-%d} ({best:%A}), "
          f"{len(active)} services active "
          f"(best of {len(counts)} candidate dates)")
    return best, active


def main():
    refresh = "--refresh" in sys.argv
    download(refresh)
    print("Selecting bus stops from the MOT GTFS feed")

    with zipfile.ZipFile(GTFS_ZIP) as zf:
        day, active_services = pick_service_day(zf)

        # Routes, and which of them are advance-booking by name.
        route_name, booking_routes, bus_routes = {}, set(), set()
        by_type = collections.Counter()
        for r in rows(zf, "routes.txt"):
            blob = f"{r.get('route_long_name','')} {r.get('route_desc','')}"
            rtype = r.get("route_type", "")
            by_type[rtype] += 1
            route_name[r["route_id"]] = r.get("route_short_name") or r["route_id"]
            if rtype == DEMAND_RESPONSE_TYPE or any(w in blob for w in BOOKING_WORDS):
                booking_routes.add(r["route_id"])
            elif rtype == BUS_ROUTE_TYPE:
                bus_routes.add(r["route_id"])
        print(f"  routes: {len(route_name)} total, by type "
              f"{dict(by_type.most_common())}")
        print(f"  keeping {len(bus_routes)} ordinary bus routes (type "
              f"{BUS_ROUTE_TYPE}); excluding {len(booking_routes)} "
              f"advance-booking (type {DEMAND_RESPONSE_TYPE})")

        # Trips running on the service day.
        trip_route = {}
        for r in rows(zf, "trips.txt"):
            if r["service_id"] in active_services and r["route_id"] in bus_routes:
                trip_route[r["trip_id"]] = r["route_id"]
        print(f"  bus trips running that day: {len(trip_route)}")

        # Departures per (stop, route). This is the 1.47 GB pass.
        by_pair = collections.defaultdict(list)
        stop_routes = collections.defaultdict(set)
        phone_pairs = set()
        scanned = kept = 0
        for r in rows(zf, "stop_times.txt"):
            scanned += 1
            if scanned % 5_000_000 == 0:
                print(f"    ...{scanned:,} stop_times rows", flush=True)
            rid = trip_route.get(r["trip_id"])
            if rid is None:
                continue
            t = parse_time(r.get("departure_time") or r.get("arrival_time"))
            if t is None or not (WINDOW_START <= t <= WINDOW_END):
                # still record the route as serving the stop, for n_lines
                if t is not None:
                    stop_routes[r["stop_id"]].add(rid)
                continue
            sid = r["stop_id"]
            if r.get("pickup_type") == PICKUP_PHONE_AGENCY:
                phone_pairs.add((sid, rid))
                continue
            by_pair[(sid, rid)].append(t)
            stop_routes[sid].add(rid)
            kept += 1
        print(f"  scanned {scanned:,} stop_times rows, kept {kept:,} in-window "
              f"departures across {len(by_pair):,} stop-route pairs")
        print(f"  advance-booking excluded: {len(booking_routes)} routes "
              f"(by route_type/name), {len(phone_pairs):,} pairs by pickup_type=2")

        # Qualifying stops.
        good_stops = {}
        for (sid, rid), times in by_pair.items():
            if rid in booking_routes:
                continue
            if qualifies(times):
                good_stops.setdefault(sid, set()).add(rid)
        print(f"  stops with >=1 all-day route: {len(good_stops):,}")

        # Names and coordinates, English from translations.txt.
        english = {}
        for r in rows(zf, "translations.txt"):
            if r.get("lang") == "EN":
                english[r["trans_id"]] = r["translation"]
        print(f"  English translations available: {len(english):,}")

        out = []
        for r in rows(zf, "stops.txt"):
            sid = r["stop_id"]
            if sid not in good_stops:
                continue
            he = r["stop_name"]
            out.append({
                "stop_id": sid,
                "stop_code": r.get("stop_code", ""),
                "name": english.get(he, he),
                "name_he": he,
                "lat": f"{float(r['stop_lat']):.6f}",
                "lng": f"{float(r['stop_lon']):.6f}",
                "n_lines": len(stop_routes.get(sid, ())),
                "n_allday_lines": len(good_stops[sid]),
            })

    out.sort(key=lambda x: (-x["n_lines"], -x["n_allday_lines"], x["name"]))
    path = HERE / "bus-candidates.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["stop_id", "stop_code", "name", "name_he",
                                          "lat", "lng", "n_lines", "n_allday_lines"])
        w.writeheader()
        w.writerows(out)
    translated = sum(1 for r in out if r["name"] != r["name_he"])
    print(f"\n  wrote {path.name}: {len(out):,} candidate stops "
          f"({translated:,} with English names, "
          f"{len(out) - translated:,} Hebrew-only)")
    print(f"  service day used: {day:%Y-%m-%d}")


if __name__ == "__main__":
    main()
