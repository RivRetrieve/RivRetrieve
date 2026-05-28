# 01-observation-foundations Critique

## Verdict

DISPATCH WITH MINORS FOLDED

The plan is overall sound. The token probe was actually executed against
the legacy checkout at the cited HEAD (`cd9b030`), the fixture-fact
assertions in §5 are derived directly from CSV bytes (not from legacy
wide-form pandas), the annotation-ID set aligns with the M3-declared
product catalogue without broadening canonical vocabulary, no module
path collides with a public callable (D6), and the parser intermediate
choice (frozen dataclass + Polars `DataFrame`) avoids both the D7
extras-allow trap and the §17 shared-backend-policy trap. The
deferrals in §8 are genuinely deferrable.

The findings below are tightenings, not contradictions. None of them
require a planner re-spin; an executor can fold them in. There is no
architecture-commitment violation, no canonical-vocabulary expansion,
no SwitzerlandFetcher-vs-arch contradiction, and no token-status
change to escalate.

## Major findings

None.

## Minor findings

### M1 — Step-01 client field set leaks step-02-only surface

Plan §3 "`ChFoenObservationClient`" declares `max_window_days: int =
366` and a `session: provider-private request session object` field
on the client shell. Plan §1 explicitly lists "366-day windowing,
live HTTP calls, retries, batching, or stitching" as out of scope.
Declaring `max_window_days` without using it is speculative carrying.
Declaring `session` forces a concrete typing decision: a
`requests.Session` annotation pulls the network dependency into
step-01 type signatures; an `Any` annotation defers ty's complaint to
step 02; a Protocol annotation IS the "shared backend abstraction"
the planner warns against in the same row ("type should avoid
introducing a shared backend abstraction"). The planner is
self-contradicting here.

**Concrete fix.** Drop `max_window_days` and `session` from the
step-01 client field list. Both belong with step 02's retrieval
code. The remaining fields (`endpoint`, `token`, `timeout_seconds`)
are sufficient to anchor the step-01 client shell and to test token
redaction in §5 test 9.

### M2 — Parser intermediate `time` column type is "either/or"

Plan §3 "Parser intermediate" `records` columns: `time` is
"Polars datetime with UTC-aware or UTC-normalized semantics", and
`window_start`/`window_stop` are "`str` or datetime preserving
explicit UTC". The parser intermediate is the contract step 02
consumes; step 02 cannot be designed against "or". Architecture.md
§16 ("preserves provider-native timestamps by default") plus the
fixture evidence (every `_time`, `_start`, `_stop` carries a literal
`Z`) is enough to pin a concrete choice now.

**Concrete fix.** Pin `time` to `pl.Datetime(time_unit="us",
time_zone="UTC")` and `window_start`/`window_stop` to the same
dtype. Drop the "or" alternatives. This is consistent with the
declared `resolved_timezone="UTC"` series annotation and avoids
asking the step-02 planner to re-litigate the same decision.

### M3 — `missing_required_column` / `malformed_csv` straddle fatal-vs-issue channels

Plan §3 lists `missing_required_column` and `malformed_csv` inside
the `ChFoenObservationIssueCodes` table (suggesting `Issue` channel,
i.e. recoverable). Plan §4 lists "Required columns are absent" and
"CSV reader cannot parse" as fatal parser failures (raise channel).
§5 test 7 has the parser "raise the chosen fatal parser exception
or returns the documented fatal path." This straddles the
two-channel exception contract codified in M1 step 01 and inherited
through M3 — fatal contract failures raise; recoverable issues go
into `Issue.code`.

**Concrete fix.** Pick one channel per code. Recommended:
`missing_required_column` and `malformed_csv` are fatal parser
exceptions whose `.code` (or equivalent attribute) carries the
string; `invalid_timestamp` and `invalid_numeric_value` remain
recoverable Issue codes because §4 already documents per-row drop
behavior. Move `missing_required_column` and `malformed_csv` into
the fatal-parser-exception list in §3 (separate from the issue-code
table), and reword §5 test 7 to assert the concrete exception
rather than "exception or documented path".

### M4 — §6 file order leaves a brief red state between items 10 and 11

Plan §6 item 10 updates `module.py` so `row_annotation_schema()` and
`series_annotation_schema()` return non-empty lists. Plan §6 item 11
updates `tests/test_ch_foen_module.py`, whose existing assertions
`assert ch_foen_module.row_annotation_schema() == []` (file lines 43-48)
will fail the moment item 10 lands and before item 11 lands. Plan §6
opening line claims "Implementation order must keep `uv run pytest`
green without network at every checkpoint." That invariant is
violated at the item-10 checkpoint.

**Concrete fix.** Either (a) swap items 10 and 11 so the test file
is rewritten first and starts asserting non-empty schemas before
`module.py` actually returns them — but this also red-states
between item 11 and item 10 because the new assertions don't yet
match the still-empty schemas — so prefer (b): collapse items 10
and 11 into a single ordered checkpoint that lands both edits
together. Make explicit in §6 that this is one atomic step, not
two.

### M5 — `build_flux_query` listed in step 01 with discretionary tests

Plan §3 "Methods to plan for" includes `build_flux_query(...)` in
the client and §5 test §9 / file §6 item 9 say "Add only
token-redaction/query-builder tests that do not touch network."
Plan §6 item 8 says "Add client scaffold and query builder if
included." The "if included" phrasing leaves the executor to decide
whether step 01 ships `build_flux_query`. Either way the code path
is step-02 surface: query string assembly with parameter
substitution drives network retrieval that step 01 does not
exercise.

**Concrete fix.** Defer `build_flux_query` to step 02 alongside the
network retrieval it serves. Step 01 ships a constructor-only
client shell sufficient to anchor the `token`-redaction test in §5
test 9 (executor passes a fake token literal, asserts it is not
echoed into any artifact the test reads). This avoids landing a
tested-but-unused query builder in step 01 and removes the "if
included" branch from §6.

### M6 — §1 and §2 disagree on what counts as "public behavior unchanged"

Plan §1 ships "`ch_foen` row and series annotation schema
declarations for the annotation names step 02 will emit", which
means `ProviderHandle.row_annotation_schema()` and
`ProviderHandle.series_annotation_schema()` change return values
from `[]` to non-empty lists. Plan §2 says "Provider-handle public
behavior: unchanged." Strictly, public schema method behavior does
change at the surface a caller sees. An executor reading §2 in
isolation might think nothing on the public handle should change
and skip the §1 deliverable, or alternately interpret §2 as license
to also change other public surfaces it shouldn't.

**Concrete fix.** Rewrite §2's second sentence to "Provider-handle
public observation behavior remains unchanged: the placeholder
result and the empty observation/annotation tables. Provider-handle
public annotation schema methods change return values from `[]` to
the declared row/series schemas in §3." This makes the in-scope vs.
out-of-scope cut at the method level rather than at the
handle-as-a-whole level.

## Nits

### N0 — D7 conditional test is dead text under the plan's own recommendation

§5 test 11 is gated on whether a Pydantic `extra="allow"` model is
introduced. Plan §3 explicitly recommends frozen dataclasses for
`ChFoenRawPayload` and `ChFoenParsedObservationPayload`. If the
executor follows the recommendation, test 11 is never written. If
the executor diverges from the recommendation, that divergence is
already gated by §9's stopping condition "Stop if D7 is violated by
testing `extra='allow'` Pydantic extras through constructor
kwargs". Drop §5 test 11 and let §9 carry the enforcement.

### N1 — VARIABLE_MAP line range citation off by one

Plan §3 cites `origin/switzerland:rivretrieve/switzerland.py:44-80`
for the VARIABLE_MAP. Actual range is 44-81 (the closing `}` is on
line 81). Adjust to `44-81`.

### N2 — `L/s` native unit string is a derivation, not a citation

Plan §3 derives `flow_ls` native unit as `L/s` and `flow` native
unit as `m3/s`. The legacy fixtures carry no native-unit column; the
legacy `_convert_units` only encodes the conversion as a numeric
division by 1000 (line 268). The mapping `flow_ls -> L/s` is
inferred from the variable name plus the conversion factor, not
read from source. Plan §7 Q7 already says "Native unit strings are
not present as CSV columns; derive unit expectations from the native
field mapping in the parser test helper" — surface this same caveat
in §3 so a reader does not mistake it for a legacy citation.

### N3 — Series annotation `provider_query_fields` JSON encoding inherits M2's asymmetric channel

The declared `value_type="json"` reuses the M2 row encoding where
`AnnotationSchema.to_row()` does `json.dumps(list(...))`. This is the
same asymmetric encoding D8 calls out (loader vs generator
serialization symmetry). Step 01 only ships the declaration so this
is fine at step-01 boundary, but step 02's executor will need to
remember that emitting `provider_query_fields` requires a JSON
dump before AnnotationTable construction. A one-line forward
pointer in plan §8 ("Step 02 must JSON-encode `provider_query_fields`
values before they cross the AnnotationTable boundary; see D8.")
would close the loop.

## Lens-by-lens summary

L1: ✅ — token probe (§3), schema declarations (§3), fixture commits
(§6 1-3), internal types (§3), parser scaffolding (§3,§4) all
present.

L2: ✅ with M1/M5 caveats — placeholder unchanged (§1, §2, §6
item 10), no wrapper, no windowing, no capability flip, no docs.
M1/M5 surface scope-creep on the client side that's contained to
declarations, not behavior.

L3: ✅ — products.parquet column set matches §3 table exactly; M3
REPORT §7.2 token line cited and independently re-verified at
legacy HEAD `cd9b030`; arch.md §16, §17 stay consistent with
§3, §8.

L4: ✅ — declaration tests (§5 1-2), fixture-presence (§5 3),
parser fixture tests with byte-derived facts (§5 4-6), fatal/
recoverable parser tests (§5 7-8), raw payload no-secret (§5 9),
issue codes (§5 10), T119/T120 negative controls (§5 12-13),
offline import (§5 14), M3 placeholder preserved (§5 15).
Conditional D7 test (§5 11) is structurally dead — see M6.

L5: ✅ with M3 caveat — fatal vs recoverable taxonomy is articulated
in §4, but the channel assignment of `missing_required_column` and
`malformed_csv` straddles both channels per §3 and §4. M3 fix
above closes the gap.

L6: ✅ — §7 Q1-Q7 each cite either products.parquet (for product
ID coverage), the legacy source by file:line, the fixture bytes, or
arch.md §12-§17. No recommendation rests on vibes.

L7: ✅ — each §8 deferral has a hard rationale tying it to the next
specific step or to arch.md §17. The parser shape in §3 keeps step
02 free of a shared backend-policy abstraction (frozen dataclass +
`pl.DataFrame`, not a generic adapter).

L8: ⚠ — M4 above: items 10 and 11 must collapse or the executor
red-states pytest between them.

L9: ✅ — §9 covers token rotation, vocabulary creep, shared backend
abstraction, timezone drift, package-root shadowing, M3 placeholder
preservation, D7/D9, and secrets-in-artifacts. Adequate for step
01's failure modes.

L10: ✅ — arch.md §0 (no speculative abstractions; tightening M1
above), §9 (no public provider class), §11-§13 (annotation
declarations match the declared-before-emit contract), §15
(two-channel exception hygiene; tightening M3 above), §16 (UTC
timezone preserved), §17 (backend policy stays provider-internal).
No commitment weakened.

L11: ⚠ — M1 above: speculative client fields. Mostly contained.
No new shared abstraction, no second provider hooks, no provider-
specific result/issue type duplicating shared ones.

L_two_channel: ⚠ — M3 above. Otherwise the plan keeps `apply_on_issue`
untouched and routes parser fatals separately from parser
recoverables.

L_inherited_patterns: ✅ — artifact-driven product IDs (annotation
declarations are consistent with the 6 product IDs and the legacy
native fields), no public type promotion (T119/T120 unchanged),
`_internal/providers/ch_foen/` subpackage path preserved per D6.

L_legacy_citation_fidelity: ✅ with N1 — INFLUX_TOKEN at line 40 ✅
(re-verified at legacy checkout HEAD `cd9b030`); Authorization
header at 199-203 ✅; VARIABLE_MAP at 44-80 → actually 44-81 (off by
one, N1); parameter preference at 252-261 ✅; flow_ls / 1000 at
263-269 ✅; daily aggregation at 290-297 ✅; Flux query at 176-188 ✅;
native field strings (`flow`, `flow_ls`, `height_abs`, `height`,
`temperature`) all present in legacy VARIABLE_MAP.

L_vocabulary_boundary: ✅ — declared annotation IDs are observation-
shape names, not product IDs. The 8 row annotations and 10 series
annotations enumerate provider-source-tracking facts (native field,
unit, conversion, endpoint, preferred/fallback, timezone, query).
No annotation ID implies a product not in `products.parquet`. No
canonical vocabulary expansion.

L_offline_invariant_explicit: ✅ — `module.py` only adds inline
`AnnotationSchema(...)` calls; new modules (`parser.py`,
`raw_payload.py`, `issue_codes.py`, `observation_client.py`) are
not imported at module-load time. Offline-import test asserts no
`rivretrieve._internal.providers.*` module is in `sys.modules`
after `import rivretrieve` — unchanged. No new file path collides
with `providers`, `provider`, `stations`, `products`,
`product_info`, `provider_info`, or `ProviderHandle`.

L_asymmetric_encoding_round_trip: ✅/NA for step 01 — no new
serialization boundary crossed by step 01 emissions. N3 above
flags `provider_query_fields` JSON encoding as a step-02 forward
pointer; not a step-01 obligation.

L_D7_probe: NA — frozen dataclasses recommended. M6 above suggests
removing the conditional test entirely.

L_D9_probe: ✅ — parser source is CSV bytes, not JSON. No
`json.loads` walking expected.

L_token_probe: ✅ — planner ran the probe against the legacy
checkout at `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python`
and pinned `cd9b030`. Independently re-verified: `git log
origin/switzerland --oneline -10` shows `cd9b030 Restore public
Switzerland token` as the current HEAD, and the literal token at
line 40 is unchanged from M3 REPORT §7.2's classification.

L_fixture_fact_derivation: ✅ — every fixture fact in §5 (row
counts 287/144/141, station IDs 2016/2206/2282, native fields
`temperature`/`flow_ls`/`height_abs`, value ranges 6.5..6.77 /
14..15 / 0.161..0.165, mean 14.944444444444 for discharge,
timestamp ranges and query windows) is derivable directly from
the CSV bytes. None copies a legacy `test_switzerland.py` wide-form
pandas assertion.

## Adversarial probes attempted

1. **`git log origin/switzerland --oneline -10`** in
   `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python`.
   Confirms current legacy HEAD is `cd9b030 Restore public
   Switzerland token`. Plan's HEAD pin (§3) is current.

2. **`git show origin/switzerland:rivretrieve/switzerland.py`,
   lines 37-82.** Confirms line 40 holds `INFLUX_TOKEN = "0yLbh-..."`
   exactly as plan claims, and confirms VARIABLE_MAP spans lines
   44-81 (plan cites 44-80 — N1 above).

3. **`git show origin/switzerland:rivretrieve/switzerland.py`,
   lines 170-300.** Confirms `_build_flux_query` at 176-188,
   Authorization header at 199-203, `_apply_parameter_preference`
   at 252-261, `_convert_units` at 263-269, daily aggregation
   block at 290-297. All match plan §3 citations.

4. **`pl.read_parquet('.../products.parquet')`** on the packaged
   ch_foen catalogue. Confirms 6 product IDs with native_ids
   `{flow, height_abs, temperature}` exactly matching plan §3
   "Product IDs and source behavior pinned" table. No silent
   vocabulary broadening.

5. **`awk` over each fixture CSV** to derive row counts, min/max
   values, mean of `_value`. Results:
   - `switzerland_2016_temperature_20200101.csv`: n=287, min=6.5,
     max=6.77, mean≈6.643 — plan §5 test 4 cites 287, 6.5..6.77 ✅.
   - `switzerland_2206_discharge_20250101.csv`: n=144, min=14,
     max=15, mean=14.944444444444 — plan §5 test 5 cites all four ✅.
   - `switzerland_2282_stage_20250101.csv`: n=141, min=0.161,
     max=0.165, mean≈0.1635 — plan §5 test 6 cites 141, 0.161..0.165 ✅.
   No fixture fact is borrowed from legacy `test_switzerland.py`.

6. **Read `tests/test_ch_foen_module.py`** to verify the existing
   assertions on `row_annotation_schema()` and
   `series_annotation_schema()`. Found lines 43-48 asserting
   `== []`. These will fail mid-§6 between items 10 and 11 — M4
   above.

7. **Read `tests/test_offline_import.py`** to verify the offline-
   import contract under the planned module layout. The test
   subprocess asserts no `rivretrieve._internal.providers.*` module
   lands in `sys.modules` after `import rivretrieve`. Plan's
   `module.py` change adds only inline `AnnotationSchema(...)` calls
   (no top-level imports of `parser.py`, `raw_payload.py`,
   `issue_codes.py`, `observation_client.py`), so the new modules
   stay outside the offline-import chain. ✅

8. **Read `tests/test_package.py`** to enumerate the T119 present-
   set (7 names + `__version__`) and the T120 deferred-name list
   (29 names). New ChFoen* internal types under
   `rivretrieve._internal.providers.ch_foen.*` are not exported at
   the package root; T119 stays exact; T120 names do not collide
   with any planned ChFoen* internal type. T119/T120 stay green. ✅

9. **Read `src/rivretrieve/_internal/observations.py`** to verify
   plan-declared `value_type` strings against
   `_ANNOTATION_VALUE_TYPES = {"string", "integer", "float",
   "boolean", "datetime", "json"}`. Plan §3 uses only these. ✅
