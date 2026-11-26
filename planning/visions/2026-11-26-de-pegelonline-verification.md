# Germany PEGELONLINE (`de_pegelonline`) — verification

Associated issue:
[#1021](https://github.com/RivRetrieve/RivRetrieve/issues/1021)
("PEGELONLINE provider port: 6. Verification"). Executing and verifying this
vision completes #1021 only; it does not deliver user documentation
([#1022](https://github.com/RivRetrieve/RivRetrieve/issues/1022)).

Builds on step 5 ([#1020](https://github.com/RivRetrieve/RivRetrieve/pull/1077),
merged into `port/de-pegelonline`): `de_pegelonline` is now a fully
registered built-in provider, with a real packaged catalogue committed under
`src/rivretrieve/_internal/providers/de_pegelonline/catalogue/`, built against
the genuine `de_pegelonline-2026-11-25-v1` archive collection in
`RivRetrieve/verification-evidence` (archive revision
`2e0183a25e36ee4365453fd1d263282c678353b7`). The primary research record is
issue [#874](https://github.com/RivRetrieve/RivRetrieve/issues/874).

## Outcome

Evidence that the shipped `de_pegelonline` code behaves correctly and that
its adopted source meanings are correct, per [step 6 of the provider-port
guide](../../docs/maintenance/provider-ports.md#6-verification) — not new
functionality. Follow the [testing](../../docs/maintenance/testing.md) and
[evidence](../../docs/maintenance/evidence.md) guides throughout.

## The CAMELS-style comparison is already waived — do not attempt it

Issue #1021 itself settles this: no suitable published observational dataset
(CAMELS-DE, GRDC/Caravan-GRDC, LamaH-CE) overlaps PEGELONLINE's rolling
~31-day live window; all of them end years earlier. This was confirmed with
the maintainer, who will spot-check live values manually instead. Do not
build an automated bounded comparison. Record this absence and its reason
through the existing evidence process (a short research note in
`verification-evidence`, consistent with the existing
`research/de-pegelonline-source-access.md` note from step 1) — that absence
alone does not block this step, per the guide's own text.

## What remains in scope

### 1. Genuine recorded-interaction verification

Catalogue lineage is already real (step 5) and distribution contents are
already generically covered (`tests/test_packaging_carries_catalogues.py`
passes for all 21 built-in providers). What's missing is genuine
source-backed retrieval evidence: today, `tests/test_de_pegelonline_fetch.py`
only exercises `fetch.py` against hand-built synthetic stub responses, not a
single genuine recorded HTTP interaction. No recording files exist yet under
`tests/test_data/` beyond the catalogue fixture and the terms-of-use page.

Capture genuine HTTP interactions from the real transport against PEGELONLINE's
live `/stations/{uuid}/{shortname}/measurements.json` route (see
`fetch.py`'s module docstring: no pagination, no shared route across
products, explicit DST-aware `start`/`end` instants). Follow the established
technique (`au_bom` #648, `fi_syke` #758): **dry-run `fetch()` first** with a
param-recording stub transport to learn the exact request shape the shared
engine actually issues (window padding, timestamp rendering), *then* capture
genuine responses matching that shape. Capturing against a guessed shape
produces real but unreplayable recordings — exactly the mistake au_bom's own
vision names and had to redo.

Target roughly 8–10 genuine captures, covering:

- at least one successful capture per product (`W`, `Q`, `WT`, `TRM`,
  `TRM_WT`) across at least two distinct stations each, so no capture is
  accidentally station-specific;
- the already-observed empty-result case (`TRM_WT` at SCHWABELWEIS returned
  0 rows, `status=empty`, during #1020's manual verification — not a wiring
  problem, a genuine case worth a permanent recorded-replay test);
- one deliberate no-match / out-of-range window, to exercise a clean
  no-data path.

This is a target, not a rigid count — adjust if a genuinely informative case
needs one more capture, or if two products turn out to share one informative
edge case.

Register the captures as a new `verification-evidence` collection (same
`archive intake`/`archive publish` process used for
`de_pegelonline-2026-11-25-v1` in step 5), then write one new test file
(e.g. `tests/test_de_pegelonline_observations.py`, naming is yours) replaying
them through `rr.find`/`rr.pick`/`rr.fetch`: check identities, timestamps and
values together, per the guide. Confirm both `uv run pytest --logic-only`
and the private archive's own `verify.py` controlled run pass, as `au_bom`
and `fi_syke`'s own step-6 commits both did.

Fold a cache-reuse check into this new test rather than building a separate
dedicated cache-roundtrip test file: `lt_lhmt` and `fi_syke` (de_pegelonline's
closest architectural siblings) have no dedicated cache test at all, while
`at_ehyd`/`br_ana`/`fr_hubeau` fold one `cache="refresh"` then `cache="reuse"`
assertion into their own `_annotations.py` test — there is no single
established pattern requiring a dedicated file, and the recorded-replay test
is the natural place to exercise it once.

### 2. Extend the all-provider offline-rebuild test

Extend `test_native_composition_root_rebuilds_committed_artifacts_without_network`
(`tests/test_catalogue_origin_certification.py`) to cover `de_pegelonline`
now, rather than deferring it the way `au_bom`/`fi_syke` deferred it at their
own step 6. Those two deferrals were each forced by a genuine, named blocker
(no reviewed evidence-repo selection file with real provenance fact-bindings
existed yet) — not a default choice, and `de_pegelonline` does not have that
blocker: it already has a real archive-backed `provenance.json`, matching
`lt_lhmt`'s exact lighter pattern (no provider-specific `selection.json`).

`lt_lhmt`'s own parametrize entry is the direct template
(`tests/test_catalogue_origin_certification.py`, in the
`test_native_composition_root_rebuilds_committed_artifacts_without_network`
parametrize list):

```python
pytest.param(
    "lt_lhmt",
    marks=pytest.mark.governing(
        *_catalogue_recording_paths("lt_lhmt"),
        "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
        "tests/test_data/lt_lhmt_terms_licence.html",
    ),
),
```

The analogous `de_pegelonline` entry is expected to be exactly this shape
(`_catalogue_recording_paths("de_pegelonline")` auto-derives from the already
real `provenance.json`). `lt_lhmt` is not in the test function's few
provider-special-cased branches (`br_ana`, or the
`{ar_ina, at_ehyd, ch_foen, co_ideam, dk_vanda, pe_senamhi}` group) — it runs
through the shared default path, and `de_pegelonline` is expected to as well,
since it follows the same build shape. This was verified structurally
(reading the test's requirements and code paths) but not yet by actually
running it; if it turns out to need genuinely new archive-side design work,
as happened for `au_bom`, name that plainly and defer it rather than forcing
it or silently skipping it.

The exact insertion point in the parametrize list does not need to match
`BUILTIN_PROVIDER_IDS`'s alphabetical convention — that list is ordered by
historical port date, not alphabetically; place the new entry wherever is
convenient, near `lt_lhmt`'s.

## `TRM`/`TRM_WT` are not `variant`s of `W`/`WT` — established context, not a decision to revisit

`TRM`/`TRM_WT` are PEGELONLINE's scheduled ("Terminwerte") reading variants of
`W`/`WT`: confirmed from the native fixture, `W`/`WT` report on a fixed
continuous interval (15 minutes at most stations) while `TRM`/`TRM_WT`'s own
`equidistance` is `None` at every station — no regular interval at all, read
at scheduled appointment times instead. This is why they are separate
`product_id`s rather than a `variant` of `W`/`WT`: RivRetrieve's `variant`
mechanism (see `docs/usage.md`'s Brazil `bruto`/`consistido` example) is for
genuinely parallel versions of the *same* temporal structure, not a
structurally different one. This mirrors established precedent
(`ba_fhmzbih`, `th_thaiwater`, `fi_syke`'s `_reported`-suffixed products,
for the same underlying reason). This context may be useful when writing
recorded-replay test descriptions or the research-record note; it is settled
background, not something to redesign.

## Explicitly out of scope / excluded

- The automated CAMELS-style bounded comparison (waived, see above).
- User documentation (#1022) — separate, later step.
- Any change to `de_pegelonline`'s `fetch.py`/`parse.py`/`generate_catalogue.py`
  behavior. This step verifies existing behavior; if a genuine bug is found,
  name it and raise it rather than silently fixing it inside this step's PR,
  unless it's trivial and directly blocks writing a correct test.

## Completion evidence and boundaries

- A new `verification-evidence` collection registered and merged, containing
  the genuine captures.
- A new recorded-replay test file passing under both `uv run pytest
  --logic-only` and the private archive's `verify.py`.
- `test_native_composition_root_rebuilds_committed_artifacts_without_network`
  extended to cover `de_pegelonline` and passing under `verify.py` — or, if a
  genuine blocker is found, explicitly named and deferred with the reason
  recorded, matching `au_bom`/`fi_syke`'s own precedent for naming (not
  silently skipping) a deferred gap.
- A short research-record note (in `verification-evidence`) recording the
  CAMELS-absence finding and its reasoning.
- Full `uv run pytest --logic-only` run, reported alongside the PR.
