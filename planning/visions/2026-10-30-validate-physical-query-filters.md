# Validate physical query filters

Reject unsupported quantity, frequency and statistic filters at the point of
selection, with useful errors rather than a silent empty search. Keep valid
searches with no known matches distinct from invalid input.

Associated issue: [#599](https://github.com/RivRetrieve/RivRetrieve/issues/599).
Implementing this vision completes the issue. Publishing this document does not
complete it or change runtime behavior.

## Current behavior and context

At investigation revision `3ca27cce`, the reported Swiss examples were reproduced:
`quantity="water temperature"`, `frequency="dayly"` and `statistic="average"`
returned zero inspection rows and no issues. `fetch` then raised
`EmptySelectionError` with `unresolved_inventory`, without identifying the physical
filters. `quantity="temperature"` returned 910 rows. This count is investigation
evidence, not a permanent acceptance requirement.

The `find` docstring in `src/rivretrieve/_internal/discovery.py` explicitly says
physical values are exact strings, are not vocabulary-checked, and misspellings
return an empty selection without an issue. The API reference renders that
docstring. This work changes that public contract.

`_validate_vocabulary` in `selection.py` currently checks provider, station and
product identifiers. `PhysicalPredicate` and `EvidenceFact` in `source_series.py`
carry string values; the current model does not define closed frequency or
statistic vocabularies. Numeric admission currently supports discharge, stage and
temperature. Define supported query values explicitly rather than treating all
preserved source facts as a closed vocabulary.

See [architecture](../../docs/architecture.md) and [usage](../../docs/usage.md)
for the distinction between established physical facts, source identity and
incomplete catalogue inventories.

## Agreed behavior

- Define one authoritative supported query vocabulary for each of quantity,
  frequency and statistic. Quantity includes `discharge`, `stage` and
  `temperature`. Establish the frequency and statistic lists from existing
  provider contracts and supported physical meanings before implementing them.
  Share these definitions across validation and documentation rather than
  maintaining independent lists.
- Validate supplied values immediately in `find` and `pick`, including `pick`
  applied to a fetched result. An unsupported value raises a clear input error
  naming the field, supplied value and supported values. It is not a selection
  issue that `on_issue="ignore"` can suppress.
- Keep matching exact and case-sensitive. Do not add aliases, silently correct
  spelling or substitute a different requested measurement. A close-spelling
  suggestion may help the caller correct an error, but never changes the request.
- Apply library-wide vocabularies. A supported value does not become invalid
  because one provider, station or current selection has no matching series.
- Preserve valid empty selections and contradictory valid restrictions. A source
  fact that is unknown still does not match an explicit filter. Preserve the
  distinction between established absence and unresolved availability; an
  incomplete catalogue is not proof that a valid request can never match.
- Improve empty-selection errors to include the requested physical filters.
  Report the combined request without claiming that one filter alone caused
  absence when the evidence cannot establish that.
- Preserve internal source evidence outside the supported query vocabulary.
  Do not restrict all `EvidenceFact` values or rewrite source vocabulary to make
  query validation work.

## Documentation and acceptance

Replace the current `find` clause saying that misspellings return an empty
selection without an issue. Update applicable `find` and `pick` parameter and
exception documentation, and the usage guide. Explain supported values, exact
matching, invalid-input errors and valid searches with no matches. Document the
improved empty-selection diagnostic without promising exhaustive inventory.

Source-independent tests should demonstrate:

- The reported unsupported words fail during `find` and `pick`, including result
  filtering, with the offending field/value and supported choices visible.
- Case variants and aliases are not accepted implicitly. Suggestions, when
  present, do not execute a corrected request.
- Supported values continue to work. Supported values absent from a selected
  provider or station remain valid searches, and unknown source facts remain
  excluded by explicit filters.
- Valid empty and contradictory searches retain their existing absence versus
  uncertainty semantics, and their fetch errors expose the physical filters.
- Preserved source facts are not narrowed to the query vocabularies.

Use the existing shared selection contracts and the repository testing guide.
Run affected source-independent tests and checks appropriate to changed public
boundaries. No provider mapping, governing source claim or private source evidence
change is intended.

## Boundaries and implementation choices

Other physical filters, such as vertical datum, remain outside this vocabulary
change. This work does not add fuzzy execution, synonyms, new hydrological
products, source reinterpretation or automatic preference among published series.

The implementing agent chooses the type representation, exception classes,
validation placement and suggestion algorithm. Keep one source of truth for
supported query values and retain ordinary string calls such as
`find(quantity="discharge")`. Exact frequency/statistic membership requires the
provider-contract inventory described above; do not infer an exhaustive public
vocabulary solely from values observed in one packaged catalogue.
