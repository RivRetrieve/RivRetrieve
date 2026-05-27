# 02-catalogue-schemas — Critique (Round 3 — final)

## Verdict

DISPATCH AS-IS

Round 2's fold-ins all landed in plan.md and verified:

- §3 line 65: "must check that non-null metadata strings parse as JSON objects" (was "may check").
- T13 (line 204): "constructed in memory, with the same shape `provider.json` will produce" — no file I/O, no loader pulled into step 3.
- §4 line 163: dropped the redundant "or null" branch from the metadata corruption mode.

Both Round 1 Majors remain resolved (verified via parquet round-trip in the project venv). No new findings. Plan is ready for the executor.

---

## Round 2 critique preserved below for the executor handoff record.

---

# 02-catalogue-schemas — Critique (Round 2)

## Verdict

DISPATCH WITH MINORS FOLDED

Both Major findings from round 1 are resolved. Round-tripped the revised dtype combination through Parquet in this repo's venv to confirm:

```
pl.Utf8 (provider/station ids, metadata) + pl.Enum(...) (availability)
write_parquet → read_parquet → schema preserved (availability stays Enum)
```

Two small wording clarifications are worth folding before dispatch. Nothing blocks.

---

## Major findings (resolved)

### M1 (was: `pl.Object` cannot be written to Parquet) — FIXED

§3 line 65 and line 85 replace `pl.Object` with `pl.Utf8` JSON object strings. Q6 (lines 287-289) re-argues the choice against Parquet compatibility, names the rejected alternatives (`pl.Object`, `pl.Struct`, drop-from-Parquet), and pins canonical JSON encoding. §9 line 334 adds the matching stopping condition. The verification ran cleanly under Polars 1.40.1.

### M2 (was: §4 fatal modes missing tests) — FIXED

Cross-walked §4 against §5 again. Every fatal mode now has a named test:

| §4 mode | Covered by |
| --- | --- |
| Missing artifact directory | T16 |
| Path exists but is not a directory | T17 |
| Missing required file | T18 |
| Unparseable `provider.json` | T19 |
| `provider.json` not a JSON object | T20 |
| Parquet unreadable | T21 |
| Missing required column | T22 |
| Wrong dtype | T23 |
| Non-nullable null (artifact path) | T24 |
| Metadata non-object JSON | T25 (artifact path), T12 (direct) |
| Invalid `availability` | T26 |
| Duplicate station key | T27 |
| Duplicate product key | T28 |
| Duplicate station-product key | T29 |
| Duplicate provider-info key | T30 |
| Provider-ID mismatch | T31 |
| Dangling station-product station FK | T32 |
| Dangling station-product product FK | T33 |
| Corrupt under `on_issue="ignore"` | T34 (the R1 vector, still present and correctly named) |

---

## Minor findings (round 1 resolutions confirmed)

- **m1 (validator file location)** — FIXED. §2 line 48 and §6 step 2 both pin `validate_catalogue` to `schemas.py`.
- **m2 (Q8 loader cast behavior)** — FIXED. Q8 (lines 295-297) now specifies: accept exact `pl.Enum`, or cast `pl.Utf8` → `pl.Enum`, wrapping cast failures in `CorruptCatalogArtifactError`; any other dtype is a schema mismatch.
- **m3 (`name` inferred, not architecture-named)** — FIXED. §3 line 129 marks `name` as inferred.
- **m4 (`catalogue_version` duplicates `CatalogProvenance.catalogue_version`)** — FIXED. §3 line 134 acknowledges the duplication and hands the mismatch-detection invariant forward to M2/M3.
- **m5 (Q11 fixture strategy depends on M1)** — FIXED. Q11 (line 309) explicitly ties the `tmp_path` strategy to the Q6 `pl.Utf8` metadata choice.
- **m6 (§9 missing stop for `Issue(severity="error")` corrupt-encoding)** — FIXED. §9 line 337 now stops if any §4 fatal failure is modeled as a recoverable Issue.

---

## New minor findings (round 2)

### r2.m1. §3 line 65 wording: "may check" leaves T12 unguaranteed

§3 line 65 reads: "The validator **may** check that non-null metadata strings parse as JSON objects." But T12 (`test_metadata_column_rejects_non_object_json`) and T25 (`test_packaged_artifact_metadata_non_object_json_raises_corrupt`) require the validator to perform that check — otherwise both tests fail. Either tighten the wording to "**must** check that non-null metadata strings parse as JSON objects" (so the executor knows it's a requirement), or downgrade T12/T25 to deferred tests. Tightening is the correct call given §4 line 163 already lists this as a fatal mode.

**Fold-in fix:** §3 line 65 — change "may check" to "must check that non-null metadata strings parse as JSON objects, but must not".

### r2.m2. T13 wording risks pulling the loader into step 3

T13 reads: "a one-row provider info DataFrame **created from `provider.json`** validates against `ProviderInfoCatalog`." Read literally, that requires `provider.json` parsing — which lands in step 4 (`artifact.py`), not step 3 (`schemas.py`). The intended meaning is almost certainly "a one-row DataFrame of the shape the loader will produce." If the executor reads it literally and pulls JSON parsing into `schemas.py`, that's scope drift and an ordering inversion.

**Fold-in fix:** T13 rephrase to "a one-row provider info DataFrame constructed in-memory (no file I/O) validates against `ProviderInfoCatalog` and matches the shape `provider.json` will produce."

---

## Nits

- §4 line 163: "Metadata column contains a non-JSON string, a JSON non-object such as `[]`, or null". The "or null" branch is already covered by the generic non-nullable check on `metadata`. Harmless overlap, but a reader could think `metadata` is nullable here. Drop the "or null" or note that nullness is rejected by the generic non-nullable rule.
- §3 line 65 also says "Later public/provider adapters may decode this field to plain dictionaries at public table boundaries; M1 does not introduce that public surface." Good guard text; keep.

---

## Lens-by-lens summary (round 2 deltas only)

- **L4 Test coverage adequacy:** ✅ — now ✅ (was ❌). Every §4 fatal mode is covered; R1 vector T34 unchanged.
- **L6 Open question rigor:** ✅ — Q6 and Q8 both substantially improved.
- **L8 Implementation order:** ⚠️ — green-at-each-boundary holds in spirit, but r2.m2 (T13 wording) could mislead the executor into pulling JSON parsing into step 3.
- **L9 Stopping conditions:** ✅ — both the Parquet-Object stop (line 334) and the corrupt-as-Issue stop (line 337) are now explicit.
- **L10 Architecture commitment compliance:** ✅ — Polars-canonical holds; metadata stays "opaque" in the sense of not parsing nested keys, while shape-checking (object vs array vs scalar) is a bounded structural check explicitly scoped by §3 line 65.
- **L12 Polars-1.40 risk:** ✅ — verified `pl.Utf8` + `pl.Enum` + `pl.Utf8` metadata round-trips through Parquet in the project venv.
- **L17 Forward-compat with M3 generation:** ✅ — M3's `generate_catalogue.py` can now produce Parquet artifacts with JSON-string metadata under the same Polars version.

All other lenses unchanged from round 1's positive assessments (L1, L2, L3, L5, L7, L11, L13, L14, L15, L16).

---

## Adversarial probes run this round

- **Reproduced the corrected dtype Parquet round-trip** in the project venv: `pl.Utf8` (provider_id/station_id/metadata) + `pl.Enum(['available','unavailable','unknown'])` (availability) writes and reads back with Enum dtype preserved.
- **Cross-walked every §4 fatal mode against the §5 test list** — full coverage, including the previously missing modes (missing-dir, path-not-dir, JSON-not-object, non-nullable artifact-path null, duplicate product key, duplicate provider-info key, dangling FK both directions).
- **Re-read §3 line 65 against T12/T25** — caught the "may check" ambiguity (r2.m1).
- **Re-read T13 against §6 step ordering** — caught the loader-creep risk in step 3 (r2.m2).
- **Confirmed §9 stop list against the round-1 R1 vector** — line 337 directly addresses the "encode corrupt as Issue severity=error" regression.
- **Re-checked architecture.md §7 line 255 ("Generic harness code treats `metadata` as opaque")** against the plan's new "validator parses metadata to check JSON-object shape" behavior. The plan correctly bounds the check to structural shape and explicitly forbids inspecting nested keys; this is a defensible interpretation, not a contradiction.
