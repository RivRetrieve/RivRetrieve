# ANA source-series conformance

## Supported source facts

Conventional daily stage and discharge retain separate `Bruto` (`1`) and
`Consistido` (`2`) identities. The Hidro 1.4 dictionary and retained current API
correspondence establish `Mediadiaria=1` as daily mean, stage in cm and discharge
in m3/s. Midnight labels do not establish day support or a time zone. Both remain
unknown. See `daily-definitions-report.md`, the derived dictionary/SQL evidence,
and exact `HidroSerieCotas` / `HidroSerieVazao` recordings in this directory.

Adopted telemetry retains `Cota_Adotada` and `Vazao_Adotada` identities. Manual
page 11 establishes cm, m3/s and measurement/collection time. It does not establish
a zone or stage datum. The current detailed endpoint is not equivalent to the
adopted endpoint and adopted access is not exhaustive telemetry discovery.

## Detailed sensor/manual/display investigation, 2026-09-20

`detailed-channel-research.json` records non-secret request identities, retrieval
instants, byte counts and hashes for this follow-up investigation.

* Re-fetched the publisher OpenAPI. Its 41,928-byte SHA-256 is unchanged from
  `openapi_2026-09-19.json`: `ab715ea45626d45a6c9c9fd6d344dec74200cd0a94d7ce550396410b54dd481d`.
  Both detailed versions describe raw data in addition to adopted data. Their
  response schema is the generic `Devolucao`, with an untyped `items` object,
  not a field dictionary for sensor/manual/display units or reference meaning.
* Followed the institutional hydrological manuals page to the current 18-page
  API manual. Its SHA-256 remains
  `89e2929cb436241b4aae2bbb04c4077edd55379886f39c9a32eb7fec0c8faba3`.
  A case-insensitive extracted-text search of every page finds the detailed
  endpoint on page 8 and the adopted fields on page 11, but no `Cota_Sensor`,
  `Cota_Manual` or `Cota_Display`. This is an extracted-text finding, not a claim
  that no publisher documentation exists. Full tutorial bytes were not retained.
* Inspected the linked SNIRH and Hidroweb public entry pages and their main
  JavaScript clients. Neither client contains the exact detailed field names or
  camel-case sensor/manual alternatives checked. These are different frontends;
  their general water-level labels cannot prove an API-field mapping.
* Inspected Hidro-Telemetria and its linked `Mapa.aspx`. Both requests returned
  the same about/cookie-instructions page, not a sensor dictionary. The page says
  the system acquires, qualifies and manages near-real-time hydrometeorological
  data. This does not establish each API channel's physical facts.
* Direct institutional searches for `Cota_Sensor` and `Cota_Display` returned the
  same generic portal page. They do not establish zero search results. External
  search was unavailable because the search-service key was not configured.

The exact detailed recording remains unchanged: SHA-256
`8f4049713c0b2e46b886052092191ae9d42a0def9047543a74b17eb1bf620feb`,
96 rows, 92 non-null sensor values, 20 sensor/adopted numerical differences.
Manual and display fields are null in all 96 rows. This disproves numerical
identity in that window, not physical equivalence or general manual/display
absence. No independent unit/reference/time mapping was established for these
three detailed fields. None is enrolled. Their known existence and the bounded
mapping limitation remain explicit in incomplete response/catalogue inventory.
No credentials were needed for this follow-up and no controlled corpus was
published. Exact authenticated observations use existing safe recordings only.

## Implementation and public proof

The obsolete telemetry-only provenance wrapper is removed. Catalogue tests call
the single `with_observation_products` implementation. The three retired
`generate_catalogue*` stubs and obsolete CLI aliases are removed. CLI refusal
leaves unrelated files intact; attested inventory/native materialization and
identity checks remain. Catalogue descriptions import their source-series
function from `series`, not the observation parser.

`test_br_ana_public_daily.py` replays real monthly bytes through public credential
composition, fetch, parse, conversion, storage and receipts. The added tests prove:

* Explicit Bruto cache coverage does not satisfy all matching daily series.
* Refreshing Bruto does not erase cached Consistido.
* A response without Consistido retains unresolved diagnostics and cannot create
  false successful all-series coverage. A repeated all-series request reacquires.
* Cached sibling rows and their source definitions/inventories survive bundle
  round-trip; store receipts remain store excerpts, not publisher reconstructions.

`test_br_ana_public_telemetry.py` additionally proves incomplete unrestricted
telemetry inventory forces reacquisition while explicitly selected adopted
coverage can reuse the same native rows with truthful store receipts.
`test_br_ana_telemetry.py` binds the detailed-channel limitation to the exact
recording hash and field census. Existing scientific tests retain native duplicate
multiplicity, nulls, finite negative values, untouched status vocabulary, daily
calendar expansion, independent boundary probes and unit conversion exactly once.

The daily timestamp-anchor follow-up corrects one overclaim: midnight is retained
as `label_time`, not an established relationship to interval boundaries. The
publisher dictionary and SQL do not establish that relationship. Daily
`timestamp_anchor` is therefore not established and has no evidence binding;
telemetry retains its documented `measurement_time` anchor. Actual parser and
attested catalogue regressions first failed on the known `00:00` anchor. The
catalogue, lineage and descriptor are rebuilt from the attested offline inputs.
This does not change source labels, daily clipping, values or unit conversion.
