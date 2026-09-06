# Israeli station list for Jet Lag: Hide and Seek

A custom station list for the [JetLagHideAndSeek map generator](https://taibeled.github.io/JetLagHideAndSeek/),
covering **144 open stations** in Israel:

| System | Stations |
|---|---:|
| Israel Railways | 71 |
| Jerusalem Light Rail (Red Line) | 34 |
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
  This matters: OSM already maps the **Jerusalem Yellow Line (L3)** and the
  **Haifa–Nazareth "Nofit" line**, neither of which has opened, and their stops
  otherwise look identical to Red Line stops. 11 such stops are excluded.
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

One row per station, never one per platform. Nearest-neighbour distances in this
dataset are sharply bimodal — 108 elements have a neighbour under 50 m, then
nothing at all between 50 m and 250 m — so merging within 120 m is unambiguous.
That collapses per-direction platform pairs (Jerusalem's 95 stop nodes become 34
stations) and spelling variants mapped twice (`Abba Hillel` / `Aba Hilel Station`,
0.4 m apart). Interchanges split across lines are also merged by name within 600 m,
so `HaMifrats Central Station` and `HaMifrats Central Station - HaEmek Line` appear
once. Merged stations use the centroid of their platforms.

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
