# Finland SYKE series identity and physical meaning

Settle scope and design for [Effort #755](https://github.com/RivRetrieve/RivRetrieve/issues/755)
(step 3 of the [provider-port guide](../../docs/maintenance/provider-ports.md))
for `fi_syke`. This vision maps `Virtaama` (discharge), `Vedenkorkeus` (stage)
and `LampoPintavesi` (surface water temperature) to distinct `SourceIdentity`
and `PhysicalFacts` records. It does not edit
`src/rivretrieve/_internal/providers/fi_syke/catalogue_series.py` — that is a
separate implementation PR for this same Effort, following the same
vision-then-implementation split already used for this port's step 2 and for
Austria's and Australia's series-identity Efforts (`#614`, `#645`).

The port belongs to [Program #353](https://github.com/RivRetrieve/RivRetrieve/issues/353).
Builds on the merged [source, scope and access vision](2026-11-07-fi-syke-source-scope-and-access.md)
(Effort #753) and [station catalogue vision](2026-11-07-fi-syke-station-catalogue-and-metadata.md)
(Effort #754, including its `Paikka_Id` correction). This vision does not
reopen station identity or product scope.

All live evidence below is checked today against SYKE's own OData API
(`https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata`) and
recorded in full in `research/fi-syke-series-identity.md`
(`verification-evidence`).

## Per-station series identity: resolved, not open

Step 2's `catalogue_series.py` currently describes each entity set's
`SourceIdentity` as "per-station series identity is unresolved" — a
placeholder left over from before step 2's `Nro`→`Paikka_Id` correction. It
no longer applies: station identity is `Paikka_Id`, and every `Paikka_Id`
row carries exactly one `Suure_Id`. Filtering `Virtaama`/`Vedenkorkeus`/
`LampoPintavesi` by `Paikka_Id` therefore returns exactly one station's one
series for that quantity, with no grouping or priority choice needed at the
series level either. The implementation PR should update this wording to
reflect that resolution.

## Quantities and units: source-documented, unchanged from step 1/2

The `Suure` entity set itself states the unit per quantity — `Virtaama`
(`Suure_Id=2`) in m³/s, `Vedenkorkeus` (`Suure_Id=1`) in cm, `LampoPintavesi`
(`Suure_Id=11`) in °C. `TauluKuvaus`/`SarakeKuvaus` remain empty for all three
tables' columns, re-checked live today — no new source documentation exists
beyond what steps 1/2 already found.

## Major finding: `Vedenkorkeus` is an absolute water-surface elevation, not a small relative stage

hydrodownloadR's own adapter comments `Vedenkorkeus`'s `Arvo` as `# raw cm
(FI returns cm in Arvo)`, treating it as a small reading needing a separate
correction. Checking the live magnitude distribution does not support that:
sampling every currently-active stage station's latest value (780 stations,
9,210 rows since 2026-10-25) gives a range of **-222 cm to 24,469 cm**
(median ~2,890 cm) — e.g. `Paikka_Id 3916` "Ahmasoja" on the small coastal
river `Eurajoki` reads -222 cm, while `Paikka_Id 2471` "Luksuan pato" on
`Kemijoki` at the Lapland reservoir `Yli-Suolijärvi` reads 24,469 cm
(~244.7 m). Both are realistic *absolute* elevations for Finland's real
low-relief, coast-to-Lapland geography — not evidence of two different
reading conventions.

This is independently corroborated by `VedenkTasoTieto`, a separate entity
set giving per-site corrections (`Tasokorjaus`) between five historical
Finnish national height systems (`N43`, `NN`, `N60`, `N2000`, `LN`). It
covers 1,623 of 1,753 stage stations (93%) and is empty for every discharge
or temperature station checked — stage-specific, as expected for a vertical
datum correction. Critically, correction-row presence does **not** track the
small/large magnitude split (346/351 small-magnitude and 395/429
large-magnitude stations both have a row, at statistically the same rate),
ruling out a mixed-convention explanation and supporting one uniform
convention: every `Vedenkorkeus` reading is an absolute elevation,
re-expressible in any of the five national datums.

The datum at which a site's own raw `Arvo` already sits with a `0`
correction is inconsistent site to site (some zero at `N60`, one sampled
site zeros at `NN`, several have no zero-row at all in the sample) — no
single national datum can be named as every site's universal native system
from this evidence.

**Recommendation:** `vertical_reference = known("above_sea_level", ...)` for
`stage_reported`'s `PhysicalFacts`, reusing the exact vocabulary
`at_ehyd/series.py` already established for this situation (distinct from
`"gauge_zero"`, which does not fit here). `vertical_datum` stays
`not_established`.

## `ArvoMin`/`ArvoMax`: real but inconsistent, not evidence of a daily-mean rule

`Virtaama` and `Vedenkorkeus` both carry `ArvoMin`/`ArvoMax` columns;
`LampoPintavesi` does not (confirmed live — real `LampoPintavesi` rows carry
only `Paikka_Id`/`Aika`/`Arvo`, and any query referencing `Lippu_id` or
`ArvoMin`/`ArvoMax` on that table returns HTTP 400, despite `SarakeKuvaus`
listing more columns for it than the table actually returns).

Where populated (sampled on a historical discharge site, August 1999),
`Arvo` sits between `ArvoMin` and `ArvoMax` on every row — consistent with a
mean over some sub-daily range. But every row checked on the modern/current
side (discharge site `894`'s 35 most recent daily values, Oct–Nov 2026; and
a historical stage site's full 1959–1960 run) has `ArvoMin`/`ArvoMax` both
`null`. No source documentation states when or why these are populated.

Per the port guide's explicit instruction not to infer a daily mean from
cadence or a field name alone, **`statistic` stays `source_silent`** for all
three products — unchanged from step 2's placeholder, now with the fuller
evidence behind that choice recorded. `ArvoMin`/`ArvoMax`'s presence is a
fact for a future parsing step (#756/#757) to decide what to do with, not
something this vision or `PhysicalFacts` models.

`temporal_support`, `timestamp_anchor` and `time_zone` also stay
`source_silent` — re-checked live, `TauluKuvaus` still states none of them.
`frequency` is unchanged (`known("daily", ...)` since step 1/2).

## `Lippu` flag vocabulary: 63 codes, several unrelated kinds of meaning, not a ranking

The full `Lippu` entity set (63 rows, fetched live) mixes data-quality/
processing flags (`Interpoloitu`, `Redukoitu`, `Mahdollisesti virheellinen
arvo`, and many snow/ice/precipitation-specific codes irrelevant to river
discharge/stage/temperature), percentile statistics (`P05`…`P95`, `PKA`),
simulated/model-derived values (`Simuloitu minimi/maksimi/…`), and device
identifiers (`2`, `3`). Only two entries carry an English description at
all.

Sampled actual usage on the three admitted tables across available history:
`Virtaama` uses codes `1` (Interpoloitu), `2` (Muu vertailu) and `3`
(Redukoitu, dominant in its oldest 1911 records); `Vedenkorkeus` uses `1` and
`2`; `LampoPintavesi` has no `Lippu_id` field at all. Every current/recent
row checked across both tables has `Lippu_id = null`.

Per the port guide's explicit instruction not to interpret quality codes as
a ranking, this vocabulary is recorded as a source fact
(`research/fi-syke-series-identity.md`) without constructing a trust
ordering, and without a new `PhysicalFacts` field — none exists for an
arbitrary flag vocabulary. Whether and how to surface `Lippu_id` on
observation rows is left to a future parsing step.

## Schema note: `huomautus` exists only on `Virtaama`

A free-text `huomautus` (remark) column exists on `Virtaama` rows (always
`null` in every row sampled) but not on `Vedenkorkeus` or `LampoPintavesi`
rows — confirmed in both `SarakeKuvaus` and live row samples. A real
difference between the three otherwise-parallel series, not an oversight to
normalize away.

## Implementation PR: what changes, named but not done here

A later, separate PR for this same Effort should:

- Add `vertical_reference`/`vertical_datum` to `stage_reported`'s
  `PhysicalFacts` in `catalogue_series.py`, per the recommendation above.
- Update each `SourceIdentity.description` to drop the stale "unresolved"
  wording.
- Leave `statistic`/`temporal_support`/`timestamp_anchor`/`time_zone` as
  `source_silent`, unchanged.
- Rebuild and recertify the `catalogue/` artifact, and extend
  `tests/test_fi_syke_module.py`/`test_catalogue_origin_certification.py`
  as needed for the new facts.

## Completion

Post a concise scope update on #755 referencing this vision, including the
`Vedenkorkeus` absolute-elevation finding. Keep #755 open until the
implementation PR is merged.
