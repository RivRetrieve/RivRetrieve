# ANA source-series conformance

## Supported source facts

Conventional daily stage and discharge retain separate `Bruto` (`1`) and
`Consistido` (`2`) identities. The Hidro 1.4 dictionary and retained current API
correspondence establish `Mediadiaria=1` as daily mean, stage in cm and discharge
in m3/s. Midnight labels do not establish day support or a time zone. Both remain
unknown. See `daily-definitions-report.md`, the derived dictionary/SQL evidence,
and exact `HidroSerieCotas` / `HidroSerieVazao` recordings in the archive.

Adopted telemetry retains `Cota_Adotada` and `Vazao_Adotada` identities. Manual
page 11 establishes cm, m3/s and measurement/collection time. It does not establish
sampling cadence, an instantaneous statistic, temporal support, a zone or a stage
datum. Those facts remain unknown; the documented measurement-time anchor remains
separate. Catalogue products, source descriptions and lineage use these same limits. The current detailed endpoint is not equivalent to the
adopted endpoint and adopted access is not exhaustive telemetry discovery.

## Retained investigation

The detailed sensor/manual/display investigation and its acquisition records
are retained in the private source archive. No independent unit, reference or
time mapping was established for these three detailed fields. None is enrolled.
Their known existence and bounded mapping limitation remain explicit in
incomplete response and catalogue inventory. Historical observed differences do
not establish general physical equivalence or nationwide availability.

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
