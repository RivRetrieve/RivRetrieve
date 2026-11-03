# Australia BoM retrieval behavior

Settle scope and design for [Effort #646](https://github.com/RivRetrieve/RivRetrieve/issues/646)
(step 4 of the [provider-port guide](../../docs/maintenance/provider-ports.md))
for `au_bom`, and deliver the implementation together with it: `config.py`,
`fetch.py` and `parse.py`, plus their tests. Unlike steps 1 through 3, this
step does not split into a separate vision PR and implementation PR.
Austria's `at_ehyd` port took the same combined approach for its own step 4
(PR #674): retrieval design here is tightly coupled to the actual request and
response shapes, and a vision written before writing the code would have
had to guess at details that only became clear while implementing it. Several
of the findings below are exactly that kind of detail.

The port belongs to [Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334).
Builds on the merged
[source-access](2026-11-01-au-bom-source-scope-and-access.md),
[catalogue](2026-11-02-au-bom-station-catalogue-and-metadata.md) and
[series-identity](2026-11-03-au-bom-series-identity-and-physical-meaning.md)
visions. The declaration stays `CatalogueOnly`; switching it to `LiveStages`
is Effort #647's job, not this one.

## Window semantics: inclusive bounds, correctly interpreted across time zones

Checked live, 2026-11-03, against `getTimeseriesValues`: a `from`/`to` window
is inclusive at both ends (a three-day date-only window returns three rows,
one for each day named; a three-hour instant-bounded window returns four
rows, one for each hour named, including both endpoints). `config.py`
declares `WindowGranularity("iso-instant")` with `StopConvention.INCLUSIVE`
to match.

The shared engine renders `iso-instant` windows as UTC instants with a `Z`
suffix. Checked live that BoM's parser interprets this correctly: a `Z`
window from `00:00` to `03:00` UTC returns the same four hourly rows as the
equivalent `+10:00`-stamped window, each correctly labeled at its true local
hour (`10:00` through `13:00`), not a naively shifted one. `config.py`
declares `zone=ZoneValue("+10:00")`, matching the `time_zone` fact #645
already settled, so that a calendar-day request window lands on BoM's actual
local calendar day.

## Resolving a station's live ts_id: one shared prerequisite call per station

#645 handed this step a concrete requirement: some stations carry two
distinct `ts_id` for the same admitted series, and `series.py`'s
`describe_series()` already keys `series_id` on `ts_id` to keep both. This
step adds the acquisition side: `fetch.py` cannot address a series by a
fixed `ts_id` the way a static mapping would, because the live `ts_id` is
only known from a response.

`fetch.py` issues one `getTimeseriesList` call per station — filtered by
`station_no` alone, with no `parametertype_name` filter — before any
`getTimeseriesValues` call. Checked live: this single call returns every
series the station carries, across every parameter type, in one response.
Declaring `SHARED_ACQUISITION_PRODUCTS` as one group covering all 18 admitted
products means the shared engine batches every requested product for a
station into one `fetch()` call, so this prerequisite call happens once per
station regardless of how many products are requested, following the same
pattern `at_ehyd` uses to deduplicate its own `Messstellen/info` call across
its `owf` products.

**`ts_name` alone is ambiguous.** Checked live at station `410730`: the exact
`ts_name` string `DMQaQc.Merged.DailyMean.24HR` is shared by discharge,
stage, pH, turbidity, electrical conductivity and water temperature alike —
six different series with the same name, distinguished only by
`parametertype_name`. This confirms, concretely, the warning step 1 recorded
from the legacy reference client's behavior: a lookup keyed on `ts_name`
alone can silently resolve to the wrong quantity's series. `fetch.py` and
`parse.py` resolve a product's `ts_id` by the pair `(ts_name,
parametertype_name)`, never `ts_name` alone, and `AuBomTimeseriesValuesCoordinates`
carries both.

**Duplicate `ts_id` for one product are requested together, not sequentially.**
Checked live: `getTimeseriesValues` accepts a comma-separated `ts_id` list
and returns one block per `ts_id` in the response (not necessarily in the
requested order — `parse.py` matches each block by its own `ts_id` field,
never by position). When the prerequisite lookup resolves two `ts_id` for one
product, `fetch.py` requests both in a single `getTimeseriesValues` call
rather than issuing two. Checked live with station `138020A`'s known
discharge pair: one of its two `ts_id` returns real rows for a recent window,
the other returns zero — consistent with one being a replaced or
decommissioned sensor record, not two interchangeable duplicates. `parse.py`
reports both: a `SUCCESS` outcome for the live one, `EMPTY` for the other,
under two distinct `series_id`.

## Response format: JSON, for one consistent error envelope

`getTimeseriesValues` and `getTimeseriesList` both support `format=csv` and
`format=json`. Checked live that an invalid parameter (for example a
nonexistent `ts_id`) produces a different-shaped error body depending on
format: with `format=csv`, a transient `DatasourceError` is JSON while an
invalid-parameter error is XML (`<ExceptionReport>`); with `format=json`,
both come back as the same JSON envelope (`{"type": "error", "code": ...,
"message": ...}`), differing only in the `code` field's value. `config.py`'s
routes request `format=json` throughout, so a parse failure never has to
branch on content-type to find the error body.

## The same HTTP 500 for a transient failure and a permanent one

Checked live: BoM returns HTTP 500 both for a transient backend failure
(`code: "DatasourceError"`) and for a permanent, non-retryable parameter
error (`code: "InvalidParameterValue"`, for example a `ts_id` that does not
exist). The shared transport's retry policy
(`src/rivretrieve/_internal/transport.py`'s `TRANSPORT_POLICY`) treats any
HTTP 500 as retryable, purely by status code, with three attempts and
backoff before raising `TransportFailure`. There is no hook anywhere in the
transport or acquisition layers for a provider to inspect a response body
before that retry decision, and a failure that results from retry exhaustion
is explicitly excluded from `source_acquisition.py`'s
`SourceResponseMeaning` resolution (`http_response_meaning` returns
`UNSPECIFIED` for any `RETRY_EXHAUSTED` failure, by the function's own
documented contract).

This means a permanently invalid request costs the same three-attempt probe
as a genuinely transient one before `fetch.py` ever sees it, and `fetch.py`
has no way to shorten that or to carry a finer distinction forward through
`FailedSourceRequest.meaning`, since that enum does not have a case for this.
`fetch.py` does not attempt to work around this with its own response-body
inspection: doing so would have no consumer, since the shared `Issue`
machinery already classifies any `FailedSourceRequest` uniformly regardless.
Correcting step 1's original phrasing: the earlier vision noted that
retrieval code "needs retry-with-backoff" for BoM's transient failure; the
shared engine already provides this, for both failure kinds alike, and no
provider-local retry code is written here. If this uniform cost ever proves
to matter in practice, it is a shared-infrastructure question for
`transport.py`/`source_acquisition.py`, not something scoped to `au_bom`.

## Empty windows, no-match series and published nulls

Checked live: a window with no data returns HTTP 200 with an explicit
zero-row body, not an error — `parse.py` reports this as `OutcomeStatus.EMPTY`
for the affected series. When the prerequisite lookup finds no `ts_id` at all
for a requested product at a station (checked live: an unresolvable station
or series name returns HTTP 200 with an empty row set, not an error either),
`parse.py` reports `OutcomeStatus.NO_MATCH` for that product, matching
`at_ehyd`'s identical handling of its own `Messstellen/info` prerequisite.

Checked live: a row can carry a timestamp with no value at all (a genuine
published null), distinct from the row being absent. `parse.py` preserves
this as a null in the `value` column rather than dropping the row or
treating it as zero.

No rolling-retention boundary was tested or found. An `EMPTY` outcome is
accepted at face value — this step does not invent a distinction between
"genuinely no data" and "before some undocumented retention start," since no
evidence establishes one exists.

## Quality codes: one informational issue per flagged row

#645 confirmed quality codes are present and named at every admitted series.
This step designs the emission, following the precedent #645 already named:
`jp_mlit`'s per-occurrence pattern, not `no_nve`'s per-code aggregation.
`parse.py` emits one `info`-severity `Issue` per row whose `Quality Code
Name` is not `quality-A`, naming the station, product, series, the exact
numeric code and name, and the source timestamp — an informational note
about what BoM itself reports, not a judgement RivRetrieve makes about the
value's usability. The numeric value itself is never filtered or dropped
because of its quality code.

## Day definition and label time: a different, mandatory vocabulary from #645's

`ProductConfig.semantics` (`src/rivretrieve/_internal/engine.py`) is a
required, retrieval-level field, separate from `PhysicalFacts.day_definition`/
`timestamp_anchor` in the catalogue-level series description. #645 left
those `PhysicalFacts` fields unestablished because no provider in this
codebase currently populates them. `ProductConfig.semantics` is a different
system with real precedent for populated values (`no_nve` uses `Daily(...)`,
though with `DayDefinition("unknown")`): it is mandatory for every product,
and #645's confirmed evidence lets `au_bom` populate it with real values
rather than `"unknown"`.

`config.py` sets:

- `Daily(DayDefinition("00:00"), DailyLabelTime("00:00:00"))` for the `24HR`
  daily products (`DailyMean`, `DailyMax`, `DailyMin`) — confirmed in #645's
  vision as midnight-to-midnight, labeled at midnight.
- `Daily(DayDefinition("09:00"), DailyLabelTime("09:00:00"))` for the `09HR`
  daily discharge mean — confirmed as 09:00-to-09:00, labeled at 09:00.
- `Hourly(IntervalDefinition("unknown"))` for the hourly products.
  `IntervalDefinition` currently accepts only the literal value `"unknown"`
  in this codebase (`src/rivretrieve/_internal/engine.py`'s `__post_init__`
  rejects anything else), so no other value is available regardless of
  evidence.
- `UnknownTemporalSupport()` for the monthly and yearly products. The engine
  has no `Monthly`/`Yearly` semantics type; this is the only declaration
  available, the same one `at_ehyd` uses for all of its products.

This does not reopen #645's decision about `PhysicalFacts`; the two systems
serve different purposes and populating one does not require populating the
other.

## Required handoff

- **[Provider integration, #647](https://github.com/RivRetrieve/RivRetrieve/issues/647):**
  switches `declaration.py` from `CatalogueOnly` to `LiveStages`, wiring
  `config()`, `window_declarations()`, `fetch` and `parse` into an
  `EngineProviderModule`, and updates `provider_manifest.py`'s registration
  kind.
- **A future, separate Effort:** the uniform retry-cost finding above, only
  if it proves to matter in practice for `au_bom` or another provider with
  the same status-code overload.

## Delivery and acceptance

- `src/rivretrieve/_internal/providers/au_bom/config.py`: route coordinates,
  `ProviderConfig`, `ProductWindowDeclarations`, `SHARED_ACQUISITION_PRODUCTS`.
- `src/rivretrieve/_internal/providers/au_bom/fetch.py`: `resolve_timeseries_list()`
  and `fetch()`.
- `src/rivretrieve/_internal/providers/au_bom/parse.py`: `parse()`, dispatching
  on the prerequisite list payload versus a product's values payload.
- `tests/test_au_bom_retrieval.py`: unit tests for ts_id resolution
  (including the `ts_name` ambiguity and its `parametertype_name`
  disambiguation), `fetch()`'s request shape and failure isolation,
  `parse()`'s outcome classification, published-null preservation, and one
  assembled `drive()`-level test proving the shared prerequisite call and
  unit conversion both work end to end.
- Verification: `uv run ruff check`, `uv run ty check src` and
  `uv run pytest --logic-only` all pass with no regressions.

Post a concise scope-and-delivery update on #646. Close #646 once this PR is
merged, matching the pattern used for Efforts #643 through #645.
