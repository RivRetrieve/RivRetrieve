# Swiss provider documentation review

## Outcome and human review boundary

Review and rewrite the Swiss provider documentation in existing PR [#289](https://github.com/RivRetrieve/RivRetrieve/pull/289), branch `docs/provider-switzerland`, targeting `main`. Deliver an updated, fact-checked page for the user to read and give feedback on. **Do not merge PR #289, proceed to another provider, or autonomously continue after handing it back.** This explicit boundary overrides any implementation workflow's default expectation of merging implementation PRs.

This is standalone documentation work, not a new Effort under the completed Program #284. That Program changed discovery and the engine; these provider-page PRs predate its implementation. Outdated snippets are expected consequences of the refactoring, not faults in the original author’s work. The original broader ambition to review twelve provider PRs has been narrowed to Switzerland alone.

## Preserve the page's purpose and editorial structure

Thiago wrote these pages to give readers useful, approachable context about where data comes from, how hydrology is organised in the country, and how RivRetrieve accesses it. Preserve that spirit, voice, and useful material. Rewrite as much as necessary to describe current behaviour accurately; minimising edits is not an objective, but neither is replacing his work with an engine audit.

There is no formal template. Thiago followed a consistent, flexible editorial structure across providers. Keep that structure in mind for the Swiss rewrite:

- Country/provider title and navigation.
- Quick-reference table covering provider, publisher, quantities, catalogue size, access, terms, and agency documentation.
- A short practical code example.
- Who measures and who publishes, including national context and the intermediary.
- What can be retrieved, including units and availability.
- Provider-specific explanations, such as recent/archive access and data status.
- Time semantics, terms/citation, and dated source references.

The Swiss page currently places data status before time; preserve useful flexibility rather than imposing an exact universal heading order. Verified discovery output and variant explanations fit naturally within the retrieval section. Comparison examples inspected during discovery were France #264, Brazil #276, and Thailand #297; those PRs are not in scope for edits.

There is no public release and no existing user population requiring compatibility treatment. Describe the current interface directly. Do not add migration guides, backward-compatibility narratives, ADRs, or unrelated documentation restructuring. Time and resources must not be used as reasons to weaken verification.

## Show actual behaviour and explain it

Readers should see a command, its verified output, and a plain-language explanation of what that output means. Explain source variants and their known meanings; where a meaning is not established, say so without inventing it.

The following was actually executed against main `cd497d0` using `uv run python` during discovery:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ch_foen",
    station="2018",
    quantity="discharge",
)
```

`rr.series(selection)` returned two rows. A projection of the actual output was:

| station_id | variant | quantity | source_unit | unit | frequency | statistic |
| --- | --- | --- | --- | --- | --- | --- |
| 2018 | flow | discharge | m3/s | m3/s | None | None |
| 2018 | flow_ls | discharge | l/s | m3/s | None | None |

Both temporal states were `not_established`; `selection.issues` was `()`. Each of these calls was also executed and returned exactly its corresponding row:

```python
flow = rr.pick(selection, variant="flow")
flow_ls = rr.pick(selection, variant="flow_ls")
```

Use the same public `variant` interface shown for Brazil in README/usage documentation, but explain that Swiss variants identify source fields, not ANA processing/consistency statuses. Discovery returns catalogue candidates, not observations or proof that station 2018 supplies both fields. Its inventory was incomplete. Show an explicit inspection/projection call matching any displayed output; re-execute the final examples rather than treating this transcript as permanent test evidence.

Current Swiss mappings support discharge (`quantity="discharge"`, fields `flow` and `flow_ls`), stage (`quantity="stage"`, fields `height` and `height_abs`), and water temperature (`quantity="temperature"`, field `temperature`). Returned units are m³/s, metres, and degrees Celsius respectively. Discharge fields retain distinct identities, with litres per second converted to m³/s. The API no longer accepts `rr.find(product=...)`; physical filters and optional variant selection replace the obsolete snippet in this page.

Explain only facts supported by current evidence. In particular:

- Feed periodicity is not a field's established frequency, averaging interval, or statistic. Swiss frequency/statistic/support remain unestablished in current mappings.
- Do not claim BAFU says nothing about aggregation. Its FAQ describes normally five-/ten-minute means, rarely two-minute means, and beginning-of-interval labels for exported files. What remains unestablished is the exact binding of those meanings to each intermediary field.
- `height` is labelled `Pegel m ü. M.` and has established above-sea-level reference; `height_abs` is labelled `Pegel m` and its reference remains unknown. Do not infer semantics from `_abs`, assert a bound vertical datum, or merge the two fields.
- The 246 catalogue stations are not 246 proven available series for every quantity. The locations catalogue lacks per-variable availability; actual returned fields establish evidence for a particular window, not an exhaustive historical inventory.
- UTC `+00:00` describes the intermediary route's timestamps, not every FOEN product or export.
- Keep agency data terms separate from intermediary service terms. Preserve useful citation and provisional-data context without extending a statement about current measurements to every archived value.

## Verification and stop conditions

Fact-check what the page says RivRetrieve does against actual current behaviour. Execute every included code snippet and verify the outputs claimed beside it. Inspecting signatures or reading tests is not sufficient to declare a retrieval example working. Distinguish discovery, recorded regression evidence, and live retrieval; do not present replayed observations as a successful current live request.

Check external claims and quotations against source evidence. Preserve source vocabulary, established facts, and explicit unknowns. Recheck dates, links, counts, terms, citation wording, and field meanings as applicable. Keep detailed validation evidence in the PR review/delivery record rather than making the reader-facing page an audit log.

**If a software problem or bug is found, stop the documentation work and report it to the user. Create a GitHub issue labelled `bug` and assign it to the user (`CooperBigFoot`), with the actual reproduction and evidence. Do not silently fix production code or work around a defect in prose.** If issue creation or assignment is unavailable, report that blocker. Distinguish a code defect from a temporary upstream outage before classifying it. Do not infer new merge gates or broader software scope from an outage.

### Historical access requires direct investigation

The user states Switzerland needs no credentials. Discovery initially overclaimed that the page's “Credentials: None” was incomplete; that conclusion was retracted as insufficiently established. Do not carry it forward as a fact or ask the user to diagnose implementation mechanics.

The concrete unresolved check is the original example's January 2024 retrieval. Existenz documents a 32-day REST horizon and an archive. At the inspected commit, `providers/ch_foen/fetch.py` chooses Flux when its transport can authenticate that endpoint and otherwise uses REST; it does not route simply by requested date. A recorded internal Flux test supplies an authenticated transport. This alone does not establish that users need credentials or that public historical retrieval works. The public example had not been executed during discovery. Execute the corrected example, trace the actual public path and source access arrangement, and establish the facts before changing the page. If this exposes a software bug, apply the stop-and-report rule rather than rewriting access claims around it. Do not label the PR body's historical HTTP 500/FatalContractError report as a current reproduced failure.

## Evidence and delivery

Useful current anchors, to recheck against the implementation checkout:

- `src/rivretrieve/_internal/discovery.py` for public signatures and composition.
- `src/rivretrieve/_internal/providers/ch_foen/{config,series,fetch,parse}.py` for mappings, source identities and access.
- `docs/usage.md`, `docs/architecture.md`, and `docs/reference.md` for current shared contracts.
- `tests/test_public_representative_source_series.py`, `tests/test_ch_foen_fetch.py`, `tests/test_ch_foen_parse.py`, and `tests/test_representative_source_series.py` for Swiss behaviour and recorded evidence.
- Swiss recordings in `tests/test_data/`, including parameter definitions and BAFU pages.
- Current https://api.existenz.ch/ and https://www.hydrodaten.admin.ch/en/questions plus the page's cited BAFU terms PDF. The discovery pass verified the two web pages but did not independently revalidate the PDF.

Older `docs/provider_ports/ch_foen.md` prose contains stale behaviour and is not authority over current implementation and source recordings. Program #284 is historical context, not a source of frozen API signatures.

Use repository-native `uv` execution and follow project instructions. Preserve unrelated work. Update the existing PR, not a replacement provider PR. Restrict changes to the Swiss page, its necessary existing index integration, and directly relevant verification material. Do not change other provider narratives or production behaviour.

Success is an updated PR #289 with a readable current-state Swiss page, executed examples and verified stated outputs, checked factual context, and concise validation evidence. Hand its URL and summary to the user and wait for personal review. Leave PR #289 open and unmerged. Publishing this vision does not start that implementation.
