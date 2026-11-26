# Estonia `ee_est`: final review fixes and merge into `main`

Resolve every finding in Thiago's
[final review of `port/ee-est` at `95b8c537`](https://github.com/RivRetrieve/RivRetrieve/issues/947#issuecomment-7189952052),
bring the branch up to date with the current `main`, review the complete
result again, and merge it into `main` once Thiago explicitly approves in #947.
The provider's data is already correct: hand checks against Ilmateenistus and
EstModel passed, and every claim in the review guide held up live. This vision
covers the remaining documentation, inventory, multi-code and test-quality
gaps, plus the integration with `main`.

Delivering this vision, including the approved merge into `main`, completes
[Effort #947](https://github.com/RivRetrieve/RivRetrieve/issues/947) under
[Program #352](https://github.com/RivRetrieve/RivRetrieve/issues/352). Steps 1
through 7 (#940 to #946) are closed. Their evidence is linked from the
[review guide](https://github.com/RivRetrieve/RivRetrieve/issues/947#issuecomment-7106270699).

## Documentation fixes

Apply these in `docs/providers/ee_est.md`, and in the `qualityFlag` field
description in `src/rivretrieve/_internal/providers/ee_est/annotations.py`.

- **Daily vs hourly discharge.** Report the measured difference as a dated
  observation, **numbers only**. Each daily EstModel `Q` value was compared with
  the average of that day's hourly `Äravool avg` values at 8 stations for
  September 2025. The median difference per station was 3.5 to 5.6 %, with up to
  13 % on single days; Ahja in June 2025 reached −16 % / +11 %. Stage (`H` vs
  `WL`) agreed within about 1 %. Do **not** suggest a cause, give advice on mixing
  `P1D` and `PT1H`, or name a preferred series. Date the statement by the
  review (comparison reported 2026-11-26 for the September 2025 and June 2025
  data). Quote the figures as the review gives them. The review does not list
  the 8 stations or define the sign of "−16 % / +11 %". Do not invent either:
  ask in #947 if the guide needs them, or leave them out.
- **Native series codes.** `variant` is null on every `ee_est` series, so
  `rr.pick(sel, variant="Q:MEAN")` matches nothing. Rename the retrieval table's
  "Source field / `variant`" column to "Native series code". Show the full
  `published_id` form in the table. The prose around lines 133–135 already
  gives the examples `SJA8821000:Q:MEAN` and `41061:Äravool avg`; keep them.
  State plainly that `variant` is null for `ee_est`.
  This header change applies only to `ee_est`. The template in
  `docs/maintenance/provider-ports.md` and the other provider guides stay as
  they are; two guides on `main` already use their own column name.
- **Selection example.** Replace the example that filters `published_id` by
  suffix and copies a `series_id` with ordinary filters, for example
  `rr.pick(all_discharge, frequency="PT1H", statistic="mean")`.
- **`qualityFlag`.** State that null does not mean checked. State that hourly
  `f_hydroseire` series carry no annotation at all, even though they are
  operational telemetry. Describe the observed pattern as a dated observation
  (observed 2026-11-26):
  in the full daily histories at Ahja and Tartu, every row up to 2025-12-31 is
  null, 2026 `Q`/`H` rows are `UNCHECKED`, 2026 `T` rows are null, and
  `BELOW_LOQ`/`OUTLIER` never appear. The current `annotations.py` wording
  ("through the end of the last completed calendar year … pending annual WISKI
  verification") reads as a permanent rule and would become wrong if a year's
  review is late. Rephrase it the same dated way.
- **Wording.** A 365-day hourly span has at most **8,760** rows; 8,784 is the
  366-day figure. Replace "RivRetrieve applies polite sequential spacing". The
  provider relies on the shared transport policy, and a live burst of 24
  multi-decade calls returned only HTTP 200.

Keep `tests/test_ee_est_documentation.py` in agreement with the revised guide.

## Code fixes

### Inventory completeness after partial chunk failure

`fetch.py` currently marks a pair inventory `COMPLETE` over the whole requested
window once at least one chunk succeeds, even if other chunks failed. This
happens for both EstModel and `f_hydroseire` (around lines 529–556 and
660–686 at `95b8c537`). An inventory must not claim completeness for a window
that was not fully retrieved. Follow the `usgs_nwis` pattern
(`InventoryCompleteness.INCOMPLETE` when a failure occurred) and cover both APIs
with tests.

### Stations with several hourly `jaam_kood` codes

`f_seirejaamad.kood` can list several hourly codes for one station
(`SJA5524000` has `"41022; 41960"`). At the moment:

- the catalogue builder (`generate_catalogue.py`) keeps only the code that has
  data and raises an error if several codes have data;
- at runtime, `_select_active_jaam_kood` checks each code and picks the
  **first** one that has ever had rows;
- `41960` is never queried, yet the inventory reports the series list as
  complete. Live, `41960` currently has no rows. The recorded probe
  `fh-41960-probe-limit1` exists but is never used.

Settled behavior:

- Query **every** listed code. Each code that has data becomes **its own
  series**, with its own `published_id` (`<jaam_kood>:<aegrida_nimi>`), which
  matches the series identity that already exists. Do not combine codes into one
  series.
- "Listed" means every code in the station's `f_seirejaamad.kood`, not just the
  codes that had data when the catalogue was built. The catalogue keeps all
  listed codes (today it stores only one `jaam_kood` per station). At runtime,
  every listed code is checked. If a code without data at build time has data
  later, its series is reported at runtime as a newly discovered series. How
  the catalogue stores the codes, and how this runtime discovery fits the
  existing `known_series` / `_jaam_kood_from_known` path, is up to the
  implementer.
- The catalogue builder and the runtime follow **one shared rule**, so the
  "reject ambiguous codes" vs "first code with data" mismatch goes away.
- A pair inventory is `COMPLETE` only when every listed code was actually
  checked. Exercise `fh-41960-probe-limit1` to show that `41960` was checked and
  returned no rows. If the changed request no longer matches that recording,
  capture an equivalent one through the controlled recording path used for the
  existing `ee_est` recordings.
- If this changes the packaged catalogue representation or its contents,
  rebuild `ee_est/catalogue/` through the controlled
  `verify.py --catalogue-inputs` path and keep `source_series.json` /
  runtime `series_id` / `facts_id` parity.

### Value-based tests

Follow [`docs/maintenance/testing.md`](../../docs/maintenance/testing.md):
replay tests compare against independently read source values, and never
compute expectations with the code under test.

- Scope: every recorded replay test for `ee_est`, currently
  `tests/test_ee_est_retrieval_recorded.py`, `tests/test_ee_est_recorded_public.py`
  and `tests/test_ee_est_verification.py`, including the tests that go through
  public `rr.fetch` with retained responses rather than `ReplayTransport`. Each
  one checks handwritten
  `(time, value)` pairs read directly from the recorded response, not just row
  counts and first timestamps. Row-count checks may stay as extra checks.
- Together the pairs cover: `vaartus: null` rows, a negative gauge-zero stage
  (Räpina, `SJA4456000`), the hourly `cm -> m` conversion, a DST change on the
  UTC hourly timeline (the existing 2024 spring and autumn recordings for
  `41061` are enough), the record starts (1867 stage and 1922 discharge at
  Tartu `SJA7331000`, 1902 discharge at Vasknarva `SJA2718000`), and
  `UNCHECKED` `qualityFlag` rows. Use existing recordings where they cover a
  case. Capture any missing case through the controlled recording path.
- Write the expected `series_id` and `published_id` as literals. Do not build
  them with `source_series` / `source_series_identity`.

## Integration with `main`

At the time of writing, `main` is 47 commits ahead of `port/ee-est`. The new
commits include the `cl_dga` port (#1044), the `au_bom` `label_time` fix
(#1082) and the provider-port documentation change (#1085). A trial merge
conflicts in `README.md`, `tests/test_catalogue_origin_certification.py` and
`tests/test_station_metadata_packaging.py`.

- Land the fixes above on `port/ee-est` through a PR into `port/ee-est`.
- Then rebase `port/ee-est` onto the current `main`, keeping the branch linear
  as in the earlier syncs. Resolve the conflicts so that both `cl_dga` and
  `ee_est` are fully represented. Regenerate everything that depends on the
  provider set, which becomes **21 providers**: `tests/test_frequency.py`, the
  coverage map, generated reference tables and metadata tables, and the
  provider and country counts in `README.md` prose ("twenty different providers
  in nineteen countries" on `main`). Use the counts after regeneration.
- The rebase requires a force push to `port/ee-est`; use `--force-with-lease`.
- Open a PR from `port/ee-est` into `main`, and merge it with a **merge commit**
  (as #1044 was merged for `cl_dga`). Check that the PR text and merge payload
  contain no unintended closing keywords for issues other than #947.

## Final review and approval gate

After the rebase, the implementing agent performs a **full review** of the
complete branch, not only the fix diff:

- every finding in the final review is resolved as described here;
- the documentation, provider code, catalogue and tests are consistent with
  each other and with the merged `main`;
- all checks pass: `ruff format --check` and `ruff check` on
  `src tests scripts`, `ty check src`, `scripts/generate_reference.py --check`,
  `pytest --logic-only`, required CI, and a new controlled
  `verify.py --catalogue-inputs` acceptance receipt on the final rebased tip.
  Record the receipt in `RivRetrieve/verification-evidence` like the earlier
  `ee_est` receipts.

Post the review results in #947. **Do not merge into `main` until Thiago
explicitly approves there.** Earlier Effort completion, passing checks or this
vision do not authorize the merge by themselves. If anything changes after the
review (including changes Thiago asks for at approval time), re-run the checks
and record a new receipt on the new tip before merging. Once Thiago has
approved the final tip, the implementing agent performs the merge.

## Out of scope

- Changing provider behavior beyond the findings listed here.
- Explaining or reconciling the daily vs hourly discharge difference.
