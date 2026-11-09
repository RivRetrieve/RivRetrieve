# Reproduce the source annotation experiment

The recommendation is in [../recommendation.md](../recommendation.md). These patches are experiments, not production migrations. Neither is applied to shipped runtime by this artifact-only change.

## Final linked candidate

- Base: `e7518740884a37d5ef12080d6a012a271e76247c`.
- Patch: `provider-adapters-fixed.patch`.
- SHA-256: `48b97307ba475a34db6e353e4c4485d66bd5c50808af845544106b3645a61634`.
- Experimental accumulated-store version 109; bundle version 103. Use temporary stores only; no compatibility or migration claim.

From the repository root, create a disposable worktree below `.worktrees/`, then apply the exact patch:

```sh
git worktree add --detach .worktrees/source-annotations-reproduction e7518740884a37d5ef12080d6a012a271e76247c
cd .worktrees/source-annotations-reproduction
git apply --check /absolute/path/to/provider-adapters-fixed.patch
git apply /absolute/path/to/provider-adapters-fixed.patch
uv run pytest --logic-only tests/test_annotation_usgs_adapter.py tests/test_annotation_nve_adapter.py tests/test_annotation_mlit_adapter.py tests/test_annotation_bundle_experiment.py tests/test_annotation_refresh_experiment.py tests/test_annotation_scope_experiment.py tests/test_linked_annotations_experiment.py tests/test_usgs_modern_parse.py tests/test_usgs_continuous_cache_axis.py tests/test_jp_mlit_acquisition_prerequisites.py tests/test_no_nve_public_routes.py tests/test_jp_mlit_chunk_isolation.py tests/test_independent_fact_cache.py tests/test_source_series_store.py tests/test_source_series_bundle.py -q
uv run ty check src
```

The owner run passed 210 tests with 56 source-backed tests deselected. An independently reviewed wider provider selection passed 210 with 107 deselected. Both typechecks passed. Deselection is explicit absence of evidence from those tests, not a pass. Safe synthetic tests exercise actual runtime components, including semantic-corruption controls; source-independent payloads are not publisher observations.

Private replay requires the archive's exact collections, separately reviewed harness/launcher, restricted output paths and exact runtime hash. Do not run arbitrary private inputs through this patch based solely on these commands. Reviewed bounded offline runs covered 4,291 USGS observations, one NVE observation and 648 MLIT slots. Originals and detailed outputs are not distributed publicly. Reviewed acceptance records and reproduction pins are retained in [private archive handoff #87](https://github.com/RivRetrieve/verification-evidence/pull/87), requiring maintainer access. Its public-artifact commit pin records the reviewed historical revision; later handoff prose does not rewrite that identity. Original association/reuse/clipping/bundle checks passed; authored refresh changes and injected failures are separately labelled synthetic evidence.

## Alternatives retained

`typed-shapes.patch` is the earlier typed-column actual-engine candidate at the same base, SHA-256 `e37d4dfb07df421086003d58764ceb8987d52db65bc87ea1c442b0e8bab7d06a`. Apply it to a **different** clean disposable worktree, never on top of the linked patch. Run its `tests/test_annotation_shapes_experiment.py`, `tests/test_annotation_columns_experiment.py`, `tests/test_independent_fact_cache.py` and `tests/test_source_series_store.py` with `uv run pytest --logic-only`. Its 58 passing cases prove bounded heterogeneous-column retrieval/cache behavior, not complete lifecycle or genuine provider fit.

The inexpensive columns/linked/long/JSON comparison is standalone:

```sh
uv run pytest --logic-only planning/experimentation/source-annotations/test_candidates.py -q
```

It has 13 synthetic cases and is not an alternative cache implementation. Historical intermediate patches, exact red/green logs and review receipts remain in external investigation history; they are not duplicated as maintained public interfaces.

## Limits

The final candidate uses provider-typed slot tables, derived joins and immutable acquisition references. Field definitions currently expose unknown meanings/references; source understanding still needs a curated, evidenced presentation. Slot scope is not an interval or whole-series annotation. Cross-page duplicate identity, snapshot annotations, IANA reconstruction and representative national-scale costs remain unproved.

IPC-in-manifest was the smallest integrity-bound encoding for the experiment. Whole-table rewrites and eager full-partition semantic reads mean it is not a production layout recommendation. No runtime patch in this directory is authorized for production adoption.
