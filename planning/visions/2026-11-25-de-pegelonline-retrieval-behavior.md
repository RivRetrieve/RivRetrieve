# Germany PEGELONLINE (`de_pegelonline`) — retrieval behavior

Associated issue:
[#1019](https://github.com/RivRetrieve/RivRetrieve/issues/1019)
("PEGELONLINE provider port: 4. Retrieval behavior"). Executing and
verifying this vision completes #1019 only; it does not by itself deliver
provider integration ([#1020](https://github.com/RivRetrieve/RivRetrieve/issues/1020)).

Builds on the merged step-1 vision
([`2026-11-24-de-pegelonline-source-scope-and-access.md`](2026-11-24-de-pegelonline-source-scope-and-access.md),
#1025/#1030), step-2 vision
([`2026-11-24-de-pegelonline-station-catalogue-and-metadata.md`](2026-11-24-de-pegelonline-station-catalogue-and-metadata.md),
#1031/#1042), and step-3 vision
([`2026-11-25-de-pegelonline-series-identity-and-physical-meaning.md`](2026-11-25-de-pegelonline-series-identity-and-physical-meaning.md),
#1046/#1047), all already implemented on `port/de-pegelonline` (catalogue
builder merged via #1041; `series.py`/`annotations.py` merged via #1047).
`port/de-pegelonline` is currently level with `main` (no further sync
needed before this step). The primary research record is issue
[#874](https://github.com/RivRetrieve/RivRetrieve/issues/874) (live-verified
2026-11-17) plus the prior steps' grills; this vision does not reproduce
that evidence beyond what's needed to act.

## Outcome

Give `de_pegelonline` a `fetch.py` and the supporting `config.py`
(`ProviderConfig`/`ProductConfig`/`SourceCoordinates`, following
`ch_foen/official_config.py`'s shape) it needs to be independently
testable — tests can call `fetch(...)` directly with a `ProviderConfig`
built in the test, the way this codebase already tests retrieval logic
ahead of full provider wiring. This builds correct, explicit bounded
requests to PEGELONLINE's REST API v2 `measurements.json` endpoint per
station × product × rendered window, and maps every response — real data,
rolling-retention-expired emptiness, and genuine failure — to the right
outcome without silently losing or corrupting data.

**Assembling `declaration.py` (the `LiveStages` `ProviderDeclaration`) is
explicitly out of scope here — leave it entirely to #1020.** Per
`docs/maintenance/provider-ports.md`'s own step 4/step 5 boundary and
issue #1020's own body (which lists declaring `LiveStages` as its work),
and matching the precedent in this exact codebase (`au_bom`'s
`declaration.py` was created at its catalogue step as `CatalogueOnly` and
only flipped to `LiveStages` in a later, separate step-5 commit): this
step produces `fetch.py`/`config.py` for #1020 to wire into a
`ProviderDeclaration` later, not the declaration itself.

Everything below resolves to already-settled facts from steps 1-3 or to
direct engine/precedent mechanics; this step is routine engineering, not a
design decision, and the vision below is deliberately short.

## Request construction — explicit window, correct offset, `.json` only

- Always pass explicit `start` and `end` as ISO-8601 with a UTC offset
  (e.g. `2026-11-01T00:00:00+01:00`, URL-encoding `+` as `%2B`) on
  `/stations/{uuid}/{shortname}/measurements.json?start=...&end=...`.
  **Never omit `start`** — PEGELONLINE silently truncates to the last 10
  days when it's absent (`Standardzeitraum`), the exact bug #874 confirmed
  in the `wetterdienst` Python adapter and the reason this is called out
  explicitly rather than left as an unstated assumption.
- Address stations only by their stable `uuid` (not station number or
  short name) and timeseries only by `shortname` (`W`/`Q`/`WT`/`TRM`/`TRM_WT`),
  consistent with the catalogue's `station_id`/`native_id`.
- Parse only `measurements.json`. Never `measurements.csv` — it uses
  semicolon delimiters, German decimal commas, and naive local timestamps
  that produce duplicate indistinguishable rows across the October DST
  fallback hour (live-verified by #874). `.json` has none of these defects.
- Build the offset with a DST-aware `Europe/Berlin` conversion of the
  engine-rendered UTC window bounds (`RenderedWindow.bounds: FetchWindow`),
  not a fixed offset — PEGELONLINE's own documented example alternates
  `+02:00`/`+01:00` across a single 31-day window that crosses the
  October DST transition. The engine's `ZoneValue` already accepts IANA
  zone names (`ZoneValue("Europe/Berlin")`, `src/rivretrieve/_internal/engine.py`)
  for declarative/validation purposes, but no shared engine mechanism
  renders a localized offset string anywhere in `window_planning.py` /
  `window_acquisition.py` — every existing provider's `ProviderConfig.zone`
  is a fixed value: `"+00:00"` (`ch_foen`, `lt_lhmt`, and others),
  `"unknown"` (`at_ehyd`, and others), or a fixed non-UTC offset
  (`au_bom`'s `"+10:00"`) — never a real IANA zone name that would need
  DST-aware rendering. `de_pegelonline` would be the first provider to need
  genuine DST-aware local-offset construction; do it in `fetch.py` itself, the same way
  `ch_foen/official_fetch.py`'s `_acquire` reads `window.bounds` directly
  rather than relying on the generic ISO-`Z` rendering — there is no
  existing helper to reuse, only the pattern of reading raw bounds
  yourself.

## No pre-clipping; `HTTP 200 []` means rolling retention, not inactivity

PEGELONLINE retains only a rolling ~31-day buffer per series; a request for
an older window returns `HTTP 200` with an empty array `[]`, not an error.
Do not pre-clip or special-case this: follow `ch_foen`'s same rolling-
retention non-decision (its `_acquire` has no retention-bounds concept at
all) and let an out-of-buffer request simply come back empty, mapped to
`OutcomeStatus.EMPTY`. The shared engine has no "source retention bounds"
concept to hook into even if this vision wanted one.

## One independent acquisition per station × product × window — no sharing, no pagination

Each of the five products lives at its own separate URL per station; there
is nothing to decode jointly. Follow `ch_foen`'s independent per-call loop
shape (`fetch()` iterating `stations × products × rendered_windows`,
delegating each call to `acquire_window`), not `lt_lhmt`'s shared-bytes
pattern (`lt_lhmt`'s two products genuinely co-publish in one HTTP
response; `de_pegelonline`'s do not).

No pagination helper (`page_acquisition.py`'s `acquire_pages`) is needed.
Per #874's live measurement, the worst case — a full 31-day window at
1-minute cadence — is at most ~44,640 JSON rows (~2.2 MB uncompressed, ~200
KB gzipped), comfortably one response. PEGELONLINE's REST API v2 documents
no row cap at all (unlike `ch_foen`'s GraphQL endpoint, which caps at
10,000 rows and requires `WindowResponseMeaning.OVERFLOW` signaling);
`de_pegelonline`'s `fetch()` should always report
`WindowResponseMeaning.COMPLETE` and never attempt overflow subdivision.

## No rate limit, no special cache handling

PEGELONLINE's own documentation states no API key, no registration, and no
hard server-side rate cap (confirmed live by #874). There is also no
`ProviderRateLimit`-style declaration mechanism anywhere in the engine yet
for any provider to use (the only related effort is issue #698; its
implementation, PR #923, is still open and unmerged on its own branch) —
so there is nothing to declare here,
consistent with every existing provider. Pass no `cache: CacheConfig` in
`config()` (`None`, matching `ch_foen`'s default) — `de_pegelonline` is a
rolling live source with no compiled store, and standard engine-level
response caching already benefits users correctly since `DL-DE->Zero-2.0`
imposes no cache-retention restriction.

Conditional `GET` (`ETag`/`If-None-Match`, `Cache-Control: max-age`) is
documented as *supported* by PEGELONLINE but not required — treat it as an
optional future enhancement, not part of this step's scope.

## Error-to-outcome mapping — do not copy `lt_lhmt`'s `404` mapping

`lt_lhmt` maps its own archive route's `404` to `SourceResponseMeaning.NO_OBSERVATIONS`
via `http_response_meaning()`'s `declared_status_meanings`
(`src/rivretrieve/_internal/source_acquisition.py`). **Do not do this for
`de_pegelonline`.** The catalogue built in step 2 (#1017/#1041) already
declares, in advance, which station × product pairs are available
(`StationProductCatalog.availability`). An unexpected `404` or `400` on a
pair the catalogue says is available means the catalogue and the live
service disagree — a real contract problem that should surface loudly as
`OutcomeStatus.FAILED` through the ordinary `TransportFailure` path, not get
silently absorbed as emptiness the way a genuine `HTTP 200 []`
rolling-retention response does. Declare no special status-code meanings at
all; let `4xx`/`5xx` responses fail normally.

## Explicitly out of scope / excluded

- Assembling `declaration.py` (the `LiveStages` `ProviderDeclaration`),
  registering `de_pegelonline` into `provider_manifest.py`'s
  `BUILTIN_PROVIDER_IDS`, and any user-facing documentation are all
  [#1020](https://github.com/RivRetrieve/RivRetrieve/issues/1020)'s job, not
  this vision's — this step only needs `fetch()`/`config()` locally
  constructible and testable by calling them directly in tests, not wired
  into a `ProviderDeclaration` or the public provider list.
- The undocumented `/gast/download/prepare` async ZIP archive
  (`2000-01-01+` historical `W`/`Q`) stays out of scope, as already decided
  in step 1 — this vision targets REST API v2 only.
- Conditional `GET` (`ETag`/`If-None-Match`) support, per above — optional,
  not required for correctness.
- Anything about *which* quantity/unit/frequency/vertical-reference a
  series carries is already settled by step 3; this vision does not revisit
  `PhysicalFacts` construction, only how bytes get fetched and classified.

## Completion evidence and boundaries

Verify request construction (explicit `start`/`end`, correct `+01:00`/
`+02:00` offset across a real DST boundary if feasible, `.json`-only) and
response-outcome mapping (`EMPTY` for out-of-buffer windows, `FAILED` for
unexpected `4xx`/`5xx`, `SUCCESS` for real data) against a fresh live fetch,
not just recorded fixtures, per the provider-port guide's step 4. Continue
the private research record
(`research/de-pegelonline-source-access.md` in
[verification-evidence](https://github.com/RivRetrieve/verification-evidence))
rather than starting a parallel history. Run
`uv run pytest tests/test_de_pegelonline_*.py --logic-only` plus the full
suite before calling this done, and confirm no regression in the
already-merged catalogue and series tests.
