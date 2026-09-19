# Everything the repository says about USGS is true

Related issue: [#271](https://github.com/RivRetrieve/RivRetrieve/issues/271). This is a
standalone vision with no Program or Effort provenance. The intended target branch is `main`.

## Outcome

Files in this repository say things about the USGS provider (`usgs_nwis`) that are not true, and
tests validate payloads USGS never sent. When this work is done, no document, test or test-data
file asserts something about USGS that USGS does not do, and every expectation about a USGS
observation response rests on bytes USGS really returned.

The human's standard, in their words: nothing wrong in here, no AI hallucinations that have made
it into the repository, and no tests that test something that isn't true. If a file invents a
USGS behaviour, or a test validates an invented one, it is removed or re-grounded on real bytes.
The correction is comprehensive for USGS. It is not bounded by the single paragraph that #271
quotes.

## What USGS actually does

Verified against the live service on 2026-09-19 at gauge `07374000` (Mississippi River at Baton
Rouge). Re-verify anything you rely on; source responses can change.

| Service | Timestamp returned | Zone on the value |
| --- | --- | --- |
| Daily values, `/nwis/dv/` | `2023-01-01T00:00:00.000` | none |
| Instantaneous values, `/nwis/iv/` | `2023-01-01T00:00:00.000-06:00` | an offset on every value |

- USGS documents this: "All time values RETURNED from the service are UTC with the exception of
  daily data, which returns time values in local dates"
  ([read_waterdata_daily](https://water.code-pages.usgs.gov/dataRetrieval/reference/read_waterdata_daily.html)).
  See also the [daily values](https://waterservices.usgs.gov/docs/dv-service/daily-values-service-details/)
  and [instantaneous values](https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/)
  service details.
- On the daylight-saving day 2023-03-12 the instantaneous service returns 92 readings for
  discharge (`00060`). They run `…01:30-06:00`, `01:45-06:00`, then `03:00-05:00`, `03:15-05:00`:
  the offset flips and the 02:00 hour is absent. Values are about 809,000–811,000 ft³/s with
  qualifier `A`.
- The daily payload still carries `sourceInfo.timeZoneInfo` (`CST`, `-06:00`, uses DST). That
  describes the station. It is not a zone on the daily values.
- `https://waterservices.usgs.gov/nwis/iv/` now answers `301` to
  `https://nwis.waterservices.usgs.gov/nwis/iv/`. The `/nwis/dv/` endpoint answered `200`
  directly. Retrieval works because the transport follows redirects.

## What the code already does, and must keep doing

`src/rivretrieve/_internal/providers/usgs_nwis/parse.py` (`_parse_timestamp`) keeps the wall-clock
time as sent and fills `time_zone` with the published offset, or `unknown` when a daily timestamp
has none. Nothing is converted to UTC at parse time. `rivretrieve.to_utc` refuses rows whose zone
is `unknown`. `test_parse_current_daily_recording_preserves_naive_period_labels_as_unknown_zone`
pins the daily behaviour against a real recording. `docs/usage.md` and `README.md` already
describe this correctly.

**The parser's behaviour does not change in this work.** It reports the zone information USGS
sends and `unknown` when there is none. That is the software's design: `AGENTS.md` says to
preserve source facts and unknowns and not to infer time zones, and `docs/README.md` promises
times "as the agency publishes them, each with its time zone, which is `unknown` when the agency
does not state one".

For the same reason, which zone defines a USGS daily value's midnight-to-midnight window is
**not an open question for this project** and gets no follow-up issue. USGS does not state it, so
the answer is `unknown`, permanently, unless USGS publishes it. Do not apply the station's `CST`
to daily rows, and do not write prose implying RivRetrieve will one day work it out.

## Known falsehoods to correct

These were found during discovery. They are a starting inventory, not the boundary of the work.

### `docs/provider_ports/usgs_nwis.md`

Correct the whole note, not only line 62. Check every claim in it against today's code and the
live source, and fix or remove what is false. Known-false today:

- Line 62, the "Critical fact" that every response value, daily included, carries an ISO 8601
  offset, with `2023-01-01T00:00:00.000-06:00` as a daily example.
- Lines 64-73: the five-step UTC conversion, storage as `pl.Datetime("us", "UTC")`, the series
  annotations `resolved_timezone` and `timezone_source = "provider_timestamp_offset"`, and the
  statement that a daily observation for `2023-01-01` becomes `2023-01-01T06:00:00Z`. None of this
  exists in the code.
- Lines 85-89, "Row and Series Annotations": `resolved_timezone`, `timezone_source`, `raw_value`
  and the other listed annotations are not what the parser emits. Verify each against the rows
  schema before keeping any.
- Line 102, the Pain Points row that cites `test_parser_timestamps_converted_from_cst`. No such
  test exists.
- The endpoint table and any other text naming the instantaneous host, given the redirect above.
  `src/rivretrieve/_internal/providers/usgs_nwis/origins.py:132` records
  `https://waterservices.usgs.gov/nwis/iv/` as `requested_from`; establish whether that is still
  a true statement of what is requested and correct it if not.

The corrected note states, as fact and briefly: instantaneous values carry an offset; daily values
are local-date labels with no stated zone, so RivRetrieve reports `unknown`; the station zone in
the payload describes the station and is not applied to daily values.

`docs/README.md` files port notes under "Project records" to be read as history. That does not
license a record to assert a source fact that was never true. Where the note describes behaviour
that was real when written and has since been replaced, say what the software does today rather
than leaving a description of code that no longer exists.

### `tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json` — delete

It presents itself as a USGS daily response but is not a capture: every daily timestamp carries
`-06:00`, its query asks for 1–31 January but it holds 10 values, and it contains the note
`[mode=USGS_WaterML2; requested:2026-01-01]`. Its discharge values do match real ones
(373000 ft³/s on 1–3 January 2023), so it is probably a real response that was edited. It was
added with the original port (`b744717`) and is the likely origin of the false doc claim.

It is used by:

- `tests/test_usgs_nwis_parse.py` — `test_parse_fixture_emits_exact_native_rows_from_payload_identity`
  and `test_parse_fixture_preserves_wall_clock_offset_and_ignores_cst_trap` assert `-06:00` on its
  rows, and `test_parse_requires_exactly_one_station_product_pair` uses its bytes. Note these tests
  parse the daily file under *instantaneous* semantics via `_provider_config()`.
- `tests/test_usgs_nwis_fetch.py:49` and `tests/test_transport_seam.py:32`, as generic USGS bytes.

Remove tests whose only content is validating the invented shape. Where a test protects a real
behaviour (wall-clock preserved, published offset kept verbatim, `CST`/`CDT` abbreviations never
used as the zone, payload identity, exactly one station-product pair), re-ground it on a real
recording: offsets on the real instantaneous recording, naive labels on the real daily recording.

### `tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12-dst.json` — delete and replace

The shape it asserts is true, but its content is invented: two readings of `100.0` and `101.0`
ft³/s with qualifier `P`, for a river carrying about 810,000 ft³/s. It is used by
`test_to_utc_usgs_dst_boundary_uses_each_payload_offset_without_catalogue` in `tests/test_utc.py`,
whose expected frames hard-code the invented values.

Capture a real recording of that day and re-ground the test on it. The behaviour under test stays:
`to_utc` converts each row by its own published offset across the DST flip, without consulting the
catalogue.

### Everything else about USGS

Sweep every remaining USGS document claim, test and test-data file the same way. At minimum:

- `tests/test_data/usgs_nwis_metadata_series.json` and `usgs_nwis_metadata_expanded.json`, used by
  `tests/test_usgs_nwis_generate_catalogue.py`. They are JSON, while the site service returns RDB
  text, and they name a real station (`02339495`). Not yet verified. Establish whether they are
  faithful to what USGS returned or invented, and treat them accordingly.
- Inline payloads in `tests/test_usgs_nwis_parse.py` built with `_content([...])`. Offsets on
  these are fine where the test parses them under instantaneous semantics, which matches USGS. No
  test may present an offset-bearing daily payload as something USGS produces.
- Source comments, docstrings, issue-code text and origins under
  `src/rivretrieve/_internal/providers/usgs_nwis/`, and every mention of USGS in `docs/` and
  `README.md`.

Discovery found the false daily-offset claim in exactly one place, the port note. `docs/usage.md`,
`docs/reference.md`, `README.md` and the provider source do not repeat it. Confirm rather than
assume.

## Recordings

The existing `*.recording.json` files under `tests/test_data/` are real captures and are the model
for new ones: `…dv_00060_00003_2023-01-01_2023-01-03.recording.json` (daily, naive labels) and
`…iv_00060_2023-01-01.recording.json` (instantaneous, offsets, captured 2026-09-19). Recording and
replay live in `src/rivretrieve/_internal/recordings.py`. A new recording must be the exact request
and the exact response bytes; do not trim, edit or hand-assemble one. USGS needs no credentials and
was reachable from the maintainer's network on 2026-09-19.

## Evidence of success

- `docs/provider_ports/usgs_nwis.md` contains no claim that contradicts the code or the live
  source, and each timezone statement in it can be checked against a committed recording.
- The two invented USGS payload files no longer exist in the tree, and nothing references them.
- Every test that asserts a property of a USGS observation response reads a real recording, or
  builds a small in-test payload whose shape matches what USGS sends for the semantics under test.
- The DST test passes against real bytes for 2023-03-12.
- `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run ty check src`,
  `uv run python scripts/generate_reference.py --check` and
  `uv run pytest -q tests/test_documentation.py` pass.
- The delivery PR lists every falsehood found and what was done about each, including any found
  beyond the inventory above.

## Scope boundaries

- USGS only. Other providers' fixtures and documents are out of scope, including the retired
  `resolved_timezone` / `timezone_source` vocabulary in `docs/provider_ports/za_dws.md`. If the
  sweep suggests the same problem exists elsewhere, open a separate issue; do not grow this work.
- No change to parser behaviour, the public API, or how `to_utc` treats unknown zones.
- Do not edit past visions under `planning/visions/`. They are the audit trail of what was done to
  the codebase, including `2026-09-01-a-fixture-is-a-recording.md`, which called the USGS payloads
  "plausible real payloads".
- Do not use `CONTEXT.md` as evidence or doctrine. It is an outdated leftover the human intends to
  delete. Ground every claim in code, tests, recordings, `AGENTS.md` and the live source.
- Do not file an issue about which zone defines a USGS day (see above).

## Jev authorisation

The repository owner explicitly authorised, on 2026-09-19, the use of Jev (TypeSafe's hosted
service, through the `semantic_decisions.py` helper of the `implement-vision` skill) for this
work. This section is the project-level permission reference for it: cite it as
`planning/visions/2026-09-19-everything-the-repository-says-about-usgs-is-true.md#jev-authorisation`
and mark covered excerpts `"sharing": "permitted"`.

The permission covers excerpts of this vision, of issue #271, and of the repository's USGS-related
source, tests, test data, recordings, documentation and the diffs produced by this work, even
though the repository is private. It does not cover secrets, credentials, `.env` content, or
personal data, which are never sent. It applies to this work only and does not extend to other
visions or other parts of the repository. Excerpts are still inspected and minimised before
sending, as the helper's guide requires, and Jev's answers remain advisory.

## Risks and uncertainty

- The origin of the offsets in the deleted daily file is not established. It is not ruled out that
  USGS once sent offsets on daily values; no evidence was found that it did. This does not change
  the work: the repository describes and tests what USGS sends now, as recorded.
- USGS is mid-migration between hosts and APIs (`api.waterdata.usgs.gov` also exists and returns
  date-only daily values). Record what is observed at capture time with its date, and avoid prose
  that will silently go stale.
- A real 2023-03-12 recording holds 92 readings rather than 2. Keep the test's expectation
  auditable by eye against the recorded bytes rather than restating all 92 rows by hand.
