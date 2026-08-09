# m1-s1 implementation plan: rename canonical published-record bounds atomically

## 1. Objective

In one merge-green change, rename the two canonical `StationProductCatalog` period-of-published-record columns from `start_date` and `end_date` to `published_record_start_date` and `published_record_end_date`. Make the canonical schema, every provider generator, all affected test data and assertions, ADR terminology, and all thirteen committed `station_products.parquet` artifacts agree atomically. The binary artifacts must be rewritten offline by renaming only those two columns in the already-committed frames; every row and every non-name value remains exactly unchanged.

## 2. Semantics to implement

1. `StationProductCatalog` has exactly these eight columns, in exactly this order and with exactly these Polars dtypes/nullability rules:

   ```text
   provider_id                    pl.Utf8             non-null
   station_id                     pl.Utf8             non-null
   product_id                     pl.Utf8             non-null
   availability                   AvailabilityDtype   non-null
   availability_reason            pl.Utf8             nullable
   published_record_start_date    pl.Date             nullable
   published_record_end_date      pl.Date             nullable
   last_catalogue_check            pl.Date             non-null
   ```

   The unique key remains exactly `("provider_id", "station_id", "product_id")`; availability values remain exactly `("available", "unavailable", "unknown")`. `start_date` and `end_date` are not aliases: neither bare name may remain in `STATION_PRODUCT_CATALOG_SCHEMA` or in a generated/packaged canonical station-product frame.

2. In each of the thirteen `generate_catalogue.py` modules listed in the write-set, change only the keys of canonical station-product row dictionaries from `"start_date"`/`"end_date"` to `"published_record_start_date"`/`"published_record_end_date"`. Keep each provider's existing source selection, availability, reason, dates, ordering, casts, validation, and `STATION_PRODUCT_CATALOG_SCHEMA.polars_schema` construction unchanged. In USGS, the local variables returned by `_matching_coverage` may remain `start_date` and `end_date`; their values must be emitted under the two new canonical keys. USGS published bounds must retain their actual dates.

3. Preserve provider vocabulary outside the canonical carrier. In particular, do **not** rename USGS `SERIES_ONLY_FIELDS` entries `begin_date` and `end_date`, `_matching_coverage`'s source-facing/local names, `tests/test_data/usgs_nwis_metadata_series.json`, or `usgs_nwis/catalogue/native.parquet`. Do **not** rename ThaiWater request query parameters `start_date`/`end_date`, or observation locals/error text `requested_start_date`/`requested_end_date` in the driver. These are not canonical catalogue fields.

4. Rewrite every committed `station_products.parquet` in the write-set by reading that exact existing artifact, applying a Polars two-column `rename`, and writing to the same path. Do not regenerate any canonical catalogue. The rewrite must preserve row order, row count, all values and nulls, both bound columns' `pl.Date` dtype and positions (positions 6 and 7 in one-based terms), and every `last_catalogue_check` value. This is mandatory because `br_ana` and `no_nve` have no committed `native.parquet`, their small fixtures contain only 4 and 3 stations while the packaged artifacts contain 52,145 and 44,001 rows, and their generators require unavailable network/credentials (ANA OAuth and `NVE_API_KEY`). More generally, `last_catalogue_check` derives from a caller-supplied `catalogue_date` defaulting to `date.today()` in six providers, so rerunning generators could replace a published value.

5. Use this one-off, repository-root command for the binary rewrite. It is intentionally not a tracked script. Its assertions are part of the implementation, not optional diagnostics:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 uv run python - <<'PY'
   from pathlib import Path

   import polars as pl
   import polars.testing as pl_testing

   providers_root = Path("src/rivretrieve/_internal/providers")
   expected_rows = {
       "ba_fhmzbih": 180,
       "br_ana": 52_145,
       "ca_eccc": 16_114,
       "ch_foen": 738,
       "cz_chmi": 4_155,
       "fr_hubeau": 33_139,
       "jp_mlit": 4_092,
       "lt_lhmt": 194,
       "no_nve": 44_001,
       "pl_imgw": 3_903,
       "th_thaiwater": 1_650,
       "usgs_nwis": 157_548,
       "za_dws": 8_715,
   }
   old_columns = (
       "provider_id",
       "station_id",
       "product_id",
       "availability",
       "availability_reason",
       "start_date",
       "end_date",
       "last_catalogue_check",
   )
   new_columns = (
       "provider_id",
       "station_id",
       "product_id",
       "availability",
       "availability_reason",
       "published_record_start_date",
       "published_record_end_date",
       "last_catalogue_check",
   )
   rename = {
       "start_date": "published_record_start_date",
       "end_date": "published_record_end_date",
   }

   for provider_id, row_count in expected_rows.items():
       path = providers_root / provider_id / "catalogue/station_products.parquet"
       before = pl.read_parquet(path)
       assert tuple(before.columns) == old_columns
       assert before.height == row_count
       assert before.schema["start_date"] == pl.Date
       assert before.schema["end_date"] == pl.Date
       renamed = before.rename(rename)
       assert tuple(renamed.columns) == new_columns
       renamed.write_parquet(path)
       after = pl.read_parquet(path)
       assert tuple(after.columns) == new_columns
       assert after.schema["published_record_start_date"] == pl.Date
       assert after.schema["published_record_end_date"] == pl.Date
       pl_testing.assert_frame_equal(
           after.rename({value: key for key, value in rename.items()}),
           before,
           check_exact=True,
       )
       print(provider_id, after.height)
   PY
   ```

   Expected output, verbatim and in order:

   ```text
   ba_fhmzbih 180
   br_ana 52145
   ca_eccc 16114
   ch_foen 738
   cz_chmi 4155
   fr_hubeau 33139
   jp_mlit 4092
   lt_lhmt 194
   no_nve 44001
   pl_imgw 3903
   th_thaiwater 1650
   usgs_nwis 157548
   za_dws 8715
   ```

6. Update ADR 0012's current canonical terminology at line 17 from `start_date` to `published_record_start_date`, without changing its source-native `begin_date`. Update ADR 0014's Croissant JSON example field name from `start_date` to `published_record_start_date`. Do not rewrite ADR 0015: its `stations.start_date`/station-level discussion records fields already removed from a different carrier and is historical design context.

7. `CONTEXT.md` is proven untouched: at the pinned ref it contains no `start_date`, `end_date`, or `published_record_*` occurrence, and the existing canonical term **Canonical column** already covers this vocabulary change. No new ADR is warranted; only the two current examples named by this step are aligned.

## 3. Write-set

Modify exactly the following tracked paths; create no tracked fixture or migration script.

- Canonical schema: `src/rivretrieve/_internal/catalogues/schemas.py` — rename the two `CatalogueColumn` names while preserving order, dtype, nullability, key, and enum.
- Provider row construction (same two canonical dictionary-key replacements in each):
  - `src/rivretrieve/_internal/providers/ba_fhmzbih/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/ca_eccc/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/cz_chmi/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/fr_hubeau/generate_catalogue.py` (both hydro and temperature row branches)
  - `src/rivretrieve/_internal/providers/jp_mlit/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/lt_lhmt/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/no_nve/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/pl_imgw/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/th_thaiwater/generate_catalogue.py`
  - `src/rivretrieve/_internal/providers/usgs_nwis/generate_catalogue.py` (output dictionary keys only; source `begin_date`/`end_date` stays)
  - `src/rivretrieve/_internal/providers/za_dws/generate_catalogue.py`
- Committed binary carriers, rewritten only with the value-preserving command above:
  - `src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/br_ana/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/ca_eccc/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/ch_foen/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/cz_chmi/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/fr_hubeau/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/jp_mlit/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/lt_lhmt/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/no_nve/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/pl_imgw/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/th_thaiwater/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/usgs_nwis/catalogue/station_products.parquet`
  - `src/rivretrieve/_internal/providers/za_dws/catalogue/station_products.parquet`
- Test carriers/assertions:
  - `tests/conftest.py` — rename both fields in all four `_station_products` rows and its explicit schema.
  - `tests/test_internal_catalogue_schemas.py` — rename both fields in `station_product_catalog_df`, invalid-availability input, exact column-order assertion, and dtype assertions; explicitly assert the two bare names are absent.
  - `tests/test_internal_packaged_catalogue_artifact.py` — rename both fields in `station_products_df` and duplicate-key overrides.
  - `tests/test_ch_foen_generate_catalogue.py` — rename the two null-count column accesses.
  - `tests/test_fr_hubeau_generate_catalogue.py` — rename expected row keys and replace the station-product digest pin.
  - `tests/test_pl_imgw_generate_catalogue.py` — rename expected row keys and replace its digest pin.
  - `tests/test_usgs_nwis_generate_catalogue.py` — rename only canonical expected/output accesses; keep source series fields and malformed-native `end_date` test unchanged.
  - `tests/test_za_dws_generate_catalogue.py` — rename expected row keys and replace its digest pin.
  - `tests/test_ba_fhmzbih_generate_catalogue.py`, `tests/test_br_ana_generate_catalogue.py`, `tests/test_jp_mlit_catalogue.py`, and `tests/test_no_nve_catalogue.py` — replace only their renamed-frame station-product content digest pins.
  - `tests/test_package.py` — retain the literal thirteen-provider loop and strengthen `test_all_packaged_catalogues_expose_exact_reduced_carriers` with the exact expected row counts, exact eight-column tuple, Date dtypes, bare-name absence, and bound non-null counts given below.
- Current terminology: `docs/adr/0012-a-catalogue-column-declares-its-origin.md` and `docs/adr/0014-catalogue-metadata-is-croissant.md` as specified above.

No on-disk file under `tests/test_data/` changes. `pr-body.md` is the sole untracked executor output and is governed by section 9, not part of the commit.

## 4. Existing assertions affected

Update these assertions explicitly:

- `tests/test_internal_catalogue_schemas.py::test_catalogue_schema_objects_define_expected_columns` expects the exact new eight-column tuple and explicitly rejects `start_date` and `end_date`; `test_catalogue_schema_objects_define_polars_dtypes` indexes both new names and expects `pl.Date`; `test_availability_accepts_allowed_enum_values` and `test_availability_rejects_invalid_value` use the renamed helper/input shapes but retain their outcomes.
- `tests/test_internal_packaged_catalogue_artifact.py::test_packaged_artifact_from_components_happy_path`, `test_packaged_artifact_from_path_happy_path`, and `test_packaged_artifact_duplicate_station_product_key_raises_corrupt` consume the renamed helper shape; exact frame equality and exception behavior remain unchanged.
- `tests/test_ch_foen_generate_catalogue.py::test_native_build_has_exact_projection_counts_dates_and_schemas` expects 738 nulls in each new bound column.
- `tests/test_fr_hubeau_generate_catalogue.py::test_committed_catalogue_matches_independent_projection_and_content_pins`, `tests/test_pl_imgw_generate_catalogue.py::test_native_build_matches_independent_exact_full_projections`, `tests/test_pl_imgw_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_complete_content`, `tests/test_usgs_nwis_generate_catalogue.py::test_station_product_matching_covers_absent_unique_duplicate_agreeing_blank_and_conflicting_series`, `tests/test_usgs_nwis_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_whole_content`, `tests/test_za_dws_generate_catalogue.py::test_native_build_matches_independent_exact_full_projections`, and `tests/test_za_dws_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_complete_content` use the new keys. Their values remain unchanged.
- Digest pins change in `tests/test_ba_fhmzbih_generate_catalogue.py::test_committed_canonical_artifact_content_digests_are_pinned`, `tests/test_br_ana_generate_catalogue.py::test_projected_national_artifacts_have_pinned_complete_content`, `tests/test_fr_hubeau_generate_catalogue.py::test_committed_catalogue_matches_independent_projection_and_content_pins`, `tests/test_jp_mlit_catalogue.py::test_committed_canonical_components_have_pinned_full_content`, `tests/test_no_nve_catalogue.py::test_projected_national_artifacts_have_pinned_complete_content`, `tests/test_pl_imgw_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_complete_content`, and `tests/test_za_dws_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_complete_content`. The USGS content digest assertion is deliberately unchanged because its helper hashes positional rows without column names.
- `tests/test_package.py::test_all_packaged_catalogues_expose_exact_reduced_carriers` (present at line 99 at the ref; schema equality is line 126 inside its literal thirteen-id tuple loop) is updated as described in the write-set. This assertion is why schema and all artifacts must co-land.

The following affected byte-determinism assertions require no source edit, but must pass after generator keys and artifacts co-land: `test_native_cli_is_offline_deterministic_and_matches_committed_artifacts` (ba_fhmzbih), `test_native_build_is_network_free_and_byte_deterministic` (ca_eccc), `test_native_build_matches_committed_catalogue_byte_for_byte` (ch_foen), `test_native_build_is_network_free_and_byte_deterministic` (cz_chmi), `test_native_cli_is_offline_byte_deterministic_and_preserves_native` (fr_hubeau), `test_native_cli_is_offline_and_byte_deterministic` (jp_mlit), `test_native_build_is_network_free_and_byte_deterministic` (lt_lhmt), `test_native_build_is_byte_identical_to_committed_artifacts` (pl_imgw), `test_fresh_build_matches_all_committed_artefact_bytes` (th_thaiwater), `test_native_build_is_network_free_and_byte_deterministic` (usgs_nwis), and `test_native_build_is_network_free_and_byte_deterministic` (za_dws), in their provider-named test files above.

Schema-following assertions in `tests/test_ba_fhmzbih_generate_catalogue.py::test_native_build_has_exact_counts_dates_and_schemas`, `tests/test_br_ana_generate_catalogue.py::test_fixture_build_uses_exact_reduced_carriers`, `tests/test_cz_chmi_generate_catalogue.py::test_committed_native_build_has_expected_counts_and_schema`, `tests/test_jp_mlit_catalogue.py::test_catalogue_validates_without_error`, `tests/test_no_nve_catalogue.py::test_fixture_build_uses_exact_reduced_carriers`, `tests/test_pl_imgw_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_complete_content`, and `tests/test_usgs_nwis_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_whole_content` are proven untouched in logic: they compare to the schema object and therefore follow its atomic rename.

`tests/test_internal_catalogue_reader.py::{test_catalogue_reader_station_products_returns_packaged_catalog_result,test_catalogue_reader_station_products_empty_sequence_matches_none,test_reader_preserves_polars_schema_after_empty_filter,test_catalogue_reader_live_station_products_warn_returns_empty_result_with_issue,test_catalogue_reader_live_station_products_ignore_returns_issue_without_warning}` are also proven untouched: they compare exact frames or schemas produced by the renamed `tests/conftest.py` helper and never index either old bound name. Other fixture consumers in discovery, registry, exit-criteria, and provider-handle tests filter identity/product fields or compare a frame to the same artifact; the full-suite gate proves them without changing their assertions.

Provider/module count, availability, origin-certification, and artifact-loading tests are unchanged in expected values. No existing expected exception text changes. In particular, `tests/test_usgs_nwis_generate_catalogue.py::test_native_build_rejects_malformed_series_alignment`, `tests/test_internal_driver.py`'s requested-window error assertion, and `tests/test_internal_window_planning.py`'s ThaiWater URLs intentionally retain `end_date`, `requested_start_date`/`requested_end_date`, and request `start_date`/`end_date` vocabulary.

## 5. Authored data

There are no new fixture files. All changed authored values are completely specified here.

The exact four-row rich carrier in `tests/conftest.py::_station_products` is:

```python
[
    {"provider_id": provider_id, "station_id": "station-1", "product_id": "level", "availability": "available", "availability_reason": None, "published_record_start_date": date(2020, 1, 1), "published_record_end_date": None, "last_catalogue_check": date(2026, 1, 1)},
    {"provider_id": provider_id, "station_id": "station-1", "product_id": "flow", "availability": "unknown", "availability_reason": "not_catalogued", "published_record_start_date": None, "published_record_end_date": None, "last_catalogue_check": date(2026, 1, 1)},
    {"provider_id": provider_id, "station_id": "station-2", "product_id": "level_hourly", "availability": "available", "availability_reason": None, "published_record_start_date": date(2021, 1, 1), "published_record_end_date": None, "last_catalogue_check": date(2026, 1, 1)},
    {"provider_id": provider_id, "station_id": "station-2", "product_id": "level_max", "availability": "unavailable", "availability_reason": "derived_not_supported", "published_record_start_date": None, "published_record_end_date": None, "last_catalogue_check": date(2026, 1, 1)},
]
```

With `rich=False`, only the first row exists. The explicit schema is the eight-column schema in section 2.

The exact three rows in `tests/test_internal_catalogue_schemas.py::station_product_catalog_df` retain:

```python
{
    "provider_id": ["synthetic", "synthetic", "synthetic"],
    "station_id": ["station-1", "station-1", "station-1"],
    "product_id": ["level", "flow", "temp"],
    "availability": ["available", "unavailable", "unknown"],
    "availability_reason": [None, "source gap", "unchecked"],
    "published_record_start_date": [date(2020, 1, 1), None, None],
    "published_record_end_date": [None, None, None],
    "last_catalogue_check": [date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1)],
}
```

Its invalid-availability row is exactly `synthetic / station-1 / level / retired / None / None / None / 2026-01-01`, with `pl.Enum(["available", "unavailable", "unknown", "retired"])`; only the two key names change. `tests/test_internal_packaged_catalogue_artifact.py::station_products_df` is exactly `synthetic / station-1 / level / available / None / 2020-01-01 / None / 2026-01-01`; its duplicate-key override repeats that row twice, including `[date(2020, 1, 1), date(2020, 1, 1)]` for `published_record_start_date` and `[None, None]` for `published_record_end_date`.

All non-USGS generator/independent-projection rows keep their existing provider/station/product/availability/reason/check values and set both renamed bounds to `None`. USGS's exact changed assertions for station `outcomes` are:

```text
discharge_daily_mean: availability="available", availability_reason=None, published_record_start_date=date(2001, 1, 2), published_record_end_date=date(2025, 3, 4)
discharge_instantaneous: published_record_start_date=date(2001, 1, 2), published_record_end_date=date(2025, 3, 4)
stage_daily_mean availability_reason: "Matching USGS source series states blank coverage dates"
stage_daily_max availability_reason: "Several matching USGS source series state conflicting coverage boundaries"
stage_daily_min: availability="unavailable", availability_reason="No matching USGS source series was published for this station-product", published_record_start_date=None, published_record_end_date=None
```

The exact `tests/test_package.py` expectation mapping is:

```python
{
    "ba_fhmzbih": (180, 0, 0),
    "br_ana": (52_145, 0, 0),
    "ca_eccc": (16_114, 0, 0),
    "ch_foen": (738, 0, 0),
    "cz_chmi": (4_155, 0, 0),
    "fr_hubeau": (33_139, 0, 0),
    "jp_mlit": (4_092, 0, 0),
    "lt_lhmt": (194, 0, 0),
    "no_nve": (44_001, 0, 0),
    "pl_imgw": (3_903, 0, 0),
    "th_thaiwater": (1_650, 0, 0),
    "usgs_nwis": (157_548, 57_450, 57_450),
    "za_dws": (8_715, 0, 0),
}
```

Each tuple is `(row_count, non_null_published_record_start_date_count, non_null_published_record_end_date_count)`. USGS bound extrema remain start `1857-02-01` through `2026-07-30` and end `1889-11-30` through `2026-08-01`. Exact unchanged `last_catalogue_check` values by provider order are `2026-08-02`, `2026-06-11`, `2026-08-02`, `2026-08-02`, `2026-08-02`, `2026-08-02`, `2026-08-02`, `2026-08-01`, `2026-06-03`, `2025-10-10`, `2026-08-02`, `2026-08-02`, `2026-08-02`.

Replace station-product content pins with exactly:

```text
ba_fhmzbih  8fe32129705d9c51e78b5379e2f9afede4d5c413677fc55e3df7c2c1594387f5
br_ana      3e221ca0c924b3423906675ae1851b8d6930be9224b9a42022184fbf3ded8674
fr_hubeau   456d072fe8310c8a00095da8dc053c8dc612e234e15d575bc3a57925503ddca3
jp_mlit     5390d653ae806e5dfe182fe484ba78c8b5b66d44eb1a6195f44737865cd5ab8c
no_nve      8322163f4875a72cd476e8a17a3c4fee7e4741d3eb368558877264ae06145299
pl_imgw     b03363ee1104062b8cc3a166873ac5c4ab54b19bb4abd49f20a74427f67ba865
za_dws      8b481dfdb358de66749239f622b567a4386423cd2849651735f1d54b1482a02f
```

The USGS pin stays exactly `a8ac1cc876ef1b2aac04fc09141eb9b0e5e59df3c767f7bddfdcb27fc59152d8`. No expected error text is authored or changed by this step.

## 6. Acceptance criteria

Run these focused observations before the full gates:

1. `git grep -n -E '"start_date"|"end_date"' -- src/rivretrieve/_internal/catalogues/schemas.py src/rivretrieve/_internal/providers/*/generate_catalogue.py tests` must show no old names in canonical schema/row/expected dictionaries. Every remaining hit must be one of the explicitly protected USGS native/source fields, ThaiWater URL query parameters, requested-window locals/error text, or an unrelated observation test. Inspect every hit; do not blanket-replace it.
2. `git diff --name-only` must contain every tracked path in section 3 and no other tracked path. In particular, all thirteen `station_products.parquet` paths must appear, and no `native.parquet`, `tests/test_data/*`, `CONTEXT.md`, ADR 0015, `pyproject.toml`, `uv.lock`, version file, graph, vision, or review artifact may appear.
3. `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_internal_catalogue_schemas.py tests/test_internal_packaged_catalogue_artifact.py tests/test_package.py` must pass. Observe the exact new eight-column order, both bounds as `pl.Date`, no bare canonical field names, exact row/non-null counts from section 5, and successful schema-backed loading for all thirteen artifacts.
4. `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_usgs_nwis_generate_catalogue.py::test_station_product_matching_covers_absent_unique_duplicate_agreeing_blank_and_conflicting_series tests/test_usgs_nwis_generate_catalogue.py::test_committed_canonical_artifacts_have_pinned_whole_content` must pass, proving the USGS dates above survived the rename.
5. Run the section 7 commands, in order, before committing. Every command exits 0. The default-branch baseline is `1622 passed, 2 skipped`; the resulting total may increase only if the explicit bare-name regression is a new test, but there may be no failure or unexpected skip.
6. After gates, `git diff --check` emits nothing. `git status --short` shows only the section 3 tracked changes plus `?? pr-body.md`. After the one commit, `git status --short` shows only `?? pr-body.md`.

## 7. Gate commands

Run verbatim, in this required order, before the commit:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

## 8. Constraints and prohibitions

Not-touched scope fence: no bounding box, `record_covers`, shipped `source="live"`, coverage snapshot, harmonised name/river search, chained query language, PyPI publication, documentation authoring beyond the two named ADR term substitutions, provider porting, or decision about shipping native tables. Do not edit ADR 0015 or other historical design records. Do not edit `.pce/repository-contract.json` at all, especially any field under `stated`. Do not change package version, create a tag, or alter `pyproject.toml`/`uv.lock`. Do not rerun any provider `generate_catalogue.py` entry point. Do not modify any provider/native fixture or `native.parquet`. This plan contains no pre-derived argument that the design is correct; it specifies reversible rename behavior and exact observations only.

Binding environment knowledge, quoted verbatim:

1. "uv opens ~/.cache/uv/sdists-v9/.git for write on EVERY invocation, so no uv command can run under a sandbox that denies writes there. pce measures stated gates under a Seatbelt profile whose only writable roots are the repository root and the platform temporary directory, and the codex sandbox allows workdir, /tmp and $TMPDIR; neither allows ~/.cache. The machine therefore carries ~/.config/uv/uv.toml setting cache-dir to a warm shared cache under $TMPDIR, which both sandboxes permit. Measured: all five stated gates green in a cold fresh worktree with network denied. If a gate fails with 'Failed to initialize cache' / 'Operation not permitted (os error 1)', that config is missing or the temp cache was purged; recreate it and re-warm with uv sync --reinstall outside any sandbox. Do not point cache-dir inside the repository: uv warns it may be included in distributions and every fresh worktree starts cold with no network."
2. "Mutation testing must set PYTHONDONTWRITEBYTECODE=1 and pytest -p no:cacheprovider: same-size edits written within one mtime second collide under CPython (mtime, size) pyc invalidation and produce a false killed result."
3. "A full-suite run inside a git archive extraction shows a spurious extra failure in tests/test_ch_foen_generate_catalogue.py because that test shells out to git show HEAD: and an extraction is not a repository."
4. "The default-branch gate baseline is fully green as of the commit that introduced this file, and pce contract check aborts on the first red gate. Any red gate an executor observes is therefore caused by its own change and must be fixed, not tolerated against a historical baseline. The previous run's red baseline (a B905 at br_ana/generate_catalogue.py:507, an invalid-argument-type at br_ana/generate_catalogue.py:623, and an unresolved-import of tqdm at jp_mlit/generate_catalogue.py:202) was closed in that same commit; tqdm is now a declared dev dependency, so the deliberately-optional import at jp_mlit/generate_catalogue.py:202 resolves for ty while its try/except ImportError still governs runtime."
5. "tests/typecheck/nominal_window_misuse.py is an INTENTIONAL negative type-check fixture asserted by tests/test_internal_engine_contracts.py. It is excluded from the stated typecheck gate because that gate is scoped to src. Whole-project uv run ty check therefore reports it and must never be used as the gate. Never repair or suppress that fixture."
6. "uv run ruff format is the stated format gate and rewrites files in place rather than reporting; it exits 0 even when it reformats. Use uv run ruff format --check to observe drift without mutating the tree."

Gate ordering, quoted verbatim: "uv sync before format before lint before typecheck before test; uv build last"

Lockfile rule, quoted verbatim: "uv.lock is tracked and must stay synchronized with pyproject.toml; uv sync reports 0 changes at this baseline"

## 9. Executor policies

- Work on the single PR for branch `pce/the-surface-is-three-verbs-and-a-selection/milestone-1`; this step is one squash-merged PR and must be represented locally by exactly **ONE** conventional commit. Use commit subject exactly `refactor: rename published record bounds` and add no attribution/co-author/footer lines.
- Run every gate in section 7 before creating the commit. Fix every red result; do not tolerate it as baseline behavior.
- At the worktree root, write `pr-body.md` with exactly:

  ```markdown
  ## Summary
  - rename canonical station-product record bounds to `published_record_start_date` and `published_record_end_date`
  - update all thirteen generators and value-preservingly rename all thirteen packaged station-product artifacts
  - align schema regression coverage, affected content pins, and current ADR terminology

  ## Validation
  - `uv sync`
  - `uv run ruff format`
  - `uv run ruff check --fix`
  - `uv run ty check src`
  - `uv run pytest`
  - `uv build`
  ```

  Leave `pr-body.md` untracked and do not commit it.
- Create no tag. Do not push. Add no attribution footers. Do not edit any field under `stated` in `.pce/repository-contract.json`.
- Version policy is **NONE**: make no version bump and create no release/tag.
