# Australia BoM verification

Verify the integrated Australia BoM provider (`au_bom`) against genuine
retained source evidence and record an external hydrological cross-check.
Delivering this vision and its retained evidence completes
[Effort #648](https://github.com/RivRetrieve/RivRetrieve/issues/648) under
[Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334);
publishing this vision alone does not complete the Effort.

Work targets `port/au-bom` and leaves `main` unchanged.
[Effort #649](https://github.com/RivRetrieve/RivRetrieve/issues/649) delivers
the dedicated user documentation (`docs/providers/au_bom.md`).
[Effort #650](https://github.com/RivRetrieve/RivRetrieve/issues/650) covers
final review and merge into `main` once both #648 and #649 are complete.

## Verify the delivered scope

Steps [#643](https://github.com/RivRetrieve/RivRetrieve/issues/643) through
[#647](https://github.com/RivRetrieve/RivRetrieve/issues/647) are delivered on
`port/au-bom`: offline discovery exposes 8,120 river-gauge stations across 18
admitted products (discharge, stage, water temperature; `24HR`/`09HR` daily
means and hourly/monthly/yearly aggregates); `declaration.py` wires
`LiveStages` (`required_credentials=()`) across a shared per-station
`getTimeseriesList` lookup and per-product `getTimeseriesValues` calls, with
a station's duplicate `ts_id` for one product surfaced as two distinct
`series_id`, never picked between.

This step retains new genuine HTTP evidence covering the retrieval edge
cases #646 and #647 already designed for, and replays it through the public
`rr.find`/`rr.pick`/`rr.fetch` surface — closing the gap between "designed
for" and "verified against a real response."

## Retained evidence

Published to the private archive as collection
`au_bom-verification-2026-11-04-v2` (GitHub release `433867288`; see
[verification-evidence#58](https://github.com/RivRetrieve/verification-evidence/pull/58)):
10 genuine, unauthenticated `GET` requests against BoM's KiWIS endpoint, using
the exact production request shapes `fetch.py` builds, retained with full
observation-value bodies (20 members: 10 bodies + 10 receipts):

- A shared `getTimeseriesList` prerequisite at station 410730, resolving
  discharge/stage/temperature `ts_id` in one call, plus an ordinary
  successful stage fetch (quality-A) and a discharge fetch where every row
  carries `quality-E` (confirms the `source.quality_code` issue path has a
  genuine, non-synthetic trigger).
- A `getTimeseriesList` at station 138020A, confirming it carries discharge
  and stage but no water-temperature series (the genuine `NO_MATCH`
  witness), plus a comma-joined duplicate `ts_id` fetch (`470345010`,
  `381776010`): one `ts_id` returns zero rows, the other returns rows
  including three genuine published nulls (`Quality Code` `-1`, `Quality
  Code Name` `null`) — the duplicate-identity design verified against a real
  response, not a hand-built fixture.
- A genuine HTTP 500 `InvalidParameterValue` response for a nonexistent
  `ts_id`, and a genuine HTTP 200 explicit zero-row response for a window
  entirely in the future (confirming BoM signals "no data" distinctly from
  "request failed").
- A `getTimeseriesList` and both admitted discharge daily-mean series at
  station 401203, retained for the external cross-check below.

**A real correction made during this step:** the engine pads every
requested fetch window by two days on each side and, for `Daily`-semantics
products, first snaps the requested bounds to day boundaries
(`src/rivretrieve/_internal/driver.py`'s `_FETCH_WINDOW_PADDING`). An initial
capture pass (`au_bom-verification-2026-11-04-v1`) used hand-chosen, clean
window bounds that did not match this real shape, discovered while writing
`tests/test_au_bom_recorded_public.py` and diffing its actual request
parameters against the retained receipts — genuine bytes, but unreplayable
through the public API. Fixed by dry-running the real `fetch()` code path
with a parameter-recording stub transport to determine the exact `from`/`to`
strings first, then re-capturing live against those exact windows
(`v2`, the collection actually bound here). `v1` remains published (releases
are not deleted) but is not referenced by any test.

**A real gap closed, not newly created by this step:** two collections
Effort #644 already published (`au_bom-catalogue-2026-11-02-v1`,
`au_bom-catalogue-native-2026-11-03-v1`) were never registered in the
private archive's `inventory/collections.json` or `archive/test_bindings.py`,
so `tests/source/test_au_bom_catalogue.py` (already written in #644) could
not run under the governed coordinator. Both are now registered alongside
the new verification collection.

## Public recorded replay

`tests/test_au_bom_recorded_public.py` (new), mirroring `at_ehyd`'s
`tests/test_at_ehyd_recorded_public.py`: replays each retained capture
through a stub `discovery.HttpClient`, asserting the live request's
scheme/host/path/params match the retained receipt before returning the
genuine bytes, then checking `rr.fetch`'s output against those bytes. Covers
unit conversion (stage, no-op), duplicate-`ts_id` split with real published
nulls, the quality-code issue path, `NO_MATCH`, an explicit empty window,
and a values-call transport failure (synthetic `getTimeseriesList`
prerequisite routing to the genuine HTTP 500 body — documented inline as the
one deliberately non-genuine piece, since no real station resolves a
product to that `ts_id`).

The private side (`verification-evidence`) adds `verification/au_bom/retrieval.py`
(`check_retrieval_receipt`, mirroring `at_ehyd`'s shape for BoM's two route
kinds) and `tests/source/test_au_bom_retrieval.py`, certifying every retained
receipt and the same scenarios independently of the public parser.

## External cross-check against CAMELS-AUS v2

CAMELS-AUS v2 (Fowler et al., University of Melbourne) publishes daily
streamflow for 561 Australian catchments, sourced from BoM's own Hydrologic
Reference Stations programme and two further academic datasets. 533 of its
561 station IDs exist in `au_bom`'s own catalogue. The repository owner
provided a local copy for this comparison; it was not downloaded by this
session and is not retained in either repository.

Station 401203, 2018-06-15, quality code `A` in CAMELS-AUS: `1177.2` ML/day,
i.e. `13.625` m3/s. Live: BoM's `DMQaQc.Merged.DailyMean.09HR` series (9am-
to-9am) matches exactly; its `DMQaQc.Merged.DailyMean.24HR` sibling
(midnight-to-midnight) gives `17.955` m3/s — a different value, not an
approximation of the same day. This is a genuine, independently sourced
confirmation that BoM's `09HR` series aligns with the national
hydrological-day convention CAMELS-AUS uses, and a concrete illustration of
why the `24HR`/`09HR` selection ambiguity #647 already flagged matters: the
two series are not interchangeable, and #649's documentation should say so
plainly. It does not change #645's `PhysicalFacts` (`day_definition` remains
deliberately unestablished there).

## A named gap, deferred rather than attempted here

`tests/test_catalogue_origin_certification.py`'s
`test_native_composition_root_rebuilds_committed_artifacts_without_network`
does not yet cover `au_bom`: closing it requires a CLI `main()` on
`generate_catalogue.py` (every other enrolled provider has one) and, more
substantially, a reviewed evidence-repo selection file
(`maintenance/catalogue/au_bom/official/catalogue.json`, referenced by
`read_catalogue_sources()` but never created) supplying real provenance
fact-bindings and license/citation statements — design work on the same
order as `ch_foen`'s `selection.json`, not a CLI wrapper. The catalogue that
already shipped in #644 was built once, correctly, through an uncommitted
ad hoc script; reconstructing a reviewed, reproducible path for it is real
new work with meaningful risk of a wrong fact-binding if rushed. Deferred to
a dedicated follow-up rather than attempted inside this step.

## Also found, left to a maintainer

`tests/test_at_ehyd_retrieval_bindings.py::test_at_ehyd_retrieval_bindings_pair_bodies_and_receipts_without_whole_root_aliases`
fails on `verification-evidence`'s `main` already, unrelated to this Effort:
it predates PR #57's `at_ehyd-verification-2026-11-03-v1` collection, which
added members under the same binding `requirement` string this older unit
test doesn't account for. Recorded in `research/au-bom-source-access.md`.

## Verification

- `uv run ruff check src tests` and `uv run ty check src` clean.
- `uv run pytest --logic-only`: no regressions (the new recorded-replay test
  is correctly deselected without a retained evidence root).
- `tests/test_au_bom_recorded_public.py` passes against the genuine v2
  captures via `RIVRETRIEVE_TEST_EVIDENCE_ROOT`.
- `verification-evidence`: `archive validate`/`archive fetch` confirm the
  three `au_bom` collections byte-for-byte; the private test suite passes
  except the one named pre-existing, unrelated failure above.

Post a concise scope-and-delivery update on #648.
