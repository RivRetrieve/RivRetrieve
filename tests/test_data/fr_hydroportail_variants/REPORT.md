# HydroPortail source evidence

Acquired 2026-09-21 10:58:07–10:58:43 UTC. No checkout created; this directory is an evidence artifact directory. No production code changed.

## Reproduce

From repository root:

```sh
uv run python tests/test_data/fr_hydroportail_variants/capture.py --out-dir .worktrees/evidence/hydroportail-variants-fresh
uv run python tests/test_data/fr_hydroportail_variants/verify.py
```

Capture requires an explicit new output directory and refuses to overwrite an existing directory. To verify fresh results, pass `--evidence-dir .worktrees/evidence/hydroportail-variants-fresh`. `manifest.json` records UTC dates, SHA-256 hashes, full series metadata, counts and endpoints. Each interaction has a `.request.http`, `.response.body`, and `.exchange.json`; observation interactions also have native v2 `.recording.json` envelopes. The HTTP request serialization records the prepared request target, headers and empty GET body. Response bytes are the exact decoded entity bytes returned by requests and supplied to Transport, not a TLS or compressed-wire capture. HTTP framing and transport compression are not retained. No secret-bearing request headers were used.

## Source results

All 32 bounded observation calls returned HTTP 200. All station, metric, selector, unit, title and UTC envelopes matched, including empty series. Four source radio selectors remain `raw`, `validated`, `pre_validated_and_validated`, `most_valid`; the UI default is `most_valid`. This does not establish a client preference.

| Station | Inclusive dates | Metric | raw | validated | pre_validated_and_validated | most_valid |
|---|---|---|---:|---:|---:|---:|
| Y251002001 | 2019-12-30..2020-01-04 | Q/H each | 1728 | 169 | 169 | 169 |
| 1232000101 | 2026-05-30..2026-06-04 | Q | 611 | 0 | 0 | 611 |
| 1232000101 | 2026-05-30..2026-06-04 | H | 615 | 0 | 0 | 615 |
| Y251002001 | 2020-01-01..2020-01-02 | Q/H each | 576 | 50 | 50 | 50 |
| 1232000101 | 2026-06-01..2026-06-02 | Q/H each | 282 | 0 | 0 | 282 |

The first two window groups are padded requests for the public API's 01..02 dates. Exact vision windows reproduce discovery counts. At Y251002001 the three reviewed-selection observation arrays are exactly equal, and differ from raw; at 1232000101 raw and most_valid arrays are exactly equal. These remain different requested source identities. Y251002001 direct raw starts 2020-01-01T00:00:00Z, reviewed starts 00:01:00Z. No null measurements were observed in these bounded witnesses. Empty responses retain code, metric, statuses, unit and title, and root timezone=UTC.

## Interpretation limits

All observed raw points have `s=4`. Reviewed Y251002001 points have `s=16`; 1232000101 most_valid points have `s=4`. `graph-measures` maps `s` to status, `q` to qualification, `m` to method, and `c` to continuity. `hydro-series` translates status 0 as Sans validation, 4 Données brutes, 8 Données corrigées, 12 Données pré-validées, 16 Données validées. Numeric ordering establishes no selection algorithm. The glossary describes processing stages, not independently requestable selectors.

Q code `l` remains scoped to Q and resolves to l/s: `unit-selector` pairs code=l with unit.q.l under Q; `unit-label` publishes common.unit.q.l=l/s. Both script hashes match existing unit evidence. H is mm. Form script links point to the fetched script versions.

No positive corrected or pre-validated point witness, mixed-status precedence or selection algorithm was established. No absence of complete historical availability is inferred from empty windows. Invalid corrected/pre_validated selectors were not re-requested in this capture; only the four actual selectors were sent. No contradiction or additional in-scope capability was found. Independent public-engine verification passed separately; see PUBLIC_PATH_REPORT.md.

## Verification

`verify.py` passed: 38 exact response and request hashes, all 32 v2 recording byte matches and source envelopes, four form selectors, and complete-array equality assertions. `capture.py` uses existing HttpClient/TransportRequest and RecordingEnvelope/write_recording interfaces. Script and source form evidence remain alongside the observation recordings for audit.

## Lossless evidence packaging

`source-captures.tar.xz` holds all original response bodies and the 16 direct-window
recording envelopes. The 16 padded recordings consumed by public-path tests stay
individually inspectable. Request bytes, exchange receipts and `manifest.json`
remain beside them. `evidence-archives.json` records archive and original-member
lengths and SHA-256 hashes. `verify.py` reads retained files or archive members
without extracting or changing them. No original response or recording bytes
were discarded.
