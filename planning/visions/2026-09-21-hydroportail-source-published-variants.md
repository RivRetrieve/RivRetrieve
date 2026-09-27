# HydroPortail source-published variants

Program: https://github.com/RivRetrieve/RivRetrieve/issues/312
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/311

## Outcome

Expose HydroPortail's source-published variants of instantaneous discharge and
stage through the shared `find` / `series` / `pick` / `fetch` API redesigned in
PR #300. The root README's Brazil example illustrates this shared API; this is
not a separate Brazil-specific model or a new API design.

The owner confirmed the Python example below as the intended outcome. The ticket's
original list of raw, corrected, pre-validated and validated was provisional,
not a requirement to invent four exclusive processing-stage series. Discovery
established different public selectors. Expose the choices the source actually
publishes, with their actual meanings:

| Variant | HydroPortail label | Meaning of the selection |
|---|---|---|
| `raw` | Données brutes | Raw series |
| `validated` | Données validées | Validated series |
| `pre_validated_and_validated` | Données pré-validées et validées | Source selection covering pre-validated and validated data |
| `most_valid` | Données les plus valides | Source-owned selection of its most valid data |

These are variants of the same physical quantity, not additional physical
quantities. `most_valid` is a named source selection, not a RivRetrieve quality
ranking, preferred default, or fallback algorithm. RivRetrieve must not reproduce
or infer its selection algorithm. The combined selector must not be labelled
pre-validated-only. Do not manufacture corrected-only or pre-validated-only
histories by filtering other responses.

## Intended Python API

This example describes the required behavior after implementation, not the
current raw-only capability or an already executed public-path result.

```python
import rivretrieve as rr

france = rr.find(
    provider="fr_hydroportail",
    station="Y251002001",
    quantity="discharge",
    statistic="instantaneous",
)

print(sorted(rr.series(france)["variant"].to_list()))

# Expected:
# ['most_valid', 'pre_validated_and_validated', 'raw', 'validated']

# Request all four, retaining their separate series identities.
all_variants = rr.fetch(
    france,
    start="2020-01-01",
    end="2020-01-02",
)

# Or request only one source variant.
validated = rr.pick(france, variant="validated")

validated_result = rr.fetch(
    validated,
    start="2020-01-01",
    end="2020-01-02",
)

print(rr.series(validated_result))
print(validated_result.data)
print(validated_result.issues)
```

Any of the four variant identifiers works with `rr.pick`. Replacing
`quantity="discharge"` with `quantity="stage"` exposes the equivalent water-level
choices. Discovery and selection use the existing catalogue-based API and do not
require observation downloads.

Unrestricted retrieval requests all matching supported variants. Explicit
selection requests only the selected variant, without preference, substitution,
or fallback. Selecting `validated` must not return raw observations when the
validated series is empty. Selecting `most_valid` requests that named source
series, even when the source returns raw observations within it.

Retain distinct identities when variants have identical or overlapping values.
Do not merge them into a best-available record or deduplicate one variant away.
Preserve the difference between null observations, absent rows, empty successful
series and identified failed requests. Independent successful variants must
survive another variant's failure under the established caller issue policy.
Fatal internal contract errors remain fatal.

## Source evidence and limits

Read these dated discovery findings as protocol evidence, not permanent counts
or guarantees of availability. Recheck the source during implementation and
retain reproducible requests and representative response evidence.

Authoritative entry points:

- https://hydro.eaufrance.fr/stationhydro/1232000101/series
- https://hydro.eaufrance.fr/glossaire
- https://hydro.eaufrance.fr/build/hydro-series.6104cd00.js
- https://hydro.eaufrance.fr/build/graph-measures.cfa55bcd.js

On 2026-09-21 the public station form offered exactly the four selectors above.
The page default was `most_valid`; that source UI default does not change
RivRetrieve's unrestricted-retrieval behavior. The glossary defines raw,
corrected, pre-validated and validated processing stages separately; glossary
stages are not proof of independently requestable series.

Live requests used GET
`https://hydro.eaufrance.fr/stationhydro/ajax/{full_station_code}/series`, with:

- `hydro_series[startAt]` and `hydro_series[endAt]` in `dd/mm/yyyy`;
- `hydro_series[variableType]=simple_and_interpolated_and_hourly_variable`;
- `hydro_series[simpleAndInterpolatedAndHourlyVariable]=Q` or `H`;
- `hydro_series[statusData]` set to the exact selector.

Sixteen legitimate calls, covering both Q and H, all returned HTTP 200, matching
station/metric/selector envelopes, UTC labels, Q unit code `l` and H unit `mm`.
The existing scoped Q unit definition establishes `l/s`; do not reinterpret the
code as a generic litre quantity.

| Station and inclusive dates | Raw | Validated | Pre-validated and validated | Most valid |
|---|---|---|---|---|
| `1232000101`, 2026-06-01 to 2026-06-02 | 282 rows, point status 4 | Empty | Empty | 282 rows, identical to raw |
| `Y251002001`, 2020-01-01 to 2020-01-02 | 576 rows, point status 4 | 50 rows, point status 16 | Identical to validated | Identical to validated |

The counts apply separately to Q and H. At the second station the reviewed
history differs from raw in timestamps and values: its first observation is
00:01 rather than 00:00. These are not necessarily co-sampled revisions of each
raw observation. Empty responses still contain station, metric, unit, selector
and title metadata. Validate that identity even when no observations return.
An empty bounded request does not establish absence of all history.

Anonymous requests with `statusData=corrected` or `statusData=pre_validated`
returned HTTP 400 with `Le choix sélectionné est invalide.` They are invalid
selectors on the checked route, not empty series. Alternate authenticated
export routes were not investigated and are not required for this outcome.

The published scripts identify observation field `s` as processing status:
0 Sans validation, 4 Données brutes, 8 Données corrigées, 12 Données pré-validées,
16 Données validées. Field `q` is qualification; `m` and `c` identify method and
continuity. Requested `series.statuses` and each observation's `s` are distinct
source facts. Retain source metadata in the established native evidence/receipt
path; do not turn processing status into a quality flag or label every
`most_valid` observation validated. This Effort does not introduce a new
harmonised quality/status column or observation-status filtering API.

No positive corrected or pre-validated point witness, mixed-status precedence,
or general selection algorithm was established by these bounded windows.
Do not infer behavior from numeric ordering of status codes. These limits do not
prevent exposing the evidenced named selectors faithfully.

## Fit within the existing provider and contracts

Start from the landed provider split in Effort #310. Preserve `fr_hydroportail`
as an independent publication-service provider, its source-owned station
inventory, full station codes, station-own rather than site-combined Q/H,
physical units and source time semantics. Do not use Hub'Eau as a fallback or
transfer its observation counts or licence to HydroPortail.

Current anchors are `providers/fr_hydroportail/config.py`, `fetch.py`, `parse.py`
and `generate_catalogue.py` under `src/rivretrieve/_internal/`. Fetch currently
hardcodes `raw`, parsing checks `statuses == raw`, and the mappings publish a
single `raw` identity without populating the public variant field. Merely
accepting more response strings cannot establish distinct source identities.

Reuse the existing source-series contracts and their multiple-series support.
Keep source identity consistent through discovery, explicit selection, parsed
results, outcomes, receipts, caches and exports. A raw-only cached inventory or
result must not satisfy an expanded unrestricted request as though all four
variants had been covered. Preserve old evidence and data without reinterpreting
their identities. No compatibility facade or migration guide is required.

Keep the existing raw historical availability witnesses scoped to raw. Do not
promote them into proof that all variants have observations. Supported variants
with unchecked history remain selectable with honest unknown availability; no
national observation census is required.

Useful existing references include the root README's Brazil example,
`source_series.py`, `catalogues/source_series.py`, Brazil's series declarations,
and Norway's existing per-series request-failure isolation. Choose implementation
mechanisms from the architecture, not from the number of variants in the example.

## Observable completion and boundaries

The proposed public API example works for discharge and stage. All four source
variants can be inspected and individually selected. Unrestricted retrieval
retains all matching variant identities, and explicit retrieval neither acquires
nor substitutes unrelated variants. Source mismatches and invalid responses are
reported through the established source-failure model, not converted to empty
successes or hidden by fallback.

Verify public-path identity, independent failures, null/empty distinctions,
overlapping variant values, source envelope validation, and relevant cache and
export round trips. In particular, exercise an explicit subset followed by an
unrestricted retrieval so cached raw-only or subset results cannot hide missing
variants. Use representative live Q/H access for every supported selector and
record its actual outcome. Empty results are legitimate when correctly identified;
never invent observations to satisfy a test. For discovered bugs, first add a
failing regression on the real path, then make that same test pass. Run project
validation through `uv`.

Keep directly affected descriptions truthful. Effort #313 owns the final separate
provider pages and coherent shared documentation rewrite. This Effort does not
add other physical quantities, temporal products, site-level retrieval, local
quality control, aggregation or a new public API. Additional in-purpose source
capabilities, contradictory evidence or unrelated defects must be raised with
the owner rather than silently included or dismissed; record follow-up issues
when a separate scope is needed.

Publication of this vision is not implementation or delivery of the Effort.
