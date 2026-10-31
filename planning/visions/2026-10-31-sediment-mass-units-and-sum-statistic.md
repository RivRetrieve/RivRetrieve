# Support river sediment mass-transport quantities, metric tonnes and sum statistic

Extend shared physical admission, unit conversion and query validation so river
providers can expose interval-integrated suspended sediment mass and bedload mass
series in metric tonnes (`t`) without conflating distinct transport processes.

Associated issue: [#635](https://github.com/RivRetrieve/RivRetrieve/issues/635).
Implementing this vision completes the issue; publishing this document alone does
not change runtime behavior.

## Current behavior and context

During Step 1 ([#612](https://github.com/RivRetrieve/RivRetrieve/issues/612)) of the
Austria eHYD port ([#525](https://github.com/RivRetrieve/RivRetrieve/issues/525)),
federal eHYD (`owf`) was confirmed to publish two quality-controlled daily river
sediment mass-transport series as 1-day interval sums in metric tonnes (`t`):

- `Schwebstoff-Tagesfracht` (`Exportzeitreihe: Schwebstoff,I,Sum,T,1,...`, unit `t`)
- `Geschiebe-Tagesfracht` (`Exportzeitreihe: Geschiebe,I,Sum,T,1,...`, unit `t`)

At `e845c583`, three shared-engine boundaries reject these series:

1. `_UNIT_DIMENSIONS` in `src/rivretrieve/_internal/source_series.py` maps each
   normalized unit string directly to a single `(quantity, factor)` pair, and
   `admission()` rejects `quantity != facts.quantity.value`. Two distinct physical
   quantities (`suspended_sediment_mass` and `bedload_mass`) therefore cannot share
   the same mass unit (`t`).
2. `Unit` in `src/rivretrieve/_internal/engine.py` defines `m3/s`, `m`, `cm`,
   `ft3/s`, `ft`, `l/s`, `mm` and `degC`, with no metric tonne (`t`) or kilogram
   (`kg`) unit members.
3. `QUERY_VOCABULARIES` in `src/rivretrieve/_internal/selection.py` limits
   `quantity` to `("discharge", "stage", "temperature")` and `statistic` to
   `("mean", "min", "max", "instantaneous")`.

## Agreed behavior

- Separate physical dimension from physical quantity in `source_series.py`:
  - Map normalized units to `(dimension, factor)` across four dimensions:
    `volume_flow` (`m3/s`, `ft3/s`, `l/s`), `length` (`m`, `cm`, `mm`, `ft`),
    `temperature` (`degC`) and `mass` (`t` with factor `1.0`, `kg` with factor
    `0.001`).
  - Map supported quantities to `(dimension, target_unit)`:
    - `discharge` -> `("volume_flow", "m3/s")`
    - `stage` -> `("length", "m")`
    - `temperature` -> `("temperature", "degC")`
    - `suspended_sediment_mass` -> `("mass", "t")`
    - `bedload_mass` -> `("mass", "t")`
  - Preserve strict scale and dimension checks during unit normalization:
    normalizing `kg` to `t`, `t` to `kg` or any cross-dimension unit remains
    rejected, and ambiguous spellings such as `ton` (short or long ton) or `T` are
    not implicitly aliased to metric tonnes (`t`).
  - Keep `suspended_sediment_mass` and `bedload_mass` distinct throughout
    selection, native storage, conversion (`result.data["quantity"]`), series
    inspection (`rr.series(...)`) and product catalogue projection (`observed_property`).
- Add `T = "t"` and `KG = "kg"` to `Unit` in `src/rivretrieve/_internal/engine.py`.
- Extend `QUERY_VOCABULARIES` in `src/rivretrieve/_internal/selection.py`:
  - `quantity`: `("discharge", "stage", "temperature", "suspended_sediment_mass", "bedload_mass")`
  - `statistic`: `("mean", "min", "max", "instantaneous", "sum")`
  - Keep exact, case-sensitive matching without aliases or automatic cross-statistic
    aggregation.

## Documentation and acceptance

Update public docstrings (`src/rivretrieve/_internal/discovery.py` and
`src/rivretrieve/_internal/observations.py`), the usage guide (`docs/usage.md`),
and generated reference tables (`docs/_generated/reference-tables.md` via
`scripts/generate_reference.py`) so target units (`m3/s`, `m`, `degC` and `t`) and
supported query filters remain consistent across code and docs.

Source-independent tests must demonstrate:

- Both `suspended_sediment_mass` and `bedload_mass` admit `t` (`factor=1.0`) and
  `kg` (`factor=0.001`) to target unit `t` while keeping their `quantity` values
  and `product_row` `observed_property` values distinct.
- Scale-changing mass normalizations (`kg` <-> `t`), cross-dimension pairings
  (such as `m3/s` or `m` with `suspended_sediment_mass`, or `t` with `discharge`),
  unestablished quantities and ambiguous `ton` labels are refused.
- Native store accumulation, read-back, conversion (`Unit.T`, `Unit.KG`) and bundle
  export/import preserve native values (`source_unit`) and convert once to `t`.
- `find` and `pick` (including fetched-result views) accept
  `quantity="suspended_sediment_mass"`, `quantity="bedload_mass"` and
  `statistic="sum"`, while continuing to reject unsupported spellings and aliases
  such as `"suspended sediment"`, `"sediment"`, `"bedload"` or `"total"`.

## Boundaries

This change adds shared physical contracts only; it does not add provider mappings,
packaged catalogue artifacts or private archive bindings, and it does not add
suspended sediment concentration (`mg/l`), turbidity or mass-flux rate (`kg/s`)
quantities. Do not merge the pull request to `main` without manual collaborator
review.
