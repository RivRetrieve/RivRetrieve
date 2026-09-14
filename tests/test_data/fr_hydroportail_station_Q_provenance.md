# Station-own HydroPortail Q test evidence

Both response bodies were acquired through the repository's RecordingTransport with
one authorised request per capture, no retries and redirects refused. The exact
recordings retain executed ordinary headers, retrieval instants and complete bytes.
No response was backdated, trimmed or relabelled. These two recordings are selected
reviewed test inputs, not publication of the governing private verification corpus.

## Positive public June 1–2, 2026

`fr_hydroportail_station_Q_padded.recording.json` is the second capture.
GET `https://hydro.eaufrance.fr/stationhydro/ajax/1232000101/series` requested
May 30–June 4, 2026, with raw Q and `simple_and_interpolated_and_hourly_variable`.
Acquired `2026-09-14T08:00:37.291189Z`. Complete body:182333 bytes,
SHA256 `aa99bc0a91dd45c928ce64d6fd68dff875abcb1e47cf348b11354980413e3f8f`.
Recording SHA256 `5829e3354477b0f437de68a146e0b6d06c2b3b202a63cdc57378654ba03b2cb5`.

The independent source-only boundary author read the approved vision, ADR0024,
harness contract and these exact source bytes. The author did not inspect the
provider implementation, parser outputs, implementation diff or retired report.
The original accepted source-only assertions are preserved below. The boundary probe
retains their count and wall clocks; the separate attestation below establishes the
fixed-offset carrier representation of their source UTC label:

- reading_count:282
- first_wall_clock_time:2026-06-01T00:00:00, UTC
- last_wall_clock_time:2026-06-02T18:00:00, UTC

The source-only calculation clips source timestamps to
`[2026-06-01T00:00:00Z,2026-06-03T00:00:00Z)`. Its original script SHA256 is
`96ce6fb9566c26a6f4011aefa34cd3d735f6fc33a7d342e0489e3a2e51926ab7`;
output SHA256 `d35716107d77123c23a43a01e88b74568661e2eb4ddbffa3c8856d7352e889dd`.
Those local review files are not runtime dependencies or public download references.
The exact response and independent literals are preserved here for a fresh clone.
Optional raw lexical witnesses are v1280 at the first public timestamp and v1230
at the last. The response declares series.unit l and display unitQ m3. Tests retain
the pre-existing engine L/s to m³/s conversion; the report did not independently
re-establish that conversion.

## Clipped-empty public June 3–6, 2026

`fr_hydroportail_station_Q_empty_clip.recording.json` is the first capture, whose
actual request is June 1–8, 2026. Body:84620 bytes, SHA256
`162823da4aaea86473725ad6c5ab22b85426dc3d919d0b74f83a520d4682757f`.
Its returned rows are June 1–2. Public June 3–6 correctly clips to an empty frame.
This recording is not substituted for the positive boundary evidence above.

## Genuine empty envelope

`fr_hydroportail_J783301020_empty.body` and its unchanged `.receipt.json` preserve
the exact station-Q June 1–8, 2023 response acquired September 13, 2026.
Body:833 bytes, SHA256 `28f1e90b2e9ca2c622447039beaddbf9a0e28585aedaddce5e9856e6537e2f0c`.
The receipt retains full request URL, timestamps, HTTP200 and body identity. It does
not establish executed request headers; none are invented. Direct parser tests use
these source bytes and make explicit adversarial mutations to metadata only.
Mutated bytes are not recordings or independent boundary evidence. Statistics in
this empty response are preserved; they are not treated as observations.

## Separate independent fixed-offset carrier attestation

The original source-only report and its UTC label above are preserved. A separate
independent author inspected the complete response, acquisition receipt, ADR0007 and
public time-zone documentation, but no provider implementation, tests or output.
The source root declares UTC and all 611 raw timestamps carry `Z`. ADR0007 classifies
explicit `Z` as a fixed offset. The existing Rows time_zone carrier is therefore
`+00:00`, representing the same published zero offset. The root reviewed and accepted
this source-only attestation before the test expectation representation was changed.
The public count 282 and both wall-clock timestamps are unchanged. No production zone
change or harness normalization was introduced.

The separately accepted source-zone attestation has SHA256
`20934e09c72d2f43a0ea02786acb6f219774608a0d7d1822c1a0bfb7a3c01024`.
Its local handoff file is not a required runtime or fresh-clone reference. The source
facts and explicit ADR rationale are preserved here with the exact source body above.
