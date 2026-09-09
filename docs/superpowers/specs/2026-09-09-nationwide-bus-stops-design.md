# Nationwide bus stops for the Jet Lag station list

**Date:** 2026-09-09
**Status:** approved

## Goal

Add Israel's bus stops to `stations.csv`, restricted to stops that are genuinely
useful as hiding zones: well served all day, not requiring advance booking, and not
piled on top of stations already on the map.

## Source

The Ministry of Transport GTFS feed,
`https://gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip` (223 MB).

The BusMaps API is deliberately **not** used for the bulk work. The feed has 30,455
stops against a 10,000-request budget, and per-stop queries would not return a full
timetable anyway. Everything below is computed offline from the zip. The API key is
kept in `.busmaps-key`, gitignored — the repo is public.

Relevant members, with sizes, since one of them dictates the implementation:

| File | Size | Use |
|---|---:|---|
| `stop_times.txt` | 1.47 GB | departures per stop per trip — **must be streamed** |
| `trips.txt` | 51 MB | trip → route, service |
| `stops.txt` | 5.0 MB | coordinates, `stop_code`, Hebrew name |
| `translations.txt` | 6.2 MB | 32,795 English names, keyed by the Hebrew string |
| `calendar.txt` | 3.2 MB | which services run on which dates |
| `routes.txt` | 984 KB | route names, for advance-booking detection |

## Selection rules

**Service day.** `calendar.txt` entries are short-dated, so an arbitrary Wednesday
may fall outside coverage. Pick the date inside the feed's coverage with the fullest
Sunday–Thursday service; record it in the output. Friday and Shabbat are excluded —
they would distort every frequency.

**Advance booking.** Excluded. GTFS marks these natively as `pickup_type=2` ("must
phone agency"); route names are also checked for `הזמנ`. Report what each rule
catches rather than assuming one suffices.

**Frequency.** For each `(stop, route)` pair, take that route's departures from that
stop between 07:00 and 22:00 on the service day. The pair qualifies when service is
continuous across the whole window:

- the first departure is at or before 07:30,
- the last departure is at or after 21:30,
- every consecutive gap is 30 minutes or less.

The edge conditions are the point: without them a route beginning at 09:00 would
qualify on a technicality. A stop qualifies if **any single route** meets this — the
requirement is not on the stop's combined service.

**Spacing.** Each added stop must be at least 250 m from every station already on the
map, *including bus stops added earlier in the same pass*. Candidates are therefore
processed greedily in descending order of `n_lines` (all distinct routes serving the
stop, not only qualifying ones), so that where two candidates compete for the same
250 m of space, the busier one wins.

## Structure

Split by cost, not by topic.

- **`bus_stops.py`** — new, expensive, run rarely. Downloads the feed, applies the
  advance-booking and frequency rules, resolves English names, and writes
  `bus-candidates.csv` (`stop_id, stop_code, name, name_he, lat, lng, n_lines`).
  Emits no spatial filtering.
- **`generate.py`** — existing. Reads `bus-candidates.csv` as one more source and
  applies the 250 m greedy rule as its **final** step, after every other station is
  placed.

The 250 m rule lives in `generate.py` because it must run against the finished map;
computing it in `bus_stops.py` would test candidates against a stale snapshot and
create a circular dependency between the two outputs.

## Naming

English from `translations.txt`, matched on the Hebrew `stop_name`. Hebrew retained
where no translation exists. The OSM `gtfs:stop_code:IL-MOT` join is a fallback only;
it is not needed if translation coverage is good.

## Verification

- Frequency logic is unit-tested against fixtures before running on real data: an
  evenly spread route qualifies; a route with a midday gap does not; routes that
  start late or finish early do not; boundary cases at exactly 30 minutes do.
- Counts reported at every filter stage, and the cap chosen from those numbers
  before anything is added to `stations.csv`.
- `validate.py` must pass on the final file.

## Outcome

Measured funnel: 30,455 stops in the feed → 14,893 with all-day service → 4,505
after the 250 m rule → 1,000 kept (`BUS_STOP_CAP`), cutting off at 15 lines.

Two corrections found while implementing, both of which would have gone unnoticed:

1. **Advance booking is not detectable by name.** No route in the feed is named
   הזמנה מראש and nothing uses `pickup_type=2`; both original checks matched zero.
   The real marker is `route_type=715`, "Demand and Response Bus Service" (14
   routes).
2. **The feed carries more than buses.** Rail, tram, funicular and shared taxis
   share `routes.txt`, so the first run let train stations qualify on *train*
   frequency. Restricted to `route_type=3`.

Service day used: 2026-10-04 (Sunday), the in-coverage weekday with the most active
services (13,850) — chosen from 21 candidate dates.
