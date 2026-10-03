# Repair the eleven dependency security alerts

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/480

## Outcome and boundaries

Resolve all eleven dependency security alerts numbered 19–29 while preserving
RivRetrieve's download, failure-handling and PDF-reading behavior. This is a
standalone repair vision for bug #480, not a revision of the catalogue Effort
#430 or its vision. The catalogue changes are already merged. Its delivery and
cleanup remain paused until the repair is verified and the owner explicitly
authorizes resuming https://github.com/RivRetrieve/RivRetrieve/issues/430.

Use a focused update of urllib3 and pypdf. Update both the lockfile and published
minimum requirements so that new installations cannot select the affected
versions. At investigation time, urllib3 2.8.0 and pypdf 6.19.0 are available,
non-yanked releases covering all eleven alerts. Use `urllib3>=2.8.0,<3` and
`pypdf>=6.19.0`, or newer compatible patched versions after checking current
advisories. Keep unrelated dependency churn out of scope.

No backward-compatibility shims or migration guides are required. The owner has
no current users. Existing environments still need their dependencies synced;
merging repository changes does not patch already installed packages. State any
remaining environment-sync or release step without introducing a release-system
redesign.

Do not add general processing deadlines, memory limits, sandboxing, a different
HTTP client or a different PDF parser. Change application code only when a
demonstrated compatibility problem requires it. Do not change source claims,
catalogue products, archive collections or provider acquisition scope. No new
provider research, live acquisition campaign or catalogue publication is needed.

## Why the bug matters

Specially crafted downloads or PDFs can cause excessive memory use or prolonged
CPU processing. A network read timeout limits waiting for network data. It cannot
interrupt a CPU loop inside a parser. Normal-data test passes do not establish
safety against these malformed inputs.

Inspection at public main `79e1233ced0b6dfea448c6b6f754bc37ff128bbc` found requests
2.34.2, urllib3 2.7.0 and pypdf 6.16.1 in `uv.lock`. Requirements in
`pyproject.toml` still allow `urllib3>=2,<3` and `pypdf>=6.16.1`. These versions and
transport behavior predate the catalogue changes. No exploitation, compromised
provider or damaged catalogue data was observed or claimed.

The source investigation established these call paths:

- `src/rivretrieve/_internal/transport.py::_send_with_requests` calls Requests
  and reads `response.content`. Requests' adapter passes `preload_content=False`;
  `Session.send` eagerly consumes content when streaming is disabled. That calls
  `Response.iter_content`, then `raw.stream(..., decode_content=True)`, reaching
  urllib3's chunked-response reader. Omitting `stream=True` is not a mitigation.
- `src/rivretrieve/_internal/acquisition_provenance.py::verify_recorded_statement`
  checks the retained file's digest, then `_recording_text` uses `PdfReader` and
  all-page text extraction. A digest establishes identity, not malicious-PDF
  safety. Parsing failures become `FatalContractError`.
- `src/rivretrieve/_internal/providers/za_dws/generate_catalogue.py` reads and
  extracts PDF text. Invalid PDFs become issues; the complete refresh requires
  all eight inventory PDFs and rejects parsing issues. Its live PDF acquisition
  uses stdlib `urllib.request`, so do not describe that acquisition as an urllib3
  call path. The pypdf exposure remains relevant.

These are static reachability findings, not demonstrations of an attack. No
malicious payload was executed during discovery.

## Advisory evidence

All eleven GitHub alerts were open when inspected. The following table separates
operations found in RivRetrieve from conditional or unobserved triggers. All
links refer to the upstream advisory, which also identifies repair references.
Recheck their current status when implementing.

| Alert | Advisory | Relevant condition or operation | First patched version |
| --- | --- | --- | --- |
| 19 | [GHSA-8988-9cw3-xx77](https://github.com/advisories/GHSA-8988-9cw3-xx77) | HTTPS proxy with divergent proxy/target TLS policy. The required configuration was not established. Requests can honor environment proxies; do not claim they are disabled or that disclosure occurred. | urllib3 2.8.0 |
| 20 | [GHSA-vxq7-64xx-v4gw](https://github.com/advisories/GHSA-vxq7-64xx-v4gw) | Normal body reading reaches chunk parsing; an oversized unterminated chunk-size line can exhaust memory. | urllib3 2.8.0 |
| 21 | [GHSA-gh4c-6fx4-qh6g](https://github.com/advisories/GHSA-gh4c-6fx4-qh6g) | Normal body reading reaches decompression; chunked Deflate content with trailing encoded bytes and sufficient decoded content can loop without a network timeout stopping it. | urllib3 2.8.0 |
| 22 | [GHSA-qv6h-rv94-w285](https://github.com/advisories/GHSA-qv6h-rv94-w285) | Roman page-label access was not found in current project paths. | pypdf 6.17.0 |
| 23 | [GHSA-5jq2-8x83-x246](https://github.com/advisories/GHSA-5jq2-8x83-x246) | PDF reading reaches indirect-object parsing; an oversized malformed header can exhaust resources. | pypdf 6.18.0 |
| 24 | [GHSA-fp3h-c4fm-7vvf](https://github.com/advisories/GHSA-fp3h-c4fm-7vvf) | Text extraction reaches font ToUnicode mappings; malformed oversized mappings are the trigger. | pypdf 6.18.1 |
| 25 | [GHSA-g9cg-prrw-2r8q](https://github.com/advisories/GHSA-g9cg-prrw-2r8q) | Text extraction reaches font widths; unusually large values are the trigger. | pypdf 6.18.1 |
| 26 | [GHSA-jw7q-gvrg-4vj3](https://github.com/advisories/GHSA-jw7q-gvrg-4vj3) | PDF stream decoding can reach a costly byte-by-byte FlateDecode fallback for malformed input. | pypdf 6.18.1 |
| 27 | [GHSA-w23x-9jrw-r45c](https://github.com/advisories/GHSA-w23x-9jrw-r45c) | Alphabetical page-label access was not found in current project paths. | pypdf 6.19.0 |
| 28 | [GHSA-php9-fj8v-98fj](https://github.com/advisories/GHSA-php9-fj8v-98fj) | Form-field updates with flattening or appearance generation were not found in current project paths. | pypdf 6.19.0 |
| 29 | [GHSA-v247-6f48-mgcj](https://github.com/advisories/GHSA-v247-6f48-mgcj) | Dictionary-based embedded-file access was not found in current project paths. | pypdf 6.19.0 |

Release evidence: [urllib3 2.8.0](https://github.com/urllib3/urllib3/releases/tag/2.8.0)
and [pypdf 6.19.0](https://github.com/py-pdf/pypdf/releases/tag/6.19.0).
The scope covers all eleven alerts even where the vulnerable operation was not
found in normal use. It does not claim protection against every possible hostile
response or PDF.

## Evidence required for acceptance

Use `uv` for dependency changes and execution. Inspect the resulting package and
lockfile diff for unrelated changes. Start with the existing coverage, adding
only focused tests for distinct uncovered behavior or a demonstrated regression.
An exploit-payload suite is not required for this dependency repair.

Run `uv run pytest --logic-only`, relevant transport and PDF checks, lint and
type checks (`uv run ruff check`, `uv run ty check src`), and
`uv lock --check`. Compare baseline and patched behavior where useful; historical
results are not acceptance of the new dependency versions.

Existing transport coverage includes `tests/test_http_retry_network.py`,
`test_http_retry_policy.py`, `test_http_retry_exchange.py`,
`test_http_retry_storage.py`, `test_internal_transport.py`,
`test_transport_seam.py`, `test_transport_attempt_evidence.py`, and
`test_source_failure_isolation.py`. The network tests exercise real Requests and
urllib3 against local servers, including interrupted responses, malformed wire
responses, disconnects and refused connections. Preserve retry meaning and failure
classification. `_sender_failure_category` inspects nested urllib3 exceptions
and an exact premature-response sentinel, making it a compatibility checkpoint.

`tests/test_za_dws_generate_catalogue.py` uses benign synthetic PDFs to check
parsing, invalid-PDF issues, malformed coordinates, incomplete inventory inputs,
duplicates and deterministic ordering. These tests exercise pypdf without private
material. Also verify benign unreadable-PDF and absent-statement failure paths;
reuse existing checks where they protect the same behavior.

Run genuine PDF-backed compatibility checks through the current private archive
coordinator, following `docs/maintenance/evidence.md`. Relevant entry points are:

- `tests/test_source_statement_verification.py::test_pdf_source_statement_is_verified_from_recorded_bytes`;
- `tests/test_cz_chmi_generate_catalogue.py::test_publisher_crs_evidence_names_coordinates_but_no_reference_system`;
- `tests/test_pl_imgw_annual.py::test_yearbook_method_scope_is_not_an_archive_wide_mean_definition`;
- the Japan catalogue tests `test_native_cli_is_offline_and_byte_deterministic`
  and `test_native_cli_rejects_statement_absent_from_recording`.

Use independently reviewed code and archive commits, exact verified inputs and
all full-positive prerequisites required by the coordinator's selected checks.
Record the selected scope and results accurately. A logic-only run is not a
genuine-input pass; an offline native-table rebuild is not original-PDF
verification. A dependency-only update does not by itself require recertifying
unrelated governing claims. Run applicable full checks if claims, source bindings,
verifiers or collections change; do not make such changes incidentally to obtain
a passing result.

The original DWS PDFs were unavailable during earlier dependency work
([PR #436](https://github.com/RivRetrieve/RivRetrieve/pull/436)). Their current
availability must be checked against the private archive inventory. Do not assume
that the old gap persists or has been repaired. Report the supported compatibility
scope and any remaining gap explicitly. Missing mandatory evidence is blocked;
never replace original PDFs with native tables or synthetic documents and call
that original-input acceptance. Earlier comparison results and commands are
historical context, not current acceptance or collection selection.

Keep controlled bodies, extracted text, receipts, logs and caches in restricted
storage. Only reviewed code may run with private evidence access. Do not print
extracted text to public logs or introduce private fixtures into this repository.
No live provider check is inherently required for this update.

After merge, verify that GitHub has scanned the changed dependency declarations
and marks alerts 19–29 resolved through the update. Do not dismiss alerts merely
to clear the count. If scanning is pending or an alert remains, report the exact
remaining state instead of claiming complete acceptance. Check current advisories
for the selected versions and report any new relevant blocker.

Finish with the implementation diff, regression results, genuine-input scope and
limitations, alert status, and any remaining environment-sync or release step.
Repair acceptance does not authorize automatic resumption of #430. Obtain the
owner's explicit permission before its final delivery and cleanup.
