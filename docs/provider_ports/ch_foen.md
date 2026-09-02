# ch_foen Provider Port Notes

`ch_foen` exposes three packaged instantaneous products through the shared live-stage engine. BAFU/FOEN is the data authority. `api.existenz.ch` and `influx.konzept.space` are intermediary publication and query surfaces.

## Runtime sources

Recent observations use anonymous `GET https://api.existenz.ch/apiv1/hydro/daterange`. The publisher describes this surface as historical values up to 32 days in the past. Older observations use `POST https://influx.konzept.space/api/v2/query?org=api.existenz.ch` with the `existenzApi` bucket and `hydro` measurement when the engine supplies an exact-origin-scoped Influx credential. Public credential loading is not part of this port. Without that composition input, the engine has only the anonymous REST surface and its publisher-stated 32-day horizon; unavailable or empty source results are not replaced with guessed values. Flux `range` has an exclusive stop. Exact REST and Flux interactions are committed as secret-safe `RecordingEnvelope`s under `tests/test_data/ch_foen_*.recording.json`.

The source publishes explicit UTC. Neither exact observation response publishes quality data, so the adapter does not infer quality. Raw publisher bytes remain available only through opt-in receipts.

## Products and native fields

| Product | Accepted native field | Source unit |
| --- | --- | --- |
| `discharge_instantaneous` | `flow` | `m3/s` |
| `stage_instantaneous` | `height_abs`, or `height` when it is the sole returned alternative | `m` |
| `water_temperature_instantaneous` | `temperature` | `°C` |

The complete exact parameters response is attested by `tests/test_data/ch_foen_parameters_2026-09-02.recording.json`. It distinguishes `flow` (`m3/s`) from `flow_ls` (`l/s`). The exact evidenced source query requests all five documented fields; the parser ignores `flow_ls` and does not retain or map it. The adapter does not relabel `flow_ls` as the packaged `flow` product. It fails if `flow` is absent. It also fails when both stage alternatives are returned, rather than silently conflating them. No stale daily computed products are exposed.

## Credentials

The provider reads no environment variables, config files, publisher pages, or embedded tokens. An engine-owned `AuthenticatedTransport` can apply a caller-supplied bearer credential at the transport boundary. Authorization headers are absent from source origins, recordings, receipts, errors, and representations. Public credential-loading UX remains outside this port.

## Authority and terms

The exact payload names `Swiss Federal Office for the Environment FOEN / BAFU, Hydrology` as authority and preserves the BAFU terms URL. Existenz states that its APIs are unofficial, free for public and non-commercial use, and that BAFU data must be credited and linked to BAFU. The session capture of the linked BAFU PDF returned HTTP 502; this port makes no claim about content from that failed PDF response. The already packaged provenance retains separately recorded BAFU source wording and Existenz terms.

The catalogue evidence URL uses the `#hydro` fragment. The fragment was not sent to the server, and the exact capture had no redirect.

## Catalogue

The packaged catalogue remains unchanged: 246 stations, three products, and 738 station-product rows with unknown source-published availability. Catalogue generation remains maintainer-only. The retired implementation under `reference/legacy_observations/ch_foen` was deleted only after exact REST and Flux fetch-and-parse proofs passed.
