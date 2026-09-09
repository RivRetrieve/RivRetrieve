# ba_fhmzbih — evidence index

Every preserved response, with its integrity fields and what it establishes.

Two kinds, deliberately separate:

- **Response-shape examples** (`recordings/`) illustrate a route or a response shape. An
  example cannot substantiate a different station's result, and none is cited as one.
- **Per-station-per-product evidence** (`evidence/`) supports exactly one inventory row.

## Response-shape examples

| Recording | Status | Retrieved (UTC) | Bytes | SHA-256 | Establishes |
| --- | --- | --- | --- | --- | --- |
| `absent_4109_WT_404.recording.json` | 404 | 2026-09-07T09:02:59.361489Z | 244 | `e1201cb8fc2bd6ed…` | Response shape: WT workbook route returns 404. |
| `absent_4228_H_404.recording.json` | 404 | 2026-09-07T09:02:58.151646Z | 239 | `4e7c38fbff5c4286…` | Response shape: station declared in the H layer, workbook route returns 404. |
| `absent_9025_H_404.recording.json` | 404 | 2026-09-07T09:02:58.757897Z | 239 | `7e3160c6d6f26ea8…` | Response shape: station declared in the H layer, workbook route returns 404. |
| `boundary_1020_WT_populated.recording.json` | 200 | 2026-09-07T08:46:43.731904Z | 95,020 | `b39b0b0981851ea6…` | Response shape: a fully populated workbook, every data row carrying a value. |
| `boundary_4060_WT_headeronly.recording.json` | 200 | 2026-09-07T08:46:43.016013Z | 3,640 | `ea267e09c2f28242…` | Response shape: no data rows, parameter and unit still declared. |
| `boundary_4110_H_smallest.recording.json` | 200 | 2026-09-07T08:46:45.294812Z | 74,560 | `7b9e27b02a74b5c1…` | Response shape: populated H workbook; unit cm. |
| `boundary_4110_Q_smallest.recording.json` | 200 | 2026-09-07T08:46:44.518802Z | 76,202 | `c49c1d0753084c70…` | Response shape: populated Q workbook; unit m³/s. |
| `horizon_4024_Q_1M_exists.recording.json` | 200 | 2026-09-07T09:06:43.931116Z | 13,307 | `aaa542c9f38e8ddf…` | Response shape: a one-month workbook period exists. |
| `horizon_4024_Q_5Y_absent.recording.json` | 404 | 2026-09-07T09:06:44.582432Z | 239 | `8e8c1904fa54722c…` | Response shape: a _5Y filename returns 404 for this station and product. |
| `horizon_directory_listing_403.recording.json` | 403 | 2026-09-07T09:06:45.207547Z | 234 | `1c8090b99e8d24ac…` | Directory listing refused with 403; recorded, not bypassed. |
| `layer_10.recording.json` | 200 | 2026-09-07T08:42:16.830255Z | 106,381 | `9ef83a18428beaf2…` | Vodostaj (H) layer membership - 99 hydrological stations. |
| `layer_20.recording.json` | 200 | 2026-09-07T08:42:17.650242Z | 64,675 | `cf8ce047653a311e…` | Proticaj (Q) layer membership - 60 stations; identical to the committed baseline. |
| `layer_30.recording.json` | 200 | 2026-09-07T08:42:18.442616Z | 13,777 | `3a30e0660be87667…` | Temperatura vode (WT) layer membership - 13 stations. |
| `layer_40.recording.json` | 200 | 2026-09-07T08:42:19.141526Z | 29,171 | `8ffe6e3ac6359f5a…` | GroundWaterLevel layer; object type 'Stanica podzemnih voda' - a different object type. |
| `layer_50.recording.json` | 200 | 2026-09-07T08:42:19.877799Z | 24,446 | `7a7d193b4c7d9cd5…` | GroundWaterTemp layer; object type 'Stanica podzemnih voda' - a different object type. |
| `layer_60.recording.json` | 200 | 2026-09-07T08:42:20.627501Z | 24,741 | `4e278220a9d8ec63…` | Precipitation layer; object type 'Meteorološka stanica' - a different object type. |
| `layer_70.recording.json` | 200 | 2026-09-07T08:42:21.364988Z | 24,733 | `a878f8dcfb16746b…` | AirTemp layer; object type 'Meteorološka stanica' - a different object type. |
| `layer_80.recording.json` | 200 | 2026-09-07T08:42:22.115645Z | 86,715 | `ebdf1ffdd9e7147c…` | EPPWaterLevel layer - 81 stations of object type 'General;Hidrološka stanica', the same type as the surveyed population. Excluded by layer alias, not by object type: see UNRESOLVED.md §7. |
| `layer_90.recording.json` | 200 | 2026-09-07T08:42:22.895659Z | 42,528 | `2c53daf49a9f144c…` | EPPFlow layer - 40 stations of object type 'General;Hidrološka stanica', the same type as the surveyed population. Excluded by layer alias, not by object type: see UNRESOLVED.md §7. |
| `layers_manifest.recording.json` | 200 | 2026-09-07T08:42:16.623444Z | 1,884 | `2921b2fd316e4216…` | The publisher's own list of ten layers; the authoritative product-to-layer mapping. |
| `lowrow_1110_Q_1rows.recording.json` | 200 | 2026-09-07T09:23:47.834622Z | 3,740 | `8c3f8fe19010952f…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `lowrow_4023_Q_164rows.recording.json` | 200 | 2026-09-07T09:23:48.414670Z | 5,614 | `dfc5e22b834ba220…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `lowrow_4911_Q_338rows.recording.json` | 200 | 2026-09-07T09:23:48.985561Z | 7,628 | `72113347f1944120…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `lowrow_9001_Q_1rows.recording.json` | 200 | 2026-09-07T09:23:49.543427Z | 3,758 | `f7602547a1d16a5d…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `lowrow_9020_Q_1rows.recording.json` | 200 | 2026-09-07T09:23:50.075322Z | 3,740 | `fc7c5bc2e895b4e2…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `lowrow_9043_Q_1rows.recording.json` | 200 | 2026-09-07T09:23:50.683534Z | 3,742 | `e0baa3bc91005ed2…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `lowrow_9130_Q_1rows.recording.json` | 200 | 2026-09-07T09:23:51.252251Z | 3,744 | `eb63e41834a446ef…` | Timestamped rows with every measurement cell published empty. Establishes that the publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot classify availability. |
| `portal_root.recording.json` | 200 | 2026-09-07T09:00:32.092827Z | 1,957 | `86d62b4fa6067e76…` | Portal identity: page title names Agencija za vodno području rijeke Save. |

## Per-station-per-product evidence

`evidence/` holds **361** files: one per station × product pair, plus the historical-access
attempts. Every inventory row links to its own file, and `verify_evidence.py` checks that the
file's station, product, URL, acquisition instant and digest match the row citing it.

Each file records the exact request URL, HTTP status, media type, UTC acquisition instant,
byte size and the SHA-256 **of the full publisher response**.

**180** of them retain the complete response bytes — every response that carries no
observation values does, which covers all four non-measurement categories:

| Status | Rows | Bytes retained |
| --- | --- | --- |
| `timestamped_without_measurements` | 35 | full |
| `no_data_rows` | 82 | full |
| `access_failed` | 7 | full |
| `measurements_present` | 173 | header, window and excerpt; see below |

For workbooks that do carry observations, the complete bytes are a year of the agency's
measurements. Issue #223 directs that whole observation histories are not to be downloaded
merely to prove access, and the source records no redistribution grant, so those files keep the
full-response digest plus a bounded excerpt: opening rows, and witness rows carrying real
values. One populated cell establishes the classification, which is what the excerpt preserves.
The excerpt carries its own separate digest and is never presented as the response digest.

**Limitation, stated plainly:** a digest over bytes that are not retained cannot be recomputed
later. The source serves a rolling window, so a re-fetch returns different bytes. The digest
fixes what was received at the recorded instant; it is not a re-verification route.

## Historical-access attempts

`evidence/horizon/` holds every attempted period suffix and format variant, with its own
response preserved and its station and product named. See `inventory/horizon_probe.csv`.
