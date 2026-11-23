# Calendar-month selection for year/month source labels

Associated issue: https://github.com/RivRetrieve/RivRetrieve/issues/915 (implementing this vision completes the work tracked in #915).
Related context: https://github.com/RivRetrieve/RivRetrieve/issues/735 (Chile retrieval behavior) under Program https://github.com/RivRetrieve/RivRetrieve/issues/734.

## Outcome and motivation

Support calendar-month selection for source series published as year/month labels without treating their synthetic first-of-month storage carrier as an observation instant. For such series, a mid-month request such as January 15 through March 10 must select January, February, and March while excluding adjacent months.

This shared capability unblocks Chile DGA monthly retrieval (#735) while keeping existing timestamp-labelled monthly series (such as CH-FOEN) on their current clock-bound filtering.

## Settled decisions

- **Explicit clipping mode:** Add `ClippingAxis.CALENDAR_MONTH = "calendar_month"` to `ClippingAxis` in `src/rivretrieve/_internal/source_series.py` and document it in `docs/reference.md`. Calendar-month selection is opt-in through `clipping_axis` and must never be inferred from `frequency == "monthly"` alone.
- **Fact validation:** In `PhysicalFacts`, require established `frequency == "monthly"` when `clipping_axis` is `ClippingAxis.CALENDAR_MONTH` (parallel to `CALENDAR_DATE` requiring `"daily"`). Do not require `temporal_support`, `time_zone`, `timestamp_anchor`, or `day_definition` to be known; those facts must remain free to stay unknown when the source does not state them.
- **Whole-month window bounds:** In `native_window` (`src/rivretrieve/_internal/physical_window.py`), expand `CALENDAR_MONTH` requests to whole calendar months: from `00:00:00` on the first day of the start month through `23:59:59.999999` on the last day of the end month (handling leap years and year boundaries). Apply any established fixed calendar offset afterward, matching `CALENDAR_DATE`. For example, a request from `2025-01-15` through `2025-03-10` produces `2025-01-01T00:00:00` through `2025-03-31T23:59:59.999999`. Compiled-query `RetrievalOutcome.window` values report these same whole-month bounds.
- **Fact-aware compiled-store scan bounds:** In `drive_store` (`src/rivretrieve/_internal/driver.py`), derive `StoreQuery` scan bounds from the `native_window_envelope` of the selected matching facts rather than scanning raw `request.window` with 2-day padding. This ensures synthetic first-of-month carriers are not discarded before conversion. Keep the existing bounded `StoreReader` query contract without a broad reader rewrite.
- **Shared `driver.py` consistency:** Keep the rest of `src/rivretrieve/_internal/driver.py` consistent with `CALENDAR_MONTH`:
  - Update the rolling-snapshot `held_read` query in `drive()` to derive scan bounds from `native_window_envelope` of the matching held facts rather than raw `request.window` bounds.
  - Update `_exclude_intervals_keep_expr()` so cache-interval exclusion for `CALENDAR_MONTH` facts matches on calendar-month range rather than falling back to wall-clock timestamp comparison.
- **Alignment across shared helpers:** Conversion (`convert`), canonical-window validation (`_require_canonical_rows_within_requested`), annotation filtering (`filter_annotations_for_window`), and compiled-query outcomes already consume `native_window` and `native_window_envelope`. Keep them aligned so rows, annotations, and outcomes agree on selected months.

## Constraints and exclusions

- **Preserve timestamp-labelled monthly/yearly behavior:** Series with `ClippingAxis.SOURCE_TIMESTAMP` (including established calendar-month and calendar-year series with real timestamps) must retain explicit clock-bound filtering. In particular, `tests/test_calendar_windows.py::test_calendar_month_and_year_preserve_explicit_clock_bounds` must remain intact and passing.
- **Source fidelity:** Preserve unknown time zone, timestamp anchor, and temporal support. Selecting a calendar month does not claim complete observations within that month.
- **Storage layout:** Retain the existing `time` storage carrier and store layout (and do not require changing native year/month source columns) unless implementation establishes a concrete need to change them.
- **Out of scope:**
  - Adding `ClippingAxis.CALENDAR_YEAR` (do not generalize speculatively).
  - Chile DGA provider acquisition, parsing, and store compilation (handled in #735 / Step 5).

## Repository context

- `src/rivretrieve/_internal/source_series.py`: Defines `ClippingAxis` (`CALENDAR_DATE`, `SOURCE_TIMESTAMP`) and `PhysicalFacts.check()`, which currently enforces `CALENDAR_DATE` -> `frequency.value == "daily"`.
- `src/rivretrieve/_internal/physical_window.py`: Centralizes `native_window()` and `native_window_envelope()`.
- `src/rivretrieve/_internal/conversion.py`: `convert()` and `filter_annotations_for_window()` both clip via `native_window()`.
- `src/rivretrieve/_internal/driver.py`:
  - `drive_store()` currently scans `StoreQuery` with `start - _FETCH_WINDOW_PADDING` and `end + _FETCH_WINDOW_PADDING` (`timedelta(days=2)`), which drops first-of-month carriers on mid-month requests, while already building compiled-query outcomes per `ClippingAxis` via `native_window_envelope()`.
  - `drive()` rolling-snapshot `held_read` currently scans `StoreQuery` with raw `request.window` ± `_FETCH_WINDOW_PADDING`.
  - `_exclude_intervals_keep_expr()` currently special-cases only `ClippingAxis.CALENDAR_DATE` when excluding native intervals.
- `docs/reference.md` and `tests/test_reference_contracts.py`: Document and verify all `ClippingAxis` enum members.
- `tests/test_calendar_windows.py`: Holds the existing calendar-window test suite (14 tests).

## Verification and acceptance criteria

The implementation is complete when all of the following hold:

1. **Compiled-store selection (`drive_store`):**
   - Mid-month requests (e.g., January 15 through March 10) return January, February, and March rows stored on first-of-month carriers.
   - Adjacent months (December, April) are excluded.
   - Year boundaries (e.g., December 15 through January 10) and leap-year February end dates behave accurately.
   - Mixed `CALENDAR_MONTH` and `SOURCE_TIMESTAMP` series in the same request/store each filter according to their own `ClippingAxis`.
   - Measured and unmeasured annotations and compiled-query `RetrievalOutcome.window` entries align with the selected rows.
2. **Domain validation and non-regression:**
   - `PhysicalFacts` rejects `ClippingAxis.CALENDAR_MONTH` when `frequency` is not established as `"monthly"`, and accepts it when `temporal_support`, `time_zone`, `timestamp_anchor`, and `day_definition` are unknown.
   - Existing calendar-window tests pass unchanged, including `tests/test_calendar_windows.py::test_calendar_month_and_year_preserve_explicit_clock_bounds`.
3. **Driver consistency:**
   - `_exclude_intervals_keep_expr` and rolling-snapshot `held_read` handle `CALENDAR_MONTH` consistently with `native_window`.
4. **Repository quality gates:**
   - Reference contract checks (`tests/test_reference_contracts.py`) pass with `CALENDAR_MONTH` documented in `docs/reference.md`.
   - Source-independent tests (`uv run pytest --logic-only`), `uv run ruff format --check`, `uv run ruff check`, and `uv run ty check src` pass.

## Open to implementation

- Exact padding around the fact-derived `StoreQuery` scan envelope (retaining the existing 2-day `_FETCH_WINDOW_PADDING` around `native_window_envelope` is acceptable).
- Helper decomposition and test file organization.
