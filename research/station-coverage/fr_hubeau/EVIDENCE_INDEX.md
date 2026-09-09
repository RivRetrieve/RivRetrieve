# fr_hubeau — evidence index

Every recording captured by this survey, with the integrity fields required by issue #222
(exact request URL and parameters, HTTP status, media type, UTC retrieval instant, response bytes,
SHA-256) and the finding it supports. Regenerate any with
`scripts/capture.py <recording_id> <url> [key=value ...]`.

Every route surveyed is public and unauthenticated. No credentials, cookies or tokens were sent
or stored.

| Recording | Status | Bytes | SHA-256 (first 16) | Retrieved (UTC) | Establishes |
| --- | --- | --- | --- | --- | --- |
| [`hubeau_sites_grandeur_declaration`](recordings/hubeau_sites_grandeur_declaration.recording.json)<br><sub>https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/sites</sub> | 200 | 789,378 | `e47c1a8c0defdde5` | 2026-09-08T14:22:01Z | grandeur_hydro is 'Q' for all 9,284 sites and date_premiere_donnee_dispo_site is empty for all: the metadata cannot establish availability. |
| [`hydroportail_historical_2020_H`](recordings/hydroportail_historical_2020_H.recording.json)<br><sub>hydro_series[startAt]=01/01/2020 hydro_series[endAt]=05/01/2020</sub> | 200 | 427,008 | `49962c7b3c914c7e` | 2026-09-08T12:26:22Z | HydroPortail serves January 2020, history observations_tr cannot reach. |
| [`hydroportail_recent_H`](recordings/hydroportail_recent_H.recording.json)<br><sub>hydro_series[startAt]=07/09/2026 hydro_series[endAt]=08/09/2026</sub> | 200 | 130,260 | `4e9d0047098cb9eb` | 2026-09-08T12:26:21Z | HydroPortail serves the current month and was the fresher route (12:15:00Z). |
| [`observations_tr_Y251002001_H`](recordings/observations_tr_Y251002001_H.recording.json)<br><sub>code_entite=Y251002001 grandeur_hydro=H</sub> | 206 | 1,407 | `2d4bf8448ea15c88` | 2026-09-08T08:45:14Z | observations_tr answers for H today, contradicting the port notes' record of a reproducible HTTP 500. |
| [`observations_tr_Y251002001_Q`](recordings/observations_tr_Y251002001_Q.recording.json)<br><sub>code_entite=Y251002001 grandeur_hydro=Q</sub> | 503 | 300 | `5764fed31b533e20` | 2026-09-08T08:45:17Z | A captured transient 503 from observations_tr: the route is intermittently unavailable. |
| [`observations_tr_Y251002001_Q_working`](recordings/observations_tr_Y251002001_Q_working.recording.json)<br><sub>code_entite=Y251002001 grandeur_hydro=Q</sub> | 206 | 1,398 | `2d9f0d6421cbda09` | 2026-09-08T08:50:20Z | observations_tr answers for Q, with UTC timestamps and both code_site and code_station. |
| [`observations_tr_horizon_30d_ok`](recordings/observations_tr_horizon_30d_ok.recording.json)<br><sub>code_entite=Y251002001 grandeur_hydro=H date_debut_obs=2026-08-09T00:00:00Z</sub> | 206 | 969 | `3e3cbeb87e721156` | 2026-09-08T11:50:48Z | A 30-day window is served. |
| [`observations_tr_horizon_31d_rejected`](recordings/observations_tr_horizon_31d_rejected.recording.json)<br><sub>code_entite=Y251002001 grandeur_hydro=H date_debut_obs=2026-08-08T00:00:00Z</sub> | 400 | 174 | `be2c2f997e3ef078` | 2026-09-08T11:50:49Z | Day 31 is refused with HTTP 400 ValidateDateMin, the publisher stating its own limit explicitly. |
| [`observations_tr_latest_H`](recordings/observations_tr_latest_H.recording.json)<br><sub>code_entite=Y251002001 grandeur_hydro=H</sub> | 206 | 918 | `bba1935f7265e66e` | 2026-09-08T12:26:24Z | Freshest observation from observations_tr (12:10:00Z), for the freshness comparison. |
| [`sandre_wfs_stationhydro_all`](recordings/sandre_wfs_stationhydro_all.recording.json)<br><sub>typeNames=sa:StationHydro</sub> | 200 | 3,149,478 | `32b91c7bcf318ea3` | 2026-09-08T09:31:40Z | Producer (NomIntervenant) for 5,366 of 6,454 hydrometry stations in one request; the same properties the per-station id.eaufrance.fr lookups return. |
| [`sandre_wfs_stationmesure_producers`](recordings/sandre_wfs_stationmesure_producers.recording.json)<br><sub>typeNames=sa:StationMesureEauxSurface</sub> | 200 | 9,396,012 | `5c60f76fd9070076` | 2026-09-08T12:41:27Z | Producer (ProducteurDuJeu) for all 869 temperature stations. |

## Derived inventories

| File | Rows | Contents |
| --- | --- | --- |
| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | 33,139 | Final inventory: every station x product with status, basis, producer and window. |
| [`STATION_TABLE.md`](STATION_TABLE.md) | 7,323 | Readable station list, one row per station. |
| [`inventory/hubeau_counts.csv`](inventory/hubeau_counts.csv) | 20,245 | Whole-record counts for the daily and temperature products. |
| [`inventory/instantaneous_counts.csv`](inventory/instantaneous_counts.csv) | 12,908 | observations_tr counts over its rolling 30-day window. |
| [`inventory/instantaneous_history.csv`](inventory/instantaneous_history.csv) | 682 | Bounded HydroPortail probe of in-service zeros, over two windows outside the real-time horizon. |

## Reproduction

```bash
uv run python research/station-coverage/fr_hubeau/scripts/sweep_daily_availability.py
uv run python research/station-coverage/fr_hubeau/scripts/sweep_instantaneous.py
uv run python research/station-coverage/fr_hubeau/scripts/probe_instantaneous_history.py
uv run python research/station-coverage/fr_hubeau/scripts/build_inventory.py
uv run python research/station-coverage/fr_hubeau/scripts/build_station_table.py
uv run python research/station-coverage/fr_hubeau/scripts/build_evidence_index.py
```

Every sweep resumes: pairs already carrying a result are skipped, and rows that failed transport
are retried rather than settled. `verify_evidence.py` re-hashes every recording and re-checks the
inventory's completeness assertions without touching the network.
