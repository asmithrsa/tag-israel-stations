# Israeli station list for Jet Lag: Hide and Seek

A custom station list for the [JetLagHideAndSeek map generator](https://taibeled.github.io/JetLagHideAndSeek/),
covering **156 open stations** in Israel:

| System | Stations |
|---|---:|
| Israel Railways | 71 |
| Jerusalem Light Rail (Red Line + open Yellow Line segment) | 46 |
| Tel Aviv Light Rail (Red Line) | 33 |
| Carmelit (Haifa funicular) | 6 |

Metronit is not included yet — see [Adding bus stops](#adding-bus-stops-later).

## Using it

1. Push this repo to GitHub (see below), then open `stations.csv` on github.com and
   click **Raw**. Copy that URL. It looks like:

   ```
   https://raw.githubusercontent.com/<you>/jetlag-israel-stations/main/stations.csv
   ```

2. In the map generator, open the **Hiding Zone** sidebar, tick **Use custom
   stations**, and paste the URL into *Import stations from URL*. Press **Import**.

The link must be a **raw** file URL. A normal GitHub page URL returns HTML, and the
site fetches it directly from your browser with no proxy — so the host has to send
`Access-Control-Allow-Origin: *`. `raw.githubusercontent.com` does; most file hosts
and Google Drive share links do not.

### Pushing to GitHub

```bash
gh repo create jetlag-israel-stations --public --source=. --push   # if you have gh
# or, manually:
git remote add origin https://github.com/<you>/jetlag-israel-stations.git
git push -u origin main
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
3. **Across families**, at 150 m, so a train station and the light rail stop at its
   entrance form one hiding zone. This pass is strictly pairwise: candidates are
   matched nearest-first and each station may be claimed only once. That matters at
   Yitzhak Navon, which is 44 m from `Central Station` and 81 m from
   `Binyene Ha'Uma ICC`; merging both would chain two distinct Red Line stops
   together, so only the nearer is absorbed. Merged interchanges take the heavy-rail
   station's name.

Merged stations use the centroid of their platforms.

## Adding bus stops later

**Do not hand-edit `stations.csv`** — `generate.py` overwrites it. Instead create
`extra-stations.csv` alongside it, with the same columns:

```csv
name,lat,lng,id,system
Some Bus Stop,32.079000,34.774000,bus/1,Metronit
```

`generate.py` merges that file into the output and skips any `id` already present,
so your additions survive every regeneration. Only `name`, `lat` and `lng` are
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
- `Jerusalem - Yitzhak Navon` and `Petah Tikva–Kiryat Aryeh` each absorb the light
  rail stop at their entrance, so each is one hiding zone. `Binyene Ha'Uma ICC`
  stays separate 104 m away: it is a Red Line stop in its own right, not the stop
  serving the railway station. `validate.py` lists any such remaining pair each run.
