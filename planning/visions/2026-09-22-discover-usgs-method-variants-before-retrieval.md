# Discover USGS method variants before retrieval

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/327

## Outcome

Make publisher-backed USGS method variants visible in the selection returned by
`rr.find`, so callers can inspect them with `rr.series(selection)` and select them
before fetching observations. Keep `find` offline. This is the sole objective;
reviewing or changing provider documentation PR #266 is not part of this work.

The intended public workflow is:

```python
import rivretrieve as rr

selection = rr.find(
    provider="usgs_nwis",
    station="07374000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

print(rr.series(selection).select("station_id", "variant", "published_id"))
chosen = rr.pick(selection, variant="61176")
result = rr.fetch(chosen, start="2024-01-01", end="2024-01-07", cache="bypass")
```

For a catalogue backed by the established source relationship, inspection exposes
`61176` as a concrete variant rather than only a generic `variant=None` candidate.
The selected identity agrees with the observation response. Published descriptions
are available before retrieval, including an empty string when that is what USGS
publishes. Do not manufacture descriptions or meanings for numeric identifiers.

## Why this is missing

Current discovery retains generic station/product candidates and separate
`NWIS.ts_id` catalogue claims. Observation parsing establishes variants from
`methodID`, or from `methodCode` when `methodID` is absent. The separation is
intentional: the implementation does not assume these namespaces are equivalent.

Known methods can already be requested before retrieval. Unknown catalogue
selectors remain explicit unresolved intent, and the driver filters acquired
response identities. The missing capability is discovering the selectable methods
from the packaged catalogue, not preserving them after retrieval.

The issue's daily example returned method `61176` and seven observations for
January 1–7, 2024, although discovery exposed no concrete method. Existing tests
also preserve the two distinct methods `126801` and `126805` at station `02196000`.
This is an enhancement, not a demonstrated observation-parser defect.

## Publisher evidence and the remaining technical question

The legacy [USGS Site Service](https://waterservices.usgs.gov/docs/site-service/site-service-details/)
provides metadata-only series catalogue output through `seriesCatalogOutput=true`
and `outputDataTypeCd`. Its RDB headers describe `ts_id` as “Internal timeseries ID”
and `loc_web_ds` as “Additional measurement description”. It also publishes period
of record information. This is the candidate source for offline method discovery;
there is no need to download observations inside `find`.

Investigation on 2026-09-22 found stronger evidence than numerical coincidence for
instantaneous data in USGS's own website implementation, pinned to commit
`2ca4342df592db75b97167aba4583112e5e9547f`:

- Its [metadata request](https://code.usgs.gov/wma/iow/waterdataui/-/blob/2ca4342df592db75b97167aba4583112e5e9547f/assets/src/scripts/web-services/period-of-record-metadata.js#L8-9)
  requests Site Service series catalogue output with `outputDataTypeCd=iv`.
- Its [RDB parser](https://code.usgs.gov/wma/iow/waterdataui/-/blob/2ca4342df592db75b97167aba4583112e5e9547f/assets/src/scripts/pages/custom-list/stores/period-of-record-metadata-store.js#L16-42)
  reads field 15 into `methodId` and field 16 into `methodDescription`. The
  [publisher fixture header](https://code.usgs.gov/wma/iow/waterdataui/-/blob/2ca4342df592db75b97167aba4583112e5e9547f/assets/src/scripts/mock-iv-data.js#L3772-3777)
  identifies these zero-based fields as `ts_id` and `loc_web_ds`.
- Its [IV response parser](https://code.usgs.gov/wma/iow/waterdataui/-/blob/2ca4342df592db75b97167aba4583112e5e9547f/assets/src/scripts/pages/custom-list/stores/iv-metadata-store.js#L20-28)
  reads `methodID` into `methodId`. Its
  [details component](https://code.usgs.gov/wma/iow/waterdataui/-/blob/2ca4342df592db75b97167aba4583112e5e9547f/assets/src/scripts/pages/custom-list/components/DataDetailsShowDetails.vue#L73-81)
  uses that ID to look up catalogue period-of-record metadata by equality.

This establishes an intentional publisher-client linkage for instantaneous data.
It is not a demonstrated service-wide daily-value mapping or a guarantee across
all service versions. Site catalogue rows use `uv` for these instantaneous records;
the metadata request uses `iv`.

Fresh bounded comparisons also found:

| Station and product | Site catalogue IDs | Response method IDs | Observation window |
| --- | --- | --- | --- |
| `07374000`, daily mean discharge | `61176` | `61176` | January 1–7, 2024 |
| `02196000`, daily mean discharge | `126801`, `126805` | `126801`, `126805` | January 1–7, 2000 |
| `07374000`, instantaneous discharge | `62517` | `62517` | January 1, 2024 |

Descriptions matched, including `[(2)]` for `126805`; preserve that text without
interpreting it. The Site catalogue retained that older series with an end date
of 2005-09-29. Sampling only recent observations would miss it.

Reproducible metadata URLs:

- https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=07374000&seriesCatalogOutput=true&outputDataTypeCd=dv&parameterCd=00060
- https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=02196000&seriesCatalogOutput=true&outputDataTypeCd=dv&parameterCd=00060
- https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=07374000&outputDataTypeCd=iv&parameterCd=00060

Matching response requests use `https://waterservices.usgs.gov/nwis/dv/` or `/iv/`,
`format=json`, the site and parameter above, and `startDT`/`endDT` for the listed
window. DV additionally uses `statCd=00003`.

**The daily identifier relationship remains a technical evidence requirement.**
Inspected service documentation, official R/Python clients, and current/archived
USGS website code did not establish an equivalent explicit daily crosswalk.
Matching examples alone do not establish a universal rule. Investigate and retain
sufficient publisher evidence for the scope actually implemented; do not quietly
extend the IV rule to every daily record or hard-code the example stations.
Publisher implementation evidence is useful evidence, not only prose documentation.
If the required relationship cannot be established, report the precise blocker
and supported discovery limits. Do not claim that instantaneous-only delivery or
a research report achieves the desired daily discovery outcome. The issue permits
an evidence-limit report, but the user has not chosen that as a replacement outcome.

The exploratory captures were saved outside the repository and are not a durable
handoff dependency. Reacquire and commit appropriate source evidence during
implementation, retaining exact bytes, request coordinates, acquisition time and
hashes. No exhaustive service-wide conclusion follows from these bounded probes.

## Constraints

- Keep `rr.find` and `rr.series(selection)` offline. Acquire source metadata at
  catalogue preparation, not as a hidden network request during inspection.
  No new online discovery API is required by this vision.
- Work within existing USGS station/product coverage and supported products.
  Retain catalogue vintage and explicit completeness limits. A catalogue snapshot,
  a period-of-record range, and a successful observation window are different
  claims; none establishes continuous or exhaustive historical availability.
- Preserve source catalogue claims and their provenance alongside any established
  executable identities. Do not relabel `NWIS.ts_id` as `methodID` without evidence.
  Do not invent a `methodCode` relationship when metadata does not supply one.
- Filter metadata by actual returned station, data type, parameter and statistic.
  Live Site requests with `parameterCd=00060` also returned other parameter rows.
- Preserve distinct methods, exact descriptions, unknowns and supported partial
  failures. Do not rank methods, choose a preferred one, or deduplicate independent
  series by equal values. Empty descriptions are not missing identifiers.
- Preserve unrestricted all-matching intent: discovery is not a frozen exhaustive
  list that hides new identities encountered during retrieval. Keep explicit subset
  selection, cache completeness and response-owned identity handling correct.
- Do not migrate to the replacement USGS API (#279), add temperature (#265), review
  or rewrite PR #266, or expand into provider documentation work. A focused account
  of the implemented discovery contract and evidence limits is in scope.

## Repository footholds

Paths below are under `src/rivretrieve/_internal/` unless noted:

- `providers/usgs_nwis/generate_catalogue.py` acquires and validates native catalogue
  arrays and maps the six existing product routes. Its acquisition is a 50-state
  plus DC snapshot with source filters, not every possible USGS station.
- `providers/usgs_nwis/catalogue_series.py` preserves `NWIS.ts_id` claims but builds
  generic executable candidates. This is the central discovery gap.
- `catalogues/source_series.py` supports concrete station-scoped descriptions and
  materializes identities. Its current catalogue-claims path clears inventory
  members; consider this when adding independently established concrete methods.
  Do not upgrade inventory completeness merely because methods become visible.
- `providers/usgs_nwis/parse.py` builds response identities from provider, station,
  product, namespace and identifier. Catalogue identities must agree with these
  when evidence establishes that they identify the same source series.
- `selection.py` and `discovery.py` retain explicit selectors and all-matching intent;
  `series` formats acquired information rather than contacting USGS.
- `providers/no_nve/catalogue_series.py` demonstrates concrete offline variants.
  Reuse established contracts where appropriate; do not copy its provider semantics.

Choose the smallest coherent implementation from those contracts. This vision does
not prescribe new types, modules or API names.

## Acceptance evidence

1. Offline public discovery exposes supported concrete USGS variants and exact
   source descriptions, including the daily `07374000` example once its mapping is
   established. Demonstrate that inspection performs no network acquisition.
2. The two-method `02196000` case remains discoverable and selectable without
   collapsing records, including the older method when present in the catalogue.
3. Public discovery → `pick` → `fetch` preserves matching source identity. Selecting
   one method does not accidentally select its sibling; unrestricted retrieval can
   still retain methods absent from the catalogue snapshot.
4. Focused tests cover catalogue evidence and bundle round-trips, missing or
   unsupported metadata, distinct products, subset/all cache behavior and source
   failures affected by the change. Mismatched evidence must not silently establish
   a false identity or completeness claim.
5. Retained publisher recordings and bounded live checks support the implemented
   daily and instantaneous scope. Tests use exact source evidence and label authored
   negative controls separately. A finite response window is never a historical
   inventory proof.
6. Run relevant tests and the repository's normal formatting, lint and `ty check src`
   through `uv`. Record actual results and any source-access blockers.

Investigation baseline: `uv run pytest -q tests/test_source_series_usgs.py
 tests/test_usgs_nwis_source_claims.py tests/test_usgs_nwis_public_routes.py` passed
45 tests. This is baseline evidence, not validation of the future implementation.
