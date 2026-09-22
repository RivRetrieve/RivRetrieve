# Recording HTML encoding declarations

## Outcome

Repair the recording-path defect reported in [issue #324](https://github.com/RivRetrieve/RivRetrieve/issues/324). Supported MLIT HTML must pass through `RecordingTransport` and remain recordable and replayable when its HTTP Content-Type is `text/html` without a charset, but the document itself declares EUC-JP.

The recorder must inspect the correctly decoded text for sensitive fields while preserving the original response bytes and Content-Type exactly. This is a standalone bug-fix vision, not a Program Effort.

## Why this fails today

`src/rivretrieve/_internal/recordings.py` decodes text for sensitive-field screening in `_decode_text_payload`. It uses an HTTP charset or byte-order mark, otherwise UTF-8. It does not consult HTML encoding declarations. MLIT's response begins with:

```html
<HTML>
<HEAD>
<META http-equiv="Content-Type" content="text/html; charset=EUC-JP">
```

The first Japanese bytes consequently fail UTF-8 decoding. `RecordingEnvelope` construction raises `ValueError: structured recording content cannot be decoded safely`, so `RecordingTransport.send` neither retains the envelope nor returns the response to the provider.

The Japan provider's `_page` in `src/rivretrieve/_internal/providers/jp_mlit/fetch.py` already decodes strict EUC-JP and checks the document declaration. This issue is not evidence that ordinary retrieval is broken or that MLIT is unavailable.

## Settled scope and constraints

- Recognise supported encoding declarations inside HTML when the HTTP charset is absent. Use explicit source evidence, not statistical encoding guesses or a provider-specific override.
- Preserve exact response bytes and headers represented by the transport. Do not fabricate an HTTP charset or transcode saved evidence.
- Keep sensitive-field screening enabled on the correctly decoded text. Reject invalid, ambiguous, unsupported, or undecodable declarations/content when safe inspection cannot be established. Do not silently replace or discard undecodable characters.
- Preserve existing supported HTTP-charset and BOM behavior and non-HTML recording behavior. Determine safe declaration parsing and conflict handling from established encoding rules and the existing fail-closed contract; these are engineering decisions, not unresolved user choices.
- Keep the change local to recording behavior and its regression coverage. No Japan-parser change, public API change, broad encoding framework, or unrelated cleanup is required.
- PR #290 and its documentation review remain separate. Do not edit, approve, merge, or resume that PR as part of this work. Nicolas will return to that review afterward. The issue's historical pause wording does not establish a new workflow dependency.

## Evidence already checked

Investigation on main reproduced the exact failure offline using the preserved MLIT response. Its SHA-256 is `e8dadbcfcc2fbf5f6b6f29447262f39b0f1074bf759bc339a8b1c4f6e09cb4a2`. Strict EUC-JP decoding succeeds. The existing `_text_has_secret_field` accepts the decoded source and detects separately added password, API-key, and access-token fields. Those probes support the diagnosis but do not constitute exhaustive security validation.

All 49 tests in `tests/test_recording_envelope.py` passed before the repair. The four existing `tests/test_data/jp_mlit_*_html.recording.json` fixtures contain `text/html; charset=EUC-JP` in their recorded Content-Type. They do not exercise the missing-HTTP-charset case. Do not rewrite their historical metadata to manufacture new source evidence.

Local supplementary evidence is under `.worktrees/evidence/japan-provider-documentation-review/live-verification/`, notably `response-1.bin` and `reproduce-recording-failure.py`. It may not exist in a fresh checkout. Issue #324 contains the reproduction and source context; add self-contained regression coverage rather than making tests depend on this local directory. Offline replay is not a fresh network witness.

## Observable success

1. A response with the MLIT shape above and non-ASCII EUC-JP text, HTTP 200, and unchanged `text/html` metadata passes through `RecordingTransport`. Its retained recording preserves the bytes and metadata and survives normal write/read/replay.
2. Sensitive fields in the same encoding still cause rejection. Cover both the source-shaped declaration and representative malformed, conflicting, unsupported, and undecodable inputs so the new path cannot bypass safe inspection.
3. Existing explicit-charset, BOM, and non-HTML behavior remains covered and passing. Run the recording tests, relevant Japan tests, and the repository's normal lint and type checks; expand regression coverage as code inspection requires.
4. If the preserved source response is available, repeat its offline reproduction after the repair and report the result without claiming a fresh acquisition. A live source call is not required to prove this deterministic defect repaired.

No outcome-level questions remain. The implementing agent owns reversible parsing and test details within these constraints.
