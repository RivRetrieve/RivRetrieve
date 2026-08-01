# Catalogue metadata is Croissant, not a schema of our own

The packaged catalogue describes itself with an [MLCommons Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec.html)
descriptor, extended with one property, rather than a metadata schema we design. Staleness
uses [dbt's source freshness vocabulary](https://docs.getdbt.com/docs/build/sources).

Croissant already carries almost everything ADR 0012 needs. A `Field` declares where its
values come from through `source`, with `extract` taking `column` for tabular files,
`jsonPath` for JSON and `fileProperty` for whole files, plus `transform` for regex,
delimiter and JSON queries and `format` for date patterns. At dataset level it defines
`license`, `citation`, `version`, `datePublished`, `creator` and `distribution` entries
carrying `sha256`, which is the provider-level licence and citation this Program wanted and
the artefact hashing ADR 0013 needs. dbt gives `loaded_at_field` with `warn_after` and
`error_after` in `{count, period}`, which is a better answer than the bare
`catalogue_version: "2026-06-01"` we ship, since it states when a catalogue stops being
trustworthy rather than only when it was made.

The one thing neither covers is a field that is deliberately empty because the source
publishes nothing. A Croissant field with no `source` is merely underspecified,
indistinguishable from carelessness, and there is no place to attach evidence. That gap is
our extension and it is one property:

```json
{ "@type": "Field", "name": "start_date",
  "rr:notPublished": {"evidence": "https://waterservices.usgs.gov/docs/site-service/"} }
```

The rejected alternative is a bespoke schema, which was the shape this work was heading
toward before the standards were checked. It would have been reinvention, and it would have
produced a catalogue only RivRetrieve can read. The cost accepted is that Croissant is
JSON-LD and therefore more verbose than a Python dataclass, and that one extension property
means the descriptor is not strictly vanilla.

## Consequence: an upstream question worth asking

Documented absence with evidence generalises past river data to any dataset assembled from
third-party sources. It is not filed upstream; the nearest open issue,
[mlcommons/croissant#1012](https://github.com/mlcommons/croissant/issues/1012), asks for
dataset-level bias description rather than field-level absence. Ask whether the vocabulary
exists before designing the extension, and propose it only once it has shipped here across
thirteen sources.
