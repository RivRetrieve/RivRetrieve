# The canonical station catalogue is identity and geometry

The station catalogue keeps five columns:

```text
provider_id | station_id | latitude | longitude | crs
```

`name`, `country`, `elevation_m`, `drainage_area_km2`, `river_name`, `status`,
`observed_properties` and the station-level `start_date` and `end_date` are not canonical
columns. Everything removed remains readable in the provider's native table in the source's
own words, so this is a relocation rather than a deletion.

The test is the one `AGENTS.md` already states: harmonise identity and physics, never
harmonise judgement. A column earns canonical status where it means the same thing across
thirteen sources; anything resting on interpretation stays native. Applied honestly it
removes most of what the catalogue ships today, and each removal has its own reason.

`country` is a Python constant in every generator (`COUNTRY = "United States"`,
`usgs_nwis/generate_catalogue.py:35`), never read from any source, stamped onto all 64,069
rows. Under ADR 0012 it has no origin at all, which makes it the one guaranteed column that
is simultaneously 100% populated and 100% invented. It is deleted rather than moved to
provider level, because an agency spanning several countries would make a provider-level
country wrong in the same way, and because coordinates cannot supply one: ADR 0005 already
bans deriving a political boundary from a point.

`elevation_m` and `drainage_area_km2` are physical quantities whose reference is not
carried. USGS returns `alt_datum_cd` in the default site-service output, distinguishing
NGVD29 from NAVD88, and the generator discards it; the glossary term **datum** already says
two heights in metres are not comparable unless they share one. Catchment area is a modelled
number whose model differs by agency.

`river_name` fails its own purpose. Its only use over the native table is querying across
providers without knowing each spelling, and river names do not harmonise across borders,
which `AGENTS.md` names explicitly as something we do not adjudicate. `name` means something
different in each source: `'St. John River at Ninemile Bridge, Maine'`,
`"L'HOGNEAU À GUSSIGNIES (59)"`, `'Murten'`, `'茂志利（もしり）'`. `status` is stated in three
incompatible vocabularies, and `end_date` already carries the operational signal from data
the source stated. `observed_properties` would be a denormalised copy of `station_products`
with no source field and therefore no origin; filtering by what a gauge measures resolves
through that table instead, so it cannot drift from what it was copied from.

The station-level dates go because USGS publishes period of record per parameter, not per
station, so filling `stations.start_date` means taking a minimum across parameters, which is
maths on a value the source never stated. Coverage lives in `station_products` where sources
state it.

`crs` is added on the terms ADR 0006 set for time. Coordinates and their reference travel
together, `unknown` where the source states no datum, values being EPSG identifiers, which
is the registry national systems already live in. `jp_mlit` shows why it is per station
rather than per provider: the scraper reads WGS84 coordinates from the 世界測地系 row and
falls back to `japan_sites.csv` values of unrecorded datum when that fails, so one provider's
rows may mix datums differing by roughly 400 metres.

## Consequence: ADR 0007's deferred timezone question is answered no

ADR 0007 left the use of USGS `tz_cd` and `dst_flag` to be reconsidered in catalogue work.
There is no station timezone column. Of the thirteen, only USGS publishes a per-station zone
and ADR 0007 established its abbreviations are inadmissible, so the column would be
`unknown` for all 64,069 stations. `tz_cd` stays in the native table verbatim. The UTC helper
the Program Map lists as unspecified remains parked, since its stated condition, reliable
per-station zones, is not met.

## Consequence: the canonical table is not human-readable

Choosing a gauge from `provider_id | station_id | latitude | longitude | crs` requires
joining the native table for a label. That cost is accepted because a name whose meaning
varies by source is not a fact this library should present as harmonised.
