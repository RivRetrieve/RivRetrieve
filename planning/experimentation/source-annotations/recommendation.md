# Recommendation: typed source annotations linked to source slots

**Recommend provider-typed linked tables, with a derived measurement view and explicit source slots without measurements.** Three contrasting bounded genuine replays support this direction. This is an experimental design recommendation, not shipped functionality or authorization for production adoption.

## Start with the user experience

Users should first discover each field's original name, native type, publisher meaning/reference or explicit unknown, and applicable source series. Then inspect the typed table directly, or join measured annotations by occurrence ID for ordinary Polars analysis. Keep independent fields independent; no quality score, automatic exclusions or dedicated filtering language.

Illustrative candidate use (not a shipped API):

```python
result.annotations[0].fields          # field names and meanings, including unknowns
slots = result.annotations[0].rows   # includes source slots without measurements
measured = result.data.join(
    slots.filter(pl.col("occurrence_id").is_not_null())
         .select("occurrence_id", "approval_status", "qualifier"),
    on="occurrence_id", validate="1:1",
)
chosen = measured.filter(
    pl.col("approval_status").struct.field("value") == "Approved"
)
```

The last expression is a user's choice, not a scientific recommendation. Qualifier retains its native scalar/list distinction and field presence separately from null. Field meanings must be source-backed, not inferred from code labels. The prototype currently carries unknown explanations; preservation alone does not finish the discovery goal.

## Why linked typed tables

One authoritative typed table per declared source schema avoids forcing unlike fields into one widened measurement struct. Occurrence links preserve distinct series, equal-time observations and duplicate multiplicity. A source slot can have no measurement link: this represents published annotation content, not a fabricated null measurement. Native slot coordinates remain unchanged during physical conversion/UTC views. The convenient measured frame is derived, never a second mutable copy.

Typed row columns worked for one schema through actual cache reuse. Heterogeneous series required struct unions and special empty paths, while unmeasured source slots still required a separate relation. Long typed cells preserved values but added reconstruction joins; JSON deferred decoding/type work rather than improving understanding. These alternatives remain inspectable in the small synthetic candidates and frozen column patch.

## Contrasting provider fit

- USGS: separate approval_status and qualifier; preserve presence, null and scalar/list shape. Retained OpenAPI/schema documents declare string while selected retained daily responses contain lists. Their applicability and temporal relationship remain unresolved; this is not a fresh current-service contract check. Do not coerce away the difference. Repeated-delivery identity across pages remains unresolved; acquisition-local ordinals are not publisher IDs.
- NVE: quality and correction remain independent integer codes; series versions remain identity, not optional quality annotations.
- MLIT: missing markers can accompany numeric-looking source cells that do not become measurements. Source-slot inspection is necessary. Exact marker whitespace is retained. Display aliases for DAT marker/row/pair coordinates are not native JSON field names; reconstructed labels are not byte-exact receipts.

Reviewed offline replay matched independent original-derived expectations for 4,291 USGS daily observations, one NVE observation and 648 MLIT source slots, including unmeasured slots. No interval or whole-series annotation scope is established by these observations; source file grain and library summaries do not establish such scope.

## Provider authoring and trade-offs

At the existing native parse loop, emit a typed source-slot row and, when the source establishes a measurement, its occurrence link. Keep original source fields, native presence/null/shape and acquisition reference. Declare each extracted field once; unknown meaning stays unknown. Separate schema IDs avoid combining identically named fields with unrelated meanings. Link validation checks series/facts and native coordinates; retirement follows existing successful coverage, not observed row density. Failed requests cannot retire held slots.

This costs an explicit validated join for the familiar measurement view and more metadata than row columns. In return, it avoids widening heterogeneous measurement structs and represents MLIT missing slots without a second annotation truth. The prototype's one-slot-per-measured-occurrence join is a scoped constraint, not a universal claim about publishers. Production schema evolution and source record identity need design decisions before adoption.

For #602, transfer original names, native types, explicit unknown meanings and discoverability. Do not assume station metadata needs occurrence links, source-slot storage or the same API.

## What was actually tested

The reviewed isolated patch exercises real driver retrieval, atomic accumulation, network-free reuse, annotation-only refresh, empty/no-slot versus unmeasured-only results, failed and partial refresh, overlapping failed subwindows, clipping, pick, fixed-offset UTC and actual bundle roundtrip, with receipts omitted. Tests assert coordinate/occurrence associations and reject malformed links, field declarations and unsupported acquisition references. Provider loops preserve native types and source-series identity. Synthetic changed responses/failures are not genuine changed publisher observations.

The exact reviewed runtime patch and base are pinned in the reproduction guide. Owner combined run: 210 passed, 56 source-backed tests deselected; independent wider selection: 210 passed, 107 deselected. Typecheck passed. Deselected tests are not acceptance evidence. Genuine replay used separately reviewed private code, exact retained originals, isolated roots and closed transport. All three bounded runs passed original association, zero-transport reuse, clipping and bundle roundtrip. Authored annotation-only refresh and failed transport controls also passed; these are synthetic changes, not genuine later publisher observations. NVE failed refresh legitimately added only an exact known catalogue fact on the unchanged series; prior facts and nonfact metadata remained exact.

## Costs and limits

IPC tables embedded in the integrity-bound manifest were a bounded experimental encoding, not a recommended production store layout. It rewrites whole tables and eagerly reads all partitions during semantic validation, including metadata paths. One ordered USGS run measured 0.973 s fresh acquisition/store publication, 0.255 s cache reuse and 0.177 s bundle export+import. Reuse followed warm preparation and equivalent outputs were checked. This is one sample without repetitions or alternative-representation comparison; it supports no national-scale or speed claim. Tiny four-slot encode/decode timings likewise cannot justify the layout.

Before adoption: settle source record/delivery identity; define independently evidenced slot replacement scope; choose durable partitioned storage and decode validation; complete published meaning/discovery UX; decide unproved snapshot/IANA/mixed-schema edges from actual needs. Do not adopt a universal metadata framework. Transfer source-name/type/unknown/discovery lessons to #602, not this storage model by default.

## Handoff and adoption decisions

The three planned contrasting bounded replays now pass. Return this recommendation to #621 for maintainer/team design discussion, keeping that discussion open. The experiment does not authorize merging the runtime patch or migrating providers.

Team decisions: choose the public discovery/projection spelling; make source meanings and source references first-class rather than leave the prototype's unknown placeholders; settle record-versus-repeat-delivery identity and the supported scoped cases; replace or justify manifest IPC through representative costs; and authorize production work separately. Missing interval/whole-series evidence, snapshot annotations, IANA reconstruction and cross-page duplication remain explicit limits, not hidden supported features.

The [reproduction guide](integration/README.md) identifies the reviewed executable and safe controls. Source originals remain archive-bound; new detailed acceptance records are retained private execution records and still require durable archival handoff before full completion. No source bodies, credentials or detailed restricted outputs are included here.
