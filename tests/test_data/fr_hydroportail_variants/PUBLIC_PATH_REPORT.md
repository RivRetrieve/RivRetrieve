# Independent live public-path verification

Ran from existing `.worktrees/visions/effort-311-hydroportail-variants` through `uv run python` on 2026-09-21. No new checkout or production edit.

`verify_public.py` passed 10 public `rr.fetch` calls: unrestricted plus each of the four explicit variants, separately for discharge and stage at Y251002001, 2020-01-01..2020-01-02. Discovery exposed eight distinct Q/H definitions. Sixteen actual source calls returned the requested selectors, Q/H metric and engine-padded 30/12/2019..04/01/2020 window. Assertions inspected actual `provenance.calls_made.request_parameters`, receipt envelopes and public series identities, not output labels alone.

For each quantity, unrestricted output retained 726 rows across all four identities. Raw retained 576 rows; validated, pre_validated_and_validated, most_valid each retained 50. Explicit calls acquired exactly one named selector, without substitution. The only issues were existing informational `provenance.license_not_established` and `provenance.citation_not_established`; no warning/error occurred.

`public-path-output.txt` contains exact successful run output. `public-path/` retains full JSON provenance, source receipt bodies with SHA-256 and origin metadata, series/data Parquet files, and summary. `verify_public.py` is executable from the implementation checkout. Its optional `--offline` mode replays the separately captured padded recordings for verifier checks; the reported successful final run did not pass `--offline`.

Two initial script-only interruptions each made four unrestricted-Q source calls: the first incorrectly rejected expected informational issues; the second attempted dataclass deep-copy serialization of an immutable mapping. Both errors were repaired in the verifier, then all cases passed using replay before the final live run. Those incomplete attempt outputs remain separate. Total public-path acquisition attempts made 24 source calls, including the final 16-call successful run. They revealed no provider defect.

This live check intentionally uses one station. Independent direct Transport evidence covers both stations, including successful empty responses at 1232000101, with counts and interpretation limits in REPORT.md. No corrected or pre-validated positive witness or source selection algorithm was inferred.

## Reproduce without overwriting retained evidence

From the repository checkout:

```sh
uv run python tests/test_data/fr_hydroportail_variants/verify_public.py --out-dir .worktrees/evidence/hydroportail-public-fresh
```

The output directory must not already exist. The script writes JSON provenance, exact source receipt bytes, origin/hash metadata and Parquet data. Retained successful evidence is losslessly packaged in `tests/test_data/fr_hydroportail_variants/public-path.tar.xz`; its files remain unchanged from acquisition. To verify offline first, supply `--offline` and a separate new `--out-dir`; `--evidence-dir` optionally selects the source recording directory and otherwise defaults to the script's directory. Offline checks do not establish current source availability.
