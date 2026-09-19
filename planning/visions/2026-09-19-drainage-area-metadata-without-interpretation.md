# Drainage-area metadata without interpretation

## Outcome

Expose drainage-area and watershed-size metadata already packaged in RivRetrieve through `rr.drainage_areas(selection)`. This is an offline convenience for accessing source metadata, not a common drainage-area dataset or a scientific recommendation. Users need access even when some gauges have no available area value.

```python
import rivretrieve as rr

gauges = rr.find(provider="ca_eccc", product="discharge_daily_mean")
gauge = rr.pick(gauges, station="02GA010")
areas = rr.drainage_areas(gauge)
```

The same function accepts a selection containing many gauges and multiple providers. It returns a Polars DataFrame. No observation retrieval, credentials, downloads, or network access are required.

## Settled behaviour

- Expose only drainage-area or watershed-size metadata. Lake area, reservoir area, regulation area, and other unrelated area measurements are not part of this utility.
- Use the source's existing field names and preserve its values, distinct meanings, and any stored units. Do not convert units, standardize values, harmonize meanings, or assign a common area-kind vocabulary.
- Keep distinct source fields separate. Never rank them, choose a preferred area, substitute one for another, or infer an absent value.
- Preserve formatted source values such as `"123.4 km²"`; do not extract a number merely to make all providers fit a numeric column. Do not invent a separate unit when none is stored or already established in the repository.
- Identify the provider, station, source field, and source value in the returned table. Preserve existing unit information without introducing a unit-research task. The illustrative six-column table discussed during discovery is not a binding schema: in particular, no standardized `area_kind` is required.
- Keep every selected gauge visible. Preserve nulls in known source fields and distinguish those from a gauge for which no relevant metadata is exposed. Neither absence means zero or proves the agency publishes no drainage area elsewhere.
- Return each station's metadata once per `(provider_id, station_id)`, regardless of how many products are selected. This does not collapse separate source area fields into one value.
- An empty selection returns an empty DataFrame with the expected schema.

The exact frame layout and lossless representation of heterogeneous source values are implementation choices. A somewhat opaque source-oriented table is acceptable. A tidy numeric shape is not worth altering the source information. Use clear machine-readable representation for the two absence cases rather than silently dropping gauges.

## Existing evidence and implementation boundary

The current public API exports `find`, `pick`, and `as_frame` from `src/rivretrieve/_internal/discovery.py`. Selections contain unique provider/station/product triples. The existing map path already works at unique-station grain. Public discovery frames use Polars.

Provider catalogues contain `native.parquet` with source vocabulary and values. `CONTEXT.md` defines native tables as preserving the source's column names, spellings, units, and values. The canonical station catalogue remains unchanged by this work.

Canada's native table holds `DRAINAGE_AREA_GROSS` and `DRAINAGE_AREA_EFFECT`. At discovery time, the packaged row for `02GA010` held gross `1035.0` and effective `null`, not the illustrative values from the original proposal. This is a useful real packaged-data case for preserving multiple fields and an unknown value.

Other existing fields include USGS `drain_area_va` and `contrib_drain_area_va`, and Norway's `drainageBasinArea` and `drainageBasinAreaNorway`. These are pointers for inspecting existing package content, not authority to equate their meanings. Review all currently packaged providers using only existing files, code, tests, and documentation. Identify eligible drainage/watershed-size fields from that evidence. Do not select arbitrary fields merely because their names contain "area", and do not guess the meaning of ambiguous fields. Preserve an explicit absence when existing evidence does not establish an eligible field.

There is no additional source research in scope. Do not query agencies, seek new source documentation, add endpoints, acquire new metadata, or refresh catalogues to increase coverage. Coverage is limited to what the package and repository already establish. Do not require a provider to supply area metadata before supporting its selection.

## Evidence of success

Local tests and the public example establish that:

- A single-gauge call exposes the existing Canadian source fields and preserves the packaged null.
- Batch calls preserve every selected gauge, distinct provider identities, and distinct source fields, without duplicating metadata for multiple selected products.
- Gauges with no exposed drainage metadata remain distinguishable from gauges whose existing area fields contain nulls.
- Source strings and numeric values retain their information without conversion or harmonization; available unit information is retained.
- Empty input has a stable empty schema, and calls work without network access or credentials.
- Unrelated area fields do not enter the result, and canonical catalogue facts are not changed.

Use real packaged metadata where available. Follow repository testing and design rules. Explain the function, its source-oriented output, and its limited coverage in software API documentation. Do not expand this into a provider-documentation research or rewriting project. Use local validation; this work does not authorize introducing or enabling hosted CI.

## Exclusions and Jev authorization

No scientific interpretation, preferred drainage area, automatic fallback between area kinds, discharge normalization, delineation, or computed watershed area is included. Pourpoint integration is explicitly out of scope. Do not create an extension mechanism for it in anticipation of future work. A general station-metadata API and quality-flag work are also outside this change.

The user explicitly authorizes Jev use for authoring and implementing this vision, including advisory semantic checks and independent-review support through TypeSafe's hosted service. This authorization covers minimized, reviewed, non-sensitive requirements, draft, repository-code, and validation excerpts relevant to this work. It does not authorize sending credentials, private personal information, unrelated material, or whole repositories. Jev remains advisory: its output cannot alter source metadata, choose scientific meanings, approve publication or merges, or replace independent review and deterministic validation. Do not add Jev as a runtime dependency or make this offline API call a hosted model. If Jev is unavailable, continue through normal reasoning, review, and validation.

This is a standalone vision. Publication authorizes no implementation by itself; implementation requires a separate invocation.
