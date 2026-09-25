# HTTP retry correctness

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/375

## Outcome

RivRetrieve should recover from transient HTTP failures when repeating the request is safe, without hiding permanent failures, accepting incomplete source bytes, repeating unsafe operations, or exposing credentials. Exhausted retries must remain identifiable failures with useful, safe diagnostics.

This is a comprehensive repair of related retry correctness defects, not an exception-list patch limited to the original report. Investigate and repair related problems in replay safety, exception classification, bounded waiting, and failure reporting. Time and implementation cost are not reasons to leave a relevant demonstrated defect unresolved. This does not authorize unrelated transport redesign or new download products.

Issue #371 and its publication-aware Poland discovery work, including PR #374, are independently owned and explicitly excluded. This work can proceed in parallel: archive discovery chooses requests; shared transport executes them. Do not change publication rules, expected archive layouts, coverage, or vintage semantics. Coordinate overlapping tests and integrate against the latest target branch before delivery; neither issue must wait for the other merely to begin.

## Investigation results

Investigation baseline: `main` at `0f36c07ad2aa29de2eff5ae5f2ade678d7adc588`.

The original failure is recovered, not hypothetical. The repository-local file `.worktrees/poland-provider-evidence-2026-09-24/download-2026-09-25.log` records a public `rr.download("pl_imgw")` run at revision `ba84391ef6fdebd0c9b311dd69f77fe019f85f24`, version 0.1.49, starting at 2026-09-25T09:51:33Z with an empty cache. Its exception chain is:

```text
urllib3.exceptions.IncompleteRead(73534 bytes read, 2331 more expected)
  -> urllib3.exceptions.ProtocolError
  -> requests.exceptions.ChunkedEncodingError
  -> TransportFailure: terminal_sender_failure after 1 attempt
```

This local log is supplementary evidence, not a dependency for implementation. It does not establish the failed archive URL, elapsed duration, count of completed archives, upstream cause, or preservation of an already existing store. The similarly named earlier `download.log` records a different compilation error.

A deterministic investigation on the baseline used a loopback HTTP server and unmodified `HttpClient` / default Requests sender, executed with `uv run python`. With Requests 2.34.2 and urllib3 2.7.0:

- A 200 response declaring `Content-Length: 20`, sending only two bytes, and closing the connection produced the same exception family and one terminal attempt.
- A 200 chunked response sending `5\r\nab` and closing before completing its chunk also produced `ChunkedEncodingError` caused by `IncompleteRead`, with one terminal attempt.
- A complete 404 response returned status 404 after one request, without retry.

Despite its name, `ChunkedEncodingError` also covers truncated fixed-length responses. Do not restrict the repair to HTTP chunked transfer encoding.

The broader review also found related gaps:

- `requests.exceptions.SSLError` inherits from `ConnectionError`, so the current broad classifier retries permanent certificate-verification failures. Conversely, `ChunkedEncodingError` can represent protocol/framing errors as well as incomplete reads; classification must not blindly equate every framing error with a transient interruption.
- The sender returns only bytes, status, and Content-Type. It drops `Retry-After`, so retryable 429/503 responses cannot influence the current fixed schedule.
- The driver retains generic transport reason, attempts, and status, but loses specific failure category when producing caller-visible issues. Its exhaustion message describes timeout/response failures rather than all supported connection/interruption failures. Safe diagnostic identity needs to survive both this boundary and credential sanitization.

These are related repair targets. There is no evidence here requiring a hard whole-download deadline, a global rate limiter, jitter, circuit breakers, or persistent download state.

### Existing transport and failure boundaries

`src/rivretrieve/_internal/transport.py` owns retry execution. `_send_with_requests` consumes response bytes before returning. `_is_retryable_sender_exception` currently includes Requests and built-in timeout/connection errors, but not `ChunkedEncodingError`. `HttpClient.send` catches that exception as a RequestException and immediately raises `TERMINAL_SENDER_FAILURE`.

The current policy allows three attempts, with 1-second and 2-second backoff, a 60-second Requests timeout, and a 1-second minimum interval between starts on one client. Retryable statuses are 408, 429, 500, 502, 503, and 504. The Requests timeout is not an overall download deadline; bounded attempt count must not be described as a strict total wall-clock bound.

Current retries are method-blind, including retries for POST. The only production POST found is the Swiss FOEN Influx query in `providers/ch_foen/fetch.py`: its Flux expression reads, filters, selects, and sorts data. That request is semantically read-only; the generic transport request type nevertheless provides no general proof that another POST is safe to replay. The earlier proposal to leave all existing POST behavior untouched was not accepted as the scope of this work. Assess existing retries as well as the new interrupted-response case.

`TransportFailure` retains reason, attempts, request, optional status, and an exception cause for ordinary sender failures. `AuthenticatedTransport` intentionally sanitizes failures and removes the original exception chain to protect credentials. Better diagnostics must preserve this boundary rather than expose raw authenticated exceptions.

Shared `_internal/bulk.py::_transfer` writes a destination only after a complete successful transport response. Poland's `download_imgw_history` removes the current partial target and archives acquired during a failed attempt, then rethrows; compilation starts only after acquisition succeeds. A transfer failure therefore does not replace a prior compiled store. Existing source facts, checksums, provenance, and store publication guarantees must remain intact.

Baseline command `uv run pytest -q tests/test_internal_transport.py tests/test_transport_seam.py` passed 71 tests. Existing retry tests mainly inject a recording sender for GET. They do not establish real incomplete-response handling or method-sensitive replay safety. Passing this suite or completing one live download does not disprove the defect.

## Required behavior

### Safe, complete retries

Retry recognized transient response interruptions through the shared transport when the operation is safe to repeat. Restart the affected request; do not concatenate incomplete attempt bytes or let them become a successful response, source artifact, or parsed observation. An interruption followed by a complete response must recover without restarting already successful requests in that same acquisition.

Apply a coherent replay-safety rule to all retry triggers, not just the newly recognized exception. GET and HEAD support ordinary safe replay. Do not infer arbitrary POST safety from its verb or from the fact that today's sole caller is read-only. Preserve retry support for source operations whose read-only or otherwise safe semantics are established. Leave the representation and propagation of that knowledge to implementation, using the repository's typed boundaries rather than provider-local retry loops.

Classify failures deliberately. Review exception inheritance and distinguish transient connection/read interruptions from permanent TLS verification, invalid request, unsupported protocol, invalid encoding, and source parsing failures. Do not retry arbitrary exceptions or treat corrupted source data as a transient success. Complete 404 and other non-retryable HTTP responses must retain their existing meaning; retry policy must not substitute for publication discovery.

### Bounded scheduling and diagnosable failure

Keep a finite attempt budget and explicit bounded retry delays. Preserve source-friendly pacing. Review server-directed retry timing and the information available at the sender boundary; honor valid Retry-After delta/date guidance without creating unlimited waits or accepting malformed timing as trustworthy input. If a valid server delay exceeds the allowed waiting budget, terminate with a clear bounded-policy failure rather than retrying earlier than the server permits. Malformed, negative, past, or excessive values must not crash scheduling or cause unbounded sleep. Do not add an unlimited loop or silently expand the attempt budget to hide persistent defects. Explain the timeout and waiting guarantees accurately.

After exhaustion, preserve the failed request's safe identity, reason, attempt count, and available final status or safe cause information. Keep permanent failure distinct from exhausted transient failure. Carry a sanitized specific failure category through caller-visible issue and authenticated boundaries where raw causes cannot safely survive; generic reason alone must not erase whether the request timed out, disconnected, or received an incomplete response. Do not invent an HTTP status when the failure path did not retain it. Preserve authentication redaction, redirect restrictions, supported source-failure isolation, and fatal internal-contract behavior.

### Cleanup and existing data

Preserve partial-file cleanup and existing valid stores on failure. A retry must not delete previously successful artifacts prematurely; ordinary acquisition rollback after final failure remains valid. Prove these boundaries with failure tests rather than assuming that a fresh successful run exercises them.

Cross-run resumable acquisition, HTTP range downloads, and a persistent archive cache are not required for retry correctness. The known cleanup policy makes exhaustion costly, but does not itself prove those new capabilities necessary. Do not quietly turn this repair into a cache/storage redesign. If investigation demonstrates a material outcome that cannot be delivered without such a change, return for an explicit scope decision with evidence.

## Evidence required for delivery

Use deterministic tests through the actual default HTTP sender against controlled responses, in addition to unit tests for policy decisions. Cover:

- Fixed-length and chunked response interruption followed by success; only the final complete bytes are returned or written.
- Repeated interruption and mixed retry triggers exhausting one shared finite budget, with correct pacing, attempt count, and final diagnostics.
- Safe and unsafe replay decisions, including established read-only POST use and a POST whose replay safety has not been established; verify existing status/timeout retries as well as interruption retries.
- Permanent request/TLS/decoding failures, complete 404 responses, malformed source payloads, and arbitrary internal exceptions retaining the correct non-transient behavior.
- Server backoff guidance and its malformed or excessive forms, to the extent relevant to the resulting scheduling policy.
- Authenticated success, exhaustion, and terminal failures without leaked credentials, and unchanged redirect protections.
- Transfer cleanup and preservation of an existing valid store after exhausted acquisition; an interruption that recovers must not trigger whole-acquisition rollback.

HEAD has no response body: test its replay and status behavior without pretending that a truncated GET body is a realistic HEAD response.

Run repository-native formatting, lint, type checking, relevant provider/store tests, and the full suite before delivery. Report any unrelated failures accurately. Update user-facing documentation only where retry behavior or guarantees need explanation, using concrete current behavior rather than implementation-history prose.

A live Poland download is useful integration evidence when practical, but is not a substitute for deterministic fault tests and must not be made dependent on an unmerged #371 repair. When both changes become available, verify their combined behavior without absorbing #371's implementation into this work.

The implementing agent owns reversible mechanisms, test structure, and PR slicing. This standalone vision does not prescribe a generic retry framework, a public configuration API, or a new storage format.
