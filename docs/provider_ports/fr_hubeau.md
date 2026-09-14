# fr_hubeau provider port

The live adapter uses `fetch.py`, `parse.py`, and `config.py`. The original adapter
was contributed by Thiago von Däniken.

## Coverage and evidence

The captured baseline contains **7,323 stations and 33,139 selectable pairs**:
6,454 hydrometry stations with five hydrometric products, plus 869 temperature
stations with temperature only. This replaces the former three-station, six-pair
sample. Native station identifiers, published site mappings and coordinates are
preserved. No new station survey or population expansion is implied.

| Availability basis | Pairs | Public state |
|---|---:|---|
| Publisher counts or exact positive historical witnesses | 20,966 | available |
| Publisher whole-record count zero at acquisition | 4,948 | unknown |
| Empty in both specified historical windows | 524 | unknown |
| Historical check failed | 97 | unknown |
| Recent empty, history unchecked | 6,604 | unknown |

Unknown pairs remain selectable. An empty window, a failed check and unchecked
history are not proof of unsupported products or permanent absence. Positive
evidence does not promise continuous records or values in every requested period.
`J783301020` instantaneous Q returned HTTP 500 for June 1–8, 2026 and an empty
June 1–8, 2023 window. Its governing state is failed historical check, not two-window
emptiness. No retry was used to change this account.

The [machine-readable coverage account](fr_hubeau_coverage.json) and reviewed
[governing ledger](../../research/station-coverage/fr_hubeau/inventory/governing_evidence.json.xz)
retain the counts and exact acquisition identities. Acquisition dates are mixed,
not a simultaneous snapshot. The offline catalogue build takes that reviewed ledger
as an explicit composition-root input. It does not open research files at runtime.
Public ledger consistency is not private source-body verification. Acceptance also
checks all retained private bodies against their receipts, exact request identities
and source contents. The private verification corpus is not distributed in wheels.

## Retrieval

Daily published products use Hub'Eau `obs_elab` with `date_debut_obs_elab`,
`date_fin_obs_elab`, and `grandeur_hydro_elab`. Temperature uses
`temperature/chronique`. Pagination follows each complete `next` URL without
appending the original query parameters. There is no local aggregation.

Instantaneous H and Q use the selected station's own HydroPortail
`/stationhydro/ajax/{code_station}/series` route. The sample identity gate and
site-Q substitution are removed. Site discharge is a different series whose
supplying station can change. Station IDs are never truncated to derive site IDs;
site-level access and activation calendars remain outside this adapter.

HydroPortail series declare UTC, H in mm, Q in l/s, and raw status. The actual
`series.unit` governs conversion, not the display preference `unitQ`. The parser
checks station, metric, unit, UTC and requested raw-series identity before examining
rows, including valid empty envelopes. Source null measurements stay null. Receipts
preserve source status, quality, method and continuity fields byte-for-byte. The
engine owns padding, clipping, unit conversion and source-issue handling.

Historical instantaneous access is retained. No freshness advantage over Hub'Eau
is claimed: retained comparison responses have the same latest instant. Normal user
requests are not restricted to the research windows.

## Time and attribution limits

Daily and temperature zones remain unknown. The temperature OpenAPI names
`date_mesure_temp` as `Date de la mesure`, `heure_mesure_temp` as `Heure de la mesure`,
and `resultat` as `Résultat`. These definitions do not establish interval or point
support. `water_temperature_reported` therefore keeps unknown frequency, statistic,
period type and anchor. Published bounds, temporal support and datums are not invented.

Official HydroPortail/PHyC and Hub'Eau publication evidence establishes responsibility
for the supplied material, not universal authorship of historical measurements.
`NomIntervenant` names an organisation; `ProducteurDuJeu` identifies a station-reference
dataset producer. Neither establishes the original producer of every measurement.
The old three-station original-producer assertions are not retained as that claim.

Source terms and citation words remain verbatim. In particular:
“L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données.”
A publication label does not resolve the dataset-author citation question. No licence
classification or blanket redistribution permission is inferred.

## Offline certification

Station-own Q uses genuine padded-request recordings. Its independent boundary
expectations are 282 rows, first `2026-06-01T00:00:00 UTC`, last
`2026-06-02T18:00:00 UTC` for public June 1–2, 2026. The source-only author did not
inspect the provider implementation or its output. Committed
[recording provenance](../../tests/test_data/fr_hydroportail_station_Q_provenance.md)
identifies exact bytes, dates and the independent literals. The older site-Q captures
remain historical evidence; they are not substituted into station-own tests.
