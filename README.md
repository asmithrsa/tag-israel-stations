# Israeli station list for Jet Lag: Hide and Seek

A custom station list for the [JetLagHideAndSeek map generator](https://taibeled.github.io/JetLagHideAndSeek/),
covering **204 open stations** in Israel:

| System | Stations |
|---|---:|
| Israel Railways | 69 |
| Jerusalem Light Rail (Red Line + open Yellow Line segment) | 45 |
| Tel Aviv Light Rail (Red Line) | 33 |
| Carmelit (Haifa funicular) | 6 |
| Central bus stations | 27 |
| Haifa Rakavlit (cable car) | 2 |
| Metronit (Haifa BRT, transfer stations) | 22 |

### Metronit

The Haifa BRT's **transfer stations** only, pinned by OSM node id in `METRONIT`.
Nothing in the data selects them: just 5 of 94 confirmed stops carry
`network=Metronit`, the lines share the numbers 1–5 with ordinary Haifa buses (so
filtering on `route_ref` yields 165 names, most of them city stops), and the route
relations are incomplete — line 3 has no stop members at all and line 4 has one.

16 of the 22 were verified as members of the Metronit route relations. `Hallisa`,
`Tsahal`, `Savyone Yam` and `HaPalmach` sit on line 3 and `Grand Canyon` on line 4,
neither of which has usable stop members, so
they are matched instead on an exact unqualified name served by a Metronit line —
`Tsahal` in particular has six namesakes on Tsahal Street in Haifa, all carrying a
cross-street suffix, against the one plain `צה״ל` up in the Krayot. Those four are
the likeliest to need correcting.

Platforms are grouped by their pinned name rather than by distance: the two
direction platforms of one station run up to 135 m apart (Police Headquarters), well
beyond the 60 m merge radius used elsewhere.

### Haifa Rakavlit

The רכבלית transit gondola (opened 2022) is pinned by OSM node id in `RAKAVLIT`,
because OSM offers no reliable handle on it: two of its six stations carry neither
the `operator` nor the `network` tag, and there is no route relation to follow. Four
have no English name, so those are supplied in the same table. `generate.py` warns if
an id stops resolving, so the pinning fails loudly rather than silently shrinking the
list. Haifa's other cable car — the Stella Maris tourist tramway — is deliberately
excluded.

Only three of its six stations are in service — **HaMifratz**, **Technion (Lower)**
and **University of Haifa** — and OSM maps all six identically, with nothing to
separate the built-but-unopened ones, so the other three are pinned in
`CLOSED_STATIONS`. HaMifratz is then dropped as a duplicate, sitting 199 m from
HaMifrats Central Station, which already covers that site. That leaves **2** rows;
the third open station is present as `HaMifrats Central Station`.

OSM names the lower Technion stop `תחנת טכניון מרכז` ("Technion Center"). It is the
lower of the two — 2255 m along the line from the HaMifrats terminus against 2677 m
for `טכניון עליון` ("Technion Upper"), on a line that climbs the whole way — so it is
listed here as `Technion (Lower)`.

### Central bus stations

Israel's intercity terminals (*תחנה מרכזית*, **merkazit**) come from two OSM sources,
because neither is complete on its own. `amenity=bus_station` is authoritative but
misses several towns — Kiryat Shmona, Ness Ziona, Rosh Pina and Beit She'an have a
central bus station mapped only as named platforms, or in Beit She'an's case only as
a building. A name search fills those gaps, with two guards:

- The name must contain a station word. Matching `מרכזית` alone catches
  *HaSdera HaMerkazit*, which is a **boulevard**, not a station.
- A platform-derived name must carry a place qualifier. 18 platforms across the
  country are named simply `Central Station`, which identifies no town.

Where both sources describe one station they are folded together within 500 m, which
also absorbs spelling variants (Acko/Akko, Kfar Saba/Sava, Tzfat/Safed). A qualified
platform name beats a vague station name — that is how the terminal mapped only as
`Central bus station` is identified as **Kiryat Shmona**'s.

**A bus or cable car station within 400 m of a rail station is dropped**, not merged,
since it is the same hiding zone. That removes 15, including Jerusalem, Be'er Sheva,
Nahariya, both Haifa bus terminals and the Rakavlit's HaMifrats end. `REVIEW.md` lists every one. The 400 m cut sits in
a clean gap in the data: collisions run up to 391 m (Lod's temporary terminal) and
the next nearest is Tel Aviv New Central Bus Station at 523 m.

## Using it

1. Push this repo to GitHub (see below), then open `stations.csv` on github.com and
   click **Raw**. Copy that URL. It looks like:

   ```
   https://raw.githubusercontent.com/asmithrsa/tag-israel-stations/main/stations.csv
   ```

2. In the map generator, open the **Hiding Zone** sidebar, tick **Use custom
   stations**, and paste the URL into *Import stations from URL*. Press **Import**.

### After updating the list

`raw.githubusercontent.com` serves this file with `cache-control: max-age=300`, and
the site imports it with a plain `fetch()` that does no cache-busting. So shortly
after a push, re-importing gives you the **previous** version — new stations appear
to be missing even though the file is correct.

**A query parameter alone does not fix this.** It defeats the *browser* cache, but
GitHub's CDN keys on the path and keeps serving stale content regardless: measured
against a fresh random parameter on every request, a push took **210 seconds** to
appear. So after pushing, wait ~4 minutes, then import with a bumped parameter to
clear your own browser too:

```
https://raw.githubusercontent.com/asmithrsa/tag-israel-stations/main/stations.csv?v=2
```

To check whether the CDN has caught up before importing:

```bash
curl -s "https://raw.githubusercontent.com/asmithrsa/tag-israel-stations/main/stations.csv" | wc -l
```

The link must be a **raw** file URL. A normal GitHub page URL returns HTML, and the
site fetches it directly from your browser with no proxy — so the host has to send
`Access-Control-Allow-Origin: *`. `raw.githubusercontent.com` does; most file hosts
and Google Drive share links do not.

### Pushing to GitHub

The repo lives at
[github.com/asmithrsa/tag-israel-stations](https://github.com/asmithrsa/tag-israel-stations).
To push further changes:

```bash
git push
```

## What counts as "open"

Data comes from OpenStreetMap via the Overpass API. Deciding which stations are
actually in service takes more than reading tags, because OSM contains ruins,
building sites and lines that are mapped before they open. The filters:

- **Geography.** Clipped to the Israel and Palestinian-territory boundary relations
  rather than a bounding box. A bounding box over this region pulls in Hejaz-railway
  ruins across the Jordanian border (Aqaba, Wadi Rum, Ma'an), which are
  indistinguishable from working stations by tags alone.
- **Lifecycle tags.** Anything carrying `construction:`, `proposed:`, `disused:`,
  `abandoned:` and similar prefixes is dropped, as is anything named as a ruin.
- **Light rail and funicular.** Confirmed by proximity to an *open* route relation.
  This matters: OSM maps the **Haifa–Nazareth "Nofit" line**, which has not opened,
  and its stops look identical to working ones.
- **The Jerusalem Yellow Line (L3) opened in stages.** As of August 2026 the
  HaTurim–Malha segment carries passengers while the northern continuation towards
  Ramot is still being built. OSM currently maps only the open segment, but its 11
  stops are pinned by id in `PARTIAL_OPEN` rather than the line being marked open
  wholesale, so stops added later for the unopened section stay out until checked.
- **Israel Railways.** Route relations for trains reference *ways*, not stop nodes,
  so proximity is useless there — the nearest route member can be 28 km away.
  Rail stations are confirmed by catalogue presence instead (a `wikidata` ref
  and/or an Israel Railways `operator` tag), which 67 of 74 carry.

Some changes leave no trace in the data at all. `Biblical Zoo` and `Jerusalem Malcha`
lost their service when the Beit Shemesh–Jerusalem section closed, but OSM still tags
both as open, with `wikidata` refs and no lifecycle tag — no heuristic can catch
that. They are pinned in `CLOSED_STATIONS` in `generate.py`; add a station there if
its service ends. (`Bet Shemesh` itself stays: it is still served from the Lod side.)

Stations that could not be confirmed either way are **kept** and listed in
[`REVIEW.md`](REVIEW.md) rather than silently dropped. Once you have checked one by
hand, add its OSM id to `CONFIRMED_OPEN` in `generate.py` so it is not flagged again
— `Shomron – Tayyiba` and `Tira - Kokhav Ya'ir` are already recorded there as
confirmed open. `REVIEW.md` currently lists nothing outstanding.

### Duplicate handling

One row per station, never one per platform — but distance alone cannot decide this,
because **the closest pairs in the whole dataset are not duplicates at all**. They
are different systems sharing an interchange:

| Distance | Pair | Same station? |
|---:|---|---|
| 0 m | `Abba Hillel` / `Aba Hilel Station` | yes — mapped twice |
| 4 m | `Ben Gurion` / `Ben Gurion Light Rail Station` | yes — mapped twice |
| 23 m | `Petah Tikva–Kiryat Aryeh` / `Kiryat Aryeh light rail station` | **no** — train + light rail |
| 42 m | `Jerusalem - Yitzhak Navon` / `Central Station` | **no** — train + light rail |
| 115 m | `Central Station` / `Binyene Ha'Uma ICC` | **no** — adjacent Red Line stops |

So merging happens in three scoped passes rather than by one distance rule:

1. **Within a mode family** (train / light rail / funicular), at 60 m. Measured
   across every pair under 300 m, platform twins of one station are never more than
   23 m apart and the closest distinct same-mode stations are 115 m apart, so 60 m
   sits safely between them. This collapses per-direction platform pairs and
   spelling variants mapped twice.
2. **By name within a family**, at 600 m, for interchanges split across lines — so
   `HaMifrats Central Station` and `HaMifrats Central Station - HaEmek Line` appear
   once.
3. **Across families**, at 150 m, so a train station and the light rail stops
   serving it form one hiding zone. Matched hub-and-spoke: a rail station absorbs
   every light rail stop within range, because a large interchange is served from
   more than one side — `Jerusalem - Yitzhak Navon` takes in both `Central Station`
   (44 m) and `Binyene Ha'Uma ICC` (81 m). Each light rail stop can be claimed only
   once, so two rail stations near one stop cannot chain together through it. Merged
   interchanges take the heavy-rail station's name.

Merged stations use the centroid of their platforms.

## Adding bus stops later

**Do not hand-edit `stations.csv`** — `generate.py` overwrites it. Instead create
`extra-stations.csv` alongside it, with the same columns:

```csv
name,lat,lng,id,system
Some Bus Stop,32.079000,34.774000,bus/1,Metronit
```

`generate.py` merges that file into the output and skips any `id` already present,
so your additions survive every regeneration. Note that entries added this way are
**not** subject to the 400 m rail-proximity rule — that applies only to the central
bus stations the script derives itself. Only `name`, `lat` and `lng` are
required; `id` defaults to a coordinate string and `system` to `Custom`.

## Regenerating

```bash
python3 generate.py --refresh   # re-query Overpass and rebuild
python3 validate.py             # check the result against the app's import rules
```

`validate.py` mirrors the rules in the app's `src/maps/api/importers.ts`: the
`text/plain` format sniff, the header aliases, and the row loop that silently skips
malformed rows. It also asserts no duplicate ids or coordinates, no blank names, and
no unmerged neighbours within 120 m.

## Notes

- The Jerusalem Red Line runs north past the Green Line through Shu'afat, Beit
  Hanina, Pisgat Ze'ev and Neve Ya'akov. Those are included as operating stations on
  a continuous line; delete the rows if your play area stops short.
- Names are English (`name:en`) where OSM has them, Hebrew otherwise.
- The `system` column is ignored by the importer — it is there so you can filter the
  list yourself.
- `Jerusalem - Yitzhak Navon` is one hiding zone covering the railway station and
  both light rail stops around it (`Central Station`, `Binyene Ha'Uma ICC`), and
  `Petah Tikva–Kiryat Aryeh` likewise absorbs its light rail stop. `validate.py`
  reports any cross-system pair left within 150 m; there are currently none.
