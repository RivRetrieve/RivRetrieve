# 04-observation-types — Adversarial Critique

**Verdict: SEND BACK TO PLANNER.**

The plan does many things right (six-field `ObservationResult` pinned exactly, no provider_id at row level, no wide-form pandas, fatal direct-raises, no public-surface drift, no step-05 over-reach, reuse of M1 step 02's `CatalogueColumn`/`CatalogueSchema` schema spec). But the canonical column names contradict architecture.md §12 and §16, the `AnnotationSchema` shape inverts architecture.md §13's intent, `ObservationRequest` drops the `provider_id` core field, the typed-temporal commitment in architecture.md §3 / §11 is silently softened to `object`, and the UTC-mandate contradicts architecture.md §16's "preserve provider-native timestamps by default" rule. These are not framing issues — they are direct architecture violations that will rot into M3/M4. Send back; do not dispatch.

The strong scaffolding is salvageable. Folding the column-name fixes alone might be a "minors folded" call, but the AnnotationSchema-shape miss and the missing `provider_id` are real planner-level decisions that need a new round, not patches in the margin.

---

## Major

### M1. Canonical observation column is `time`, not `timestamp`

architecture.md §12 line 478–483:

> The canonical observation table is long-form:
> ```text
> time
> station_id
> product_id
> value
> ```

architecture.md §16 line 622:

> The observation table has one `time` column, not `time_start` and `time_end`.

docs/design/provider-redesign.md line 162:

> `time | station_id | product_id | value`

The plan uses `timestamp` throughout (§3 line 195, §3 line 131 row annotations, §3 line 188 canonical schema, T68 and T70-T72 test inventory). This is a direct, repeated architecture violation. M1 step 02 honored architecture's column names exactly (provider_id, station_id, name, latitude, longitude, country, elevation_m, drainage_area_km2, start_date, end_date, metadata in `StationCatalog`). Step 04 must do the same.

Q9 (line 364) claims the canonical schema is "grounded in arch.md §12" — verified against the actual section, the claim is wrong on column name.

### M2. Annotation column names are `annotation` and `value`, not `annotation_name` and `annotation_value`

architecture.md §12 lines 504–510 (row annotations):

> ```text
> time
> station_id
> product_id
> annotation
> value
> ```

architecture.md §12 lines 514–519 (series annotations):

> ```text
> station_id
> product_id
> annotation
> value
> ```

docs/design/provider-redesign.md lines 283 and 291 confirm this with identical wording.

The plan uses `annotation_name` and `annotation_value` (§3 line 131, line 132, line 134, T64-T66, T58). This is also a direct architecture column-naming violation. `annotation`/`value` and `annotation_name`/`annotation_value` are not interchangeable — every downstream test, fixture, provider port, and `to_pandas()` consumer reads these names.

### M3. `AnnotationSchema` shape inverts architecture.md §13's intent

architecture.md §13 lines 540–554:

> Providers declare annotation schemas up front:
> ```python
> def row_annotation_schema() -> list[AnnotationSchema]: ...
> def series_annotation_schema() -> list[AnnotationSchema]: ...
> ```
>
> Annotation schema fields:
> ```text
> annotation_id
> description
> value_type
> allowed_values
> source_field
> ```

docs/design/provider-redesign.md line 299 lists the same fields. The provider returns a `list[AnnotationSchema]` — meaning a list of *per-annotation declarations*, each describing one annotation (its `annotation_id`, its `value_type`, its `allowed_values`, its provider `source_field`, its `description`).

The plan defines `AnnotationSchema` as `(name, columns, annotation_names, unique_keys, enum_values)` — a *whole-table-shape declaration with a flat allowed-name set*. The plan's `AnnotationSchema` describes one *table* and one *set of names that can appear in its `annotation_name` column*. These are different concepts: per-annotation declarations vs per-table declarations.

This is the load-bearing miss. With the plan as written:

- A provider declaring three quality codes (e.g., `ch_foen.quality_a`, `ch_foen.quality_b`, `ch_foen.interpolation`) would express that as one `AnnotationSchema` with three `annotation_names` and no per-name typing.
- Under architecture.md §13, the provider would declare three `AnnotationSchema` objects, each carrying `value_type` and `allowed_values` for the one annotation it describes.

The plan's reading also makes `value_type` and `allowed_values` per-annotation impossible to express, which contradicts the architecture rule that providers declare typed annotation schemas before emitting names. Step 05's `validate_annotation_names` would need to be redesigned once the per-annotation typing arrives.

Either follow architecture.md §13 directly, or log a docs/discoveries.md D3 entry justifying the table-schema reading and queue an architecture.md §13 addendum. Do not silently absorb the divergence.

### M4. `ObservationRequest` is missing `provider_id`

architecture.md §11 lines 458–464:

> Core fields:
> ```text
> provider_id
> stations
> products
> start
> end
> ```

The plan's `ObservationRequest` has `stations`, `products`, `start`, `end` — no `provider_id`. The omission is not acknowledged in the plan's open questions, §8 deferrals, or §9 stopping conditions.

Downstream coherence consequence: `ObservationProvenance` carries `provider_id: ProviderId` as a *required* field (§3 line 92). Step 05's `_ProviderHandle.observations()` would have to pass `provider_id` alongside the request rather than reading it off the request. That is exactly the "request is self-describing" property the §11 list exists to provide.

Acceptable resolutions: (a) add `provider_id: ProviderId` to `ObservationRequest`; (b) explicitly defer it to step 05 with a justification and a discoveries entry. The plan does neither.

### M5. `start`/`end` as `object` contradicts architecture.md §3 and §11

architecture.md §3 line 130:

> Public methods may accept timestamp-like inputs, including ISO strings, but internal `ObservationRequest` objects contain typed temporal values.

architecture.md §11 line 468:

> `start` and `end` are typed temporal values. They are required in V1.

docs/design/provider-redesign.md line 95:

> [...] the internal `ObservationRequest` passed to providers should contain typed temporal values such as `pd.Timestamp`, and duration or resolution fields should use typed objects such as `pd.Timedelta`.

The plan keeps `start: object` and `end: object` (§3 line 58–59, line 66, Q2 line 336). The plan's defense ("Architecture time semantics belong in product metadata, annotations, provenance, and issues, not in product-ID parsing or eager request narrowing") elides what architecture actually says: not that time *semantics* belong in the request, but that the temporal *values* are typed. Those are different claims.

Acceptable resolutions: (a) pin to `datetime` or `pd.Timestamp` per architecture; (b) split the typed-coercion work into step 05's public-handle entry point and document the deferral here with a stopping condition and a discoveries entry. The plan does neither — it silently relaxes the architecture commitment.

### M6. UTC-mandate contradicts architecture.md §16

architecture.md §16 line 624:

> RivRetrieve preserves provider-native timestamps by default. It should only shift or reinterpret timestamps when the provider-specific convention is documented and the conversion is recorded.

architecture.md §16 line 626:

> Timezone facts belong in series annotations.

docs/design/provider-redesign.md line 383 elaborates: keep UTC when provider gives UTC, resolve from coordinates when provider gives local, `timezone="unknown"` annotation when not resolvable.

The plan pins `timestamp: pl.Datetime(time_zone="UTC")` as the canonical dtype (§3 line 195, line 200) and acknowledges "this is stricter than architecture.md's 'timezone-aware when possible' wording." That misreads the harder rule, which is *preserve native by default*. Under the plan, every `ch_foen` observation row must be in UTC, which forces provider-side conversion for any non-UTC source and silently drops the "preserve native" commitment.

Acceptable resolutions: (a) use `pl.Datetime(time_zone=None)` and let providers preserve native zones, recording the actual zone in series annotations per arch §16; (b) use `pl.Datetime(time_unit=...)` without a fixed timezone and let validation accept either tz-aware or tz-naive, with conversion facts annotated. The plan picks the strictest option and explicitly diverges from architecture without queuing an architecture addendum.

---

## Minor

### m1. Asymmetric typed wrapper: `AnnotationTable` exists, `ObservationTable` does not

architecture.md §12 line 491 names `data=ObservationTable`. The plan introduces `AnnotationTable` as a typed wrapper (frozen dataclass binding `pl.DataFrame` + schema) but leaves `ObservationResult.data` as a bare `pl.DataFrame`. Either name the wrapper (and pin its validation behavior consistently with `AnnotationTable`) or note explicitly why the asymmetry is intentional (e.g., "ObservationTable is the canonical column set itself; the result's data is always validated against `ObservationDataSchema`, so a wrapper would only add indirection"). Decide and document.

### m2. `validate_annotation_names` is name-set-only; arch §13 implies value-type and allowed-value validation too

Architecture's annotation schema has `value_type` and `allowed_values` fields. The plan's validator only checks declared-name membership. Even if richer validation is deferred to step 05/M4, the validator's scope should be declared (this function checks names; `value_type` / `allowed_values` validation is deferred to step N). Avoids future ambiguity.

### m3. Pydantic with `pl.DataFrame` field needs `arbitrary_types_allowed=True`

`ObservationResult` is a Pydantic `BaseModel` with `data: pl.DataFrame` (§3 line 162). Pydantic 2 rejects unknown types unless `model_config = ConfigDict(arbitrary_types_allowed=True)`. M1's `CatalogResult[T]` works because `T` is generic. The plan does not address this; the executor will hit it during step 04 implementation. Add it to the §3 plan-of-record so the executor doesn't have to invent it.

### m4. Empty-string ID coverage missing in T54

Q3 (line 340) says "missing dates, missing/empty station/product collections, wrong collection types, non-string IDs, *and empty-string IDs*" all map to `InvalidObservationRequestError`. The test inventory has T54 (`rejects_non_string_sequence_members`) but no test that empty-string `""` station/product IDs raise. §3 line 80 says empty-string IDs should be rejected; no T-number covers it. Add a test or fold it into T54's enumeration.

### m5. "if useful" in §6 step 8 is ambiguous for a load-bearing helper

§6 step 8: "Extend `observations.py` with `validate_observation_data` if useful". The `ObservationResult` constructor uses it; it's not optional. Replace "if useful" with a concrete decision (in or out, and what `ObservationResult.__init__` calls). Affects executor scope.

### m6. Plan does not require `polars.testing.assert_frame_equal` in T75 round-trip identity test

T75 says `result.to_polars() is result.data`. With Pydantic frozen `BaseModel` + `arbitrary_types_allowed`, attribute access returns the original object (no copy), so `is` should hold — but if the implementation accidentally rebuilds the frame in `to_polars()`, this test catches it. Good. T76 (`to_pandas_matches_polars_boundary_conversion`) should specify `pandas.testing.assert_frame_equal(result.to_pandas(), result.data.to_pandas())` so the boundary-only conversion is exact. The plan mentions "pandas equality helpers rather than manual element-wise checks" (§6 step 9), which is fine but worth pinning concretely.

### m7. `RawPayload.content_type: str | None`, `content: bytes | str | None` — JSON-string convention vs binary inconsistency

`metadata: str | None` is JSON-encoded (consistent with M1's catalogue metadata wire convention from D2 §1). But `content` is `bytes | str | None` for the raw provider payload. The two encodings live in the same dataclass without a stated rule for when `content` is `bytes` vs `str`. Likely fine in practice (provider chooses based on payload), but the plan should pin it explicitly: e.g., "`content` is provider-native bytes for binary payloads, text for JSON/text responses; `content_type` distinguishes them."

---

## Nits

### n1. T-number consistency

T46-T78 (33 numbers) but plan says "about 31 tests" with parametrization. Reconcile (parametrized cases can keep their T-numbers as docstring/comments).

### n2. Q9's claim about §12 wording is partially miscited

Q9 line 364 says "exactly `station_id`, `product_id`, `timestamp`, and `value`". As shown in M1, arch §12 names `time`, not `timestamp`. Once M1 is fixed, this citation becomes accurate.

### n3. ObservationProvenance fields list is a superset of architecture §14

architecture.md §14 lines 569–577 lists: provider ID, request parameters, requested/retrieved timestamps, RivRetrieve version, catalogue version, provider calls made, endpoint/query/status metadata. The plan adds `time_windows` and `decomposition` (§3 lines 95–96) — defensible per arch §17's "provenance records every source/API call" but worth noting these are step-04 plan-of-record additions, not direct arch citations.

### n4. `_ProviderHandle` is still private per M1 §7.5; the plan does not promote it. Good.

### n5. §6 step 13 references `bump-my-version bump patch`, which is correct per D1.

---

## Lens Summary

| Lens | Status | Notes |
|---|---|---|
| L1 scope completeness | ✓ | All 6 types + validator + fatal exception + T23 list update covered |
| L2 scope over-reach | ✓ | No `_ProviderHandle.observations()` body, no provider-module changes, no public surface |
| L3 citation verification | ✗ | Q9 misreads arch §12 column name (`time`, not `timestamp`); Q4 misreads arch §13 AnnotationSchema concept |
| L4 test coverage | ◐ | Fatal coverage good; empty-string ID test missing |
| L5 error handling | ✓ | All fatals direct-raise, no `apply_on_issue` routing |
| L6 open question rigor | ✗ | Q4 (AnnotationSchema) and Q9 (canonical schema) misalign with architecture |
| L7 deferral hygiene | ✓ | Each §8 deferral genuinely later-step |
| L8 implementation order | ✓ | Each intermediate keeps pytest green |
| L9 stopping conditions | ✓ | Comprehensive, covers the right tripwires |
| L10 architecture commitment compliance | ✗ | §3 (typed temporal), §11 (provider_id, typed temporal), §12 (column names), §13 (AnnotationSchema fields), §16 (preserve native timestamps) all diverge |
| L11 speculative abstraction | ✓ | No unauthorized extension points |
| L_two_channel | ✓ | Every fatal subclasses `FatalContractError`, raises direct, parametrized over `on_issue` |
| L_schema_representation | ✓ | Reuses `CatalogueColumn`/`CatalogueSchema` directly; no parallel column type |
| L_canonical_long_table | ◐ | No provider_id ✓; explicit dtypes ✓; explicit nullability ✓; timezone over-pinned to UTC ✗; column name `timestamp` vs arch `time` ✗ |
| L_six_field_observation_result | ✓ | Exact six fields, no extras, no omissions |
| L_m1_inheritance | ✓ | (1) two-channel ✓ (2) schema rep ✓ (3) opaque metadata N/A (4) T22/T23 ✓ (5) offline-import ✓ (6) `_ProviderHandle` private ✓ (7) ProviderInfo row contract untouched ✓ |

---

## Adversarial Probes Attempted

1. **"Does the plan invent ObservationTable as a wrapper?"** — No. `data: pl.DataFrame`. AnnotationTable is wrapped but data isn't. Asymmetric (m1) but doesn't violate arch §12.
2. **"Does the plan smuggle provider_id into observation data rows?"** — No. Canonical schema is `{station_id, product_id, timestamp, value}` with no provider_id. Honors arch §12 line 485, tracker §2 L25.
3. **"Does the plan let `to_pandas()` reshape, widen, or merge annotations?"** — No. `self.data.to_pandas()` only. Honors tracker §19.
4. **"Does the plan promote `_ProviderHandle` or add observation method bodies?"** — No. Stopping condition explicitly blocks it (§9 line 397, line 398).
5. **"Does any fatal failure route through `apply_on_issue`?"** — No. Plan §4 line 219 is unambiguous.
6. **"Does the validator design assume step 05's handle method exists?"** — No. `validate_annotation_names(table, schemas)` takes a table and a sequence of schemas; the caller chooses. Step 05 can call it; step 04 can test it standalone.
7. **"Does the plan check column names against the actual architecture document?"** — *Failed adversarial check.* The plan uses `timestamp`/`annotation_name`/`annotation_value` everywhere; architecture uses `time`/`annotation`/`value` everywhere. Q9 cites §12 but does not quote it.
8. **"Does the plan honor the typed-temporal commitment?"** — *Failed adversarial check.* arch §3 and §11 explicitly say internal `ObservationRequest` has typed temporal values; the plan keeps them as `object`.
9. **"Does the plan let `RawPayload` carry secrets?"** — No. Provenance secrets rule cited at §3 line 102 and stopping condition at §9 line 404. Plan's `RawPayload.content: bytes | str | None` could theoretically hold raw provider responses including auth headers if a careless provider sticks them in — but that's a step-05+ implementation concern, not a step-04 design defect.
10. **"Does the plan introduce a new `AnnotationColumn`?"** — No. Plan §3 line 127 explicitly says "Do not define `AnnotationColumn`. Reuse `CatalogueColumn` directly." Good.
11. **"Does AnnotationSchema match arch §13?"** — *Failed adversarial check.* arch §13 lists `{annotation_id, description, value_type, allowed_values, source_field}` per-annotation declaration; the plan defines a table-schema-with-name-set instead.
12. **"Does ObservationRequest carry provider_id per arch §11?"** — *Failed adversarial check.* Plan omits it without acknowledgment.
13. **"Does Pydantic actually accept `pl.DataFrame` as a field type without config?"** — No, it doesn't. Plan doesn't mention `arbitrary_types_allowed=True` (m3). Minor — executor will surface it during step 04.
14. **"Could the legacy divergence note (§1 line 19) be misread as authorizing the divergences in M1–M6 above?"** — No. The legacy-divergence note is about the *required-dates* and *long-form* divergences from legacy, not about column-name or typed-temporal divergences from current architecture. Those latter divergences are not surfaced anywhere in the plan.
