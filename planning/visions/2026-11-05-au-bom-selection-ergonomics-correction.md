# Australia BoM selection ergonomics correction

Corrects two decisions #645 made for `au_bom`'s discharge daily means
(`discharge_daily_mean_24hr`, `discharge_daily_mean_09hr`), found while
writing #649's user documentation and delivered as
[Effort #699](https://github.com/RivRetrieve/RivRetrieve/issues/699) under
[Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334). Work
targets `port/au-bom` and leaves `main` unchanged.

## What #645 got right, and what it got wrong

The choice to give the two series separate `product_id`s rather than
merging them was correct and stays unchanged: `br_ana`'s own `bruto`/
`consistido` pair is also two separate `product_id`s, and
`docs/architecture.md` states the general principle directly ("RivRetrieve
preserves each matching supported identity rather than choosing a preferred
series"). This is not being revisited.

Two things #645 left unestablished should not have been:

**`label_time`.** Every other provider in this codebase with a daily
product populates `PhysicalFacts.label_time` (`br_ana`, `ca_eccc`,
`fr_hubeau`, `cz_chmi`, `lt_lhmt`, `jp_mlit`, `pl_imgw`, `usgs_nwis`), and the
shared engine's `conversion.py` actively validates every row against it once
set. #645's own vision already live-confirmed the exact values this field
needs, in its own aggregation-ladder table: `24HR`-suffixed series label
every row `00:00`, `09HR`-suffixed series label every row `09:00`, with no
exceptions found. Leaving it unestablished was not a considered position in
the vision text; it was an implementation-time comment ("matching every
other provider... none currently populates either field") that was simply
inaccurate.

**`variant`.** #645 considered and rejected `variant` for `au_bom`, but the
stated reason ("BoM names no distinction between them... unlike `br_ana`'s
named consistency levels") was written about a different ambiguity: the
within-product duplicate-`ts_id` case (two `ts_id` for one station and
product, where BoM genuinely names no distinction). It does not hold for
the across-product `24hr`/`09hr` case: BoM's own native series name
(`DMQaQc.Merged.DailyMean.24HR` vs `...09HR`) is a source-stated
distinguishing name, directly comparable to `br_ana`'s native consistency
codes. `docs/usage.md` has a section titled "When an agency publishes more
than one version", framed generically and using `br_ana` only as its worked
example — this is the exact situation it describes.

## What changes

`src/rivretrieve/_internal/providers/au_bom/series.py`:

- `_label_time()`: `"00:00"` for every daily-or-coarser product except
  `discharge_daily_mean_09hr` (`"09:00"`); `None` for hourly products,
  matching every other provider's own convention of leaving it unset where
  there is no daily label at all.
- `_variant()`: `"24hr"` / `"09hr"` for discharge's two daily-mean products
  only. Every other `au_bom` product stays unambiguous under `quantity`,
  `frequency` and `statistic` alone and keeps `variant` unset.
- The duplicate-`ts_id` case (one product, two source identities) is
  unaffected: both still carry whichever `variant` their shared product
  carries, `None` for every product except the 24hr/09hr pair, and remain
  distinguished by `series_id`, not by this change.

## A real nuance in how this surfaces to users

Checked live: restricting *before* fetching with
`rr.pick(selection, variant="09hr")` works correctly end to end for
`au_bom`, but with one difference from `br_ana`'s documented pattern —
`au_bom`'s series identity (like its `series_id`) is confirmed only once a
response names a concrete `ts_id`, not from the offline catalogue. Checked
live: this raises a `selection.unresolved_inventory` warning on the way
("The acquired inventory cannot settle the explicit source restriction
'09hr'") rather than resolving silently, then honors the restriction
correctly once BoM responds (confirmed: the sibling product reports
`NO_MATCH` rather than being fetched, and the result contains only the
requested variant's rows). Restricting the *result* after fetching
(`rr.pick(result, variant="09hr")`) resolves with no warning at all, since
the real identities are known by then. #649's documentation is updated to
show both, honestly, rather than presenting only the warning-free case.

## Verification

- `uv run pytest --logic-only -q -k au_bom`: all pass, including new tests
  for `_label_time()`/`_variant()` on the 09hr product and on products
  outside the 24hr/09hr pair.
- `tests/test_au_bom_recorded_public.py` (genuine retained evidence) still
  passes unchanged.
- `uv run ruff check src tests` and `uv run ty check src` clean.
- No new genuine evidence capture was needed: every value here was already
  live-confirmed and on record in #645's own vision doc.

Once merged, #649's documentation (PR #696, still open) is updated to use
`variant` directly instead of its current fetch-then-filter-by-`product_id`
workaround.
