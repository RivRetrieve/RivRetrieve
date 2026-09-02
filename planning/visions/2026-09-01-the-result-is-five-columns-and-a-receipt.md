# Vision: The result is five columns and a receipt

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/11

## Goal / Why

A result is the only thing a user of RivRetrieve ever actually holds. Today it does not
keep the promises the project has already made about it.

The engine computes a time zone for every observation row and then discards it one line
before the caller sees it (`registry.py`, `_drive_engine` selects only
`time, station_id, product_id, value`). The canonical table ADR 0006 specifies —
`time | time_zone | station_id | product_id | value` — therefore exists inside the engine
and nowhere at the surface. A user who asks for two gauges in different zones gets a
naive timestamp column and no way to interpret it, which is the exact silent wrongness
ADR 0001 and ADR 0006 exist to prevent.

Every result also carries two annotation tables that are always empty. `usgs_nwis` and
`ca_eccc` each declare a schema for theirs; neither has ever emitted a single row. That
is the shape of the mistake: asking thirteen providers to each model their own extras
produced thirteen declarations and zero data.

Every result carries a `raw` slot built as `RawPayload(provider_id=...)` and nothing
else, while `CONTEXT.md` states as settled language that raw is the provider payload kept
alongside the returned data. The receipt is a promise the code does not keep.

The product catalogue for all thirteen providers carries a `derived` flag that is always
false and a `derivation_method` that is always null — vocabulary for a capability that is
banned. Three providers advertise eight daily-mean products that no source publishes:
verified in the legacy reference, `ch_foen/query.py`, `th_thaiwater/transform.py` and
`ba_fhmzbih/transform.py` each set `aggregate_daily=True` for exactly those products and
`False` for every other, and compute them with `group_by(...).mean()`.

Success is that a result becomes exactly four things — a five-column frame, a receipt,
issues, and raw — identical for all thirteen providers; that a user can audit any value
against what the source actually said; and that everything above disappears.

## Scope — In

1. Add `time_zone` to the frame `observations()` returns, carrying the value the engine
   already computes per row, so the public table is ADR 0006's five columns in its order.
   `unknown` where the source establishes no zone.
2. Reduce `ObservationResult` to exactly four members — the frame, provenance, issues,
   raw — with the same shape for every provider.
3. Make `raw` opt-in: the slot always exists, stays empty unless the caller asks for it
   on the call, and holds no response bytes when unasked.
4. Populate `raw`, when asked, as one entry per source call. Each entry holds the bytes
   the provider's `parse` stage was handed, as bytes, plus a uniform envelope stating
   where those bytes came from: URL, request parameters, status code, `retrieved_at` and
   content type where they apply, and `unknown` where they do not.
5. Exclude request headers from `raw` and from the receipt entirely, so a credential can
   never appear in either.
6. Add `license` and `citation` to `ObservationProvenance`, fed only by read-through from
   the packaged catalogue — never an engine constant, never inferred. Emit an
   `info`-severity issue when they are absent.
7. Delete both annotation tables and everything supporting them: `RowAnnotationTableSchema`,
   `SeriesAnnotationTableSchema`, `AnnotationTable`, `AnnotationSchema`,
   `AnnotationSchemaDeclaration`, `validate_annotation_names`,
   `AnnotationSchemaViolationError`, the `row_annotations` and `series_annotations`
   members of `ObservationResult`, the `row_annotation_schema()` and
   `series_annotation_schema()` methods on `ProviderHandle`, their counterparts in the
   provider-module protocol and the registry, and the declarations in
   `usgs_nwis/module.py` and `ca_eccc/module.py`.
8. Delete `derived` and `derivation_method` from `PRODUCT_CATALOG_SCHEMA` and from all
   thirteen `generate_catalogue.py` files, and regenerate the packaged catalogue
   artifacts.
9. Delete the eight computed daily-mean products from the catalogues of `ba_fhmzbih`
   (`discharge_daily_mean`, `stage_daily_mean`, `water_temperature_daily_mean`),
   `th_thaiwater` (`stage_daily_mean`, `discharge_daily_mean`) and `ch_foen`
   (`discharge_daily_mean`, `stage_daily_mean`, `water_temperature_daily_mean`).
10. Update `CONTEXT.md` where this changes settled language.

## Scope — Out (explicit non-goals)

- Establishing what any source's licence or citation actually is, or filling those
  fields with values. That is Effort ticket #51; this vision builds the pipe only.
- The on-disk layout of a stored row and the interface it is queried through. That is
  Effort ticket #12, which reconciles against this result shape as its projection.
- A harmonised quality flag, or any structured home for source-published quality codes.
  Deferred past v0.1.0 by standing decision; after this lands such codes survive in
  `raw` or not at all.
- Porting any provider's observation stages. Eleven of thirteen remain catalogue-only.
- Restoring the deleted daily-mean products by any means, including fixing their
  averaging. Aggregation of any kind is banned.
- Credentialed providers and how they earn origin guarantees — Effort ticket #90.
- Deriving a station's zone from anything other than what its source publishes.
- Modelling, parsing, or per-provider typing of `raw` content. Bytes stay bytes.

## Constraints

- ADR 0006 fixes the canonical table as `time | time_zone | station_id | product_id |
  value` and is not reopened here.
- ADR 0007 fixes what a zone value may be: an IANA identifier, a fixed offset, or
  `unknown`.
- `unknown` means *the source does not tell us* (`CONTEXT.md`, ADR 0005). A licence
  RivRetrieve has not yet researched is not `unknown` — the sources publish their terms.
  Whatever the receipt emits before #51 must mean "not established by RivRetrieve".
- `apply_on_issue` acts only on `warning` and `error`. An `info` issue is carried in
  `issues` but never printed and never raised, including under `on_issue="raise"`.
- `raw` is what `parse` was handed, not what came off the wire. Eleven providers fetch
  over HTTP; `ca_eccc` queries a local SQLite cache and never touches the network;
  `pl_imgw` downloads a zip and reads a member out of it. The envelope is engine-owned
  and provider-agnostic — no provider file gains any code for `raw`.
- The repository is private with no PyPI release, so there is no backward-compatibility
  obligation for any removed column, member, or product.
- Eleven of the thirteen providers are catalogue-only, so removing catalogue rows removes
  a listing rather than a working capability.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "Zone reaches the caller",
      "input": "retrieve a usgs_nwis sub-daily product for a station whose payload states a UTC offset",
      "observation": "the returned frame has a time_zone column and every row's value is the offset the payload stated, neither null nor the string unknown"
    },
    {
      "name": "Zone admits ignorance",
      "input": "retrieve from a provider whose source publishes no zone for the requested station",
      "observation": "every returned row's time_zone is exactly the string unknown"
    },
    {
      "name": "Raw costs nothing unasked",
      "input": "call observations() without asking for raw",
      "observation": "the result's raw slot is empty and no source response bytes are reachable from the returned result"
    },
    {
      "name": "Raw works without a network",
      "input": "ask for raw on a ca_eccc retrieval served from the local SQLite cache",
      "observation": "raw holds one entry per query whose content is the rows that query returned, whose file path and query are stated, and whose URL and status code read unknown rather than a fabricated value"
    },
    {
      "name": "A secret cannot reach raw",
      "input": "perform an authenticated retrieval whose request headers carry a recognisable token, ask for raw, then search every byte of every raw entry and of the provenance receipt for that token",
      "observation": "the token appears nowhere in raw or provenance"
    },
    {
      "name": "Annotations are gone, not hidden",
      "input": "search the shipped package for the annotation vocabulary and attempt to call row_annotation_schema() and series_annotation_schema() on a provider handle",
      "observation": "no annotation type, schema, table or validator remains anywhere in the shipped package, and both method calls fail because the methods do not exist"
    },
    {
      "name": "Derived vocabulary is gone",
      "input": "read the packaged product catalogue for all thirteen providers",
      "observation": "neither derived nor derivation_method is a column, and none of the eight named daily-mean products appears for ba_fhmzbih, th_thaiwater or ch_foen"
    },
    {
      "name": "One shape for all providers",
      "input": "retrieve from usgs_nwis and from ca_eccc and compare the two results",
      "observation": "both expose the same four members and the same provenance fields, with no member present on one and absent on the other"
    }
  ]
}
```

## Decomposition hints

- Start with the smallest proof that ADR 0006 is real at the surface: stop discarding
  `time_zone` in `_drive_engine` and let it through. It touches one `select`, exercises
  both zone criteria, and is the change most likely to be silently regressed later.
- Do the `raw` design next, before the deletions. It is the only genuinely new mechanism
  here and the only place the vision can be built wrong rather than incompletely. Design
  the envelope against `ca_eccc` first, not `usgs_nwis` — the non-HTTP case is what
  forces the `unknown` fields to exist, and building HTTP-first will produce an envelope
  that has to be reopened.
- Write the secret-cannot-reach-raw check as part of the raw slice rather than after it.
  It is the one criterion designed to make the thing fail, and it is cheapest to satisfy
  while the envelope's field list is still being decided.
- The deletions are mechanical and independent of each other: annotations, the derived
  vocabulary, and the eight products can land in any order. They produce a large diff and
  little risk. `ObservationResult` losing two members and `ProviderHandle` losing two
  methods should land together, since the registry validates the tables against the
  schemas and both halves must go at once.
- The provenance licence and citation pipe is last and smallest — two optional fields and
  an `info` issue, with no values to supply.
- Regenerating the packaged catalogue artifacts is the tail of the two catalogue-schema
  slices, not a slice of its own.

## Open questions / risks

- An ADR titled *Raw is what parse read* was offered during the grill and not yet
  accepted. It records why `raw` hands back an unzipped member rather than the bytes the
  server sent, and #12 inherits that answer for the stored row. Needs a yes or a no
  before the raw slice lands.
- The secret-cannot-reach-raw criterion is checkable in this run only against a fake
  authenticated transport. No ported provider needs credentials today — `za_dws` and
  `no_nve` are catalogue-only and #90 owns credentialed providers — so it cannot be
  proven against a live authenticated source until then.
- The `pl_imgw` zip-member case is specified here but unexercised: that provider is not
  ported, so the envelope's behaviour for "a member of a downloaded archive" ships
  designed and untested until #17 reaches it.
- #11 and #12 describe the same data at two moments and must agree; neither blocks the
  other, and whoever moves second reconciles. If #12 starts before this lands, the stored
  row is the base and this frame is its projection.
- What the receipt emits for a licence RivRetrieve has not established must not be the
  word `unknown`, which in this project means the source is silent. The exact wording is
  unsettled and only matters before #51 fills the values.
