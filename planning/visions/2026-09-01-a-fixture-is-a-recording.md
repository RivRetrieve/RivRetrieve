# Vision: a fixture is a recording

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/13

## Goal / Why

Charting audited all thirteen providers for the fetch/clip calendar mismatch and found it in
eleven: RivRetrieve asked each source in the source's own calendar and trimmed the answer in UTC,
so the edges of every window are wrong. The engine has since taken ownership of every window
arithmetic, with two always-on invariants. That closed the arithmetic and left the declarations
open — a provider still declares its window granularity, stop convention, rendering vocabulary and
day definition, and the engine obeys them without being able to check them. A wrong declaration
reproduces the original wrong day on top of a correct engine.

The corpus that would catch it cannot. Of the eleven unported providers, nine hold observation
payloads under 2.5 KB written by hand rather than captured: Czechia's entire daily-flow payload is
five rows of round numbers, Norway's hourly payload is three readings, Brazil's station is
`12345000`. Three providers' fake transports return the same payload whatever window is asked for.
`ba_fhmzbih` ships a test that issues exactly the corrupting request and asserts the corrupted
answer, and it is green. Meanwhile the catalogue side of this repository attests every native
station table with exact URLs, retrieval instants, counts and digests across four sanctioned
capture routes; that rigour was never extended to observation payloads.

Success is that a test fixture becomes a recording of a real interaction with a real source, that
replay resolves a request rather than answering unconditionally, and that each ported provider
carries one executable claim about what its source actually published at a local midnight. After
this lands, the eleven ports in #17 are graded against the world rather than against a previous
author's belief, and a window-ignoring fake is unconstructible rather than merely absent.

## Scope — In

1. The transport seam, which does not exist today. `usgs_nwis/fetch.py:52` constructs
   `HttpClient()` inline and tests substitute it by monkeypatching the provider module's
   `HttpClient` attribute, so nothing can supply a transport from outside. `drive` supplies the
   transport to `fetch`, extending the `ProviderStages.fetch` contract, because the transport is
   the same for every provider and ADR 0008 puts what is the same for every provider in the engine.
2. A recording format carrying the exact request issued, the exact response bytes, the retrieval
   instant and a digest.
3. Replay that resolves a request and fails when it holds no recording matching it, so a fake that
   ignores the requested window cannot be written and a divergent window-rendering declaration
   surfaces as a missed lookup.
4. A repeatable recording procedure — a command that re-records a provider's corpus — so a
   recording is never a one-time campaign.
5. Real recordings for `usgs_nwis`, the only ported provider that issues HTTP at fetch time, which
   is the proving ground for the apparatus before eleven ports depend on it.
6. A shared boundary-probe harness parametrised over ported providers, asserting three literals per
   provider-product: returned reading count, first wall-clock time, last wall-clock time, over a
   recording whose readings straddle local midnight in the source's own calendar.
7. Deletion of every interior baseline that compares the port against retired-implementation output
   over an invented payload.
8. Removal of the fake-transport pattern that answers regardless of the window asked for.
9. The testing policy in `AGENTS.md`: fixtures are recordings, boundary-probe expectations are
   authored independently of the port's code and output, and the three-literal limit that keeps
   them auditable. Plus the NumPy-docstring constraint, which `AGENTS.md` does not yet carry and
   which #18 generates the documentation site from.

## Scope — Out (explicit non-goals)

- Porting any of the eleven remaining providers. #17 owns that; this vision builds what #17 is
  graded by, and proves it against the one ported provider that exercises it.
- The Warsaw boundary probe itself. It was ratified in the grill, and it requires `pl_imgw` to be
  ported, which it is not. It lands in #17 under this vision's harness; what this vision delivers
  instead is the harness refusing a ported provider-product that carries no probe, which is the
  thing that forces #17 to write it.
- `ca_eccc` recordings and a `ca_eccc` boundary probe. It reads a local SQLite cache, issues no HTTP
  request at fetch time, and publishes no sub-daily product, so it has no transport interaction to
  record and no local midnight to straddle. Its store-shaped receipt work belongs to #12's remaining
  milestones.
- Detecting drift. No network access happens in this vision. Recordings carry the request and the
  instant a later job needs; re-issuing them and reporting divergence is #9's on-demand live
  workflow and the scheduled monitor the Map still leaves unspecified.
- Deleting the invented payloads under `reference/legacy_observations/`. ADR 0011 keeps the legacy
  tree as reading material for porting, and a previous author's belief about a source's shape is
  worth reading. What ends is promoting one into a live fixture or a baseline.
- Re-running the retired implementations. The audit established the old code was wrong; the open
  question is whether the new code is right.
- A second, test-side parser per provider to derive expectations mechanically. Rejected: for
  Japan's fixed-width files and Bosnia's workbooks that parser is nearly as hard as the real one,
  with its own bugs.
- Mechanically enforcing independent authorship. It is a process rule in `AGENTS.md` with no
  enforcement; the three-literal limit is the mitigation.
- Any change to the engine's window arithmetic or its two always-on invariants.

## Constraints

- There is no transport seam today. `HttpClient` is constructed inside
  `src/rivretrieve/_internal/providers/usgs_nwis/fetch.py` (the only construction site in `src/`),
  and `ProviderStages.fetch` in `src/rivretrieve/_internal/driver.py` takes no transport argument.
  Creating that seam is inside this vision and is the single point at which recording and replay
  happen; this vision does not add a second. `HttpClient(sender=...)` already accepts an injected
  `Sender`, so the change is to who constructs the client, not to how it sends.
- `ca_eccc` reads a local SQLite cache and issues no HTTP request at fetch time, so the seam change
  must not assume every provider needs a transport.
- The recording envelope reuses what already exists rather than inventing a format: `AGENTS.md`
  attestation content for native tables, and the ADR 0023 `publisher_payload` receipt envelope. A
  recording travels in; a receipt travels out; they are the same bytes.
- Request headers never enter a recording, matching ADR 0018 and ADR 0023, so a credential has no
  route in.
- For the two bulk providers a recording is a committed compiled observation store under the ADR
  0022 shape and the ADR 0021 rules; they touch no network at request time.
- The executor's network is disabled. Every criterion in this vision must be runnable offline
  against committed bytes; capture itself is performed outside the executor and supplied as a step
  input under the `AGENTS.md` attestation routes.
- `uv run pytest` is the test command. `uv run <command>` for everything else.
- Boundary-probe expectations are limited to three literals per provider-product. A larger
  assertion is out of contract, because an expectation nobody can audit by eye is
  indistinguishable from one nobody wrote.
- ADR 0024 governs this vision and is Proposed; it moves to Accepted within it.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "Window-ignoring fake cannot answer",
      "input": "Ask a replay transport for a window no committed recording covers",
      "observation": "The replay fails naming the unmatched request; no payload is returned and no fallback recording is substituted"
    },
    {
      "name": "Wrong rendering declaration is caught",
      "input": "Flip a ported provider's declared stop convention from inclusive to exclusive and run that provider's suite",
      "observation": "The replay lookup misses and the suite fails; it does not pass with a shifted window"
    },
    {
      "name": "Bosnia's corrupting request is unavailable",
      "input": "The four-day ba_fhmzbih discharge_daily_mean request that returned 61.858 against a true 157.738",
      "observation": "The product does not exist and the request is refused by name; no averaged value is returned"
    },
    {
      "name": "A ported provider without a boundary probe is refused",
      "input": "Register a provider-product as ported and give it no boundary probe, then run the harness",
      "observation": "The harness fails naming that provider-product as unprobed; it does not pass by silently having nothing to check"
    },
    {
      "name": "USGS keeps the last local hour",
      "input": "The Arizona sub-daily window whose final reading sits at 23:00 local",
      "observation": "That reading is present in the result and labelled 23:00 local, not dropped or relabelled"
    },
    {
      "name": "An invented payload cannot ground a probe",
      "input": "Point a boundary probe at an observation payload carrying no recorded request and no retrieval instant",
      "observation": "The probe is refused for absence of a recorded request; it does not run against the payload"
    },
    {
      "name": "No baseline compares two implementations",
      "input": "Search the committed suite for an assertion against retired-implementation output over an observation payload",
      "observation": "No such assertion exists anywhere in the suite"
    },
    {
      "name": "Drift is detectable without provider knowledge",
      "input": "Run the re-record command in its no-network mode against any committed recording",
      "observation": "It prints the request URL, its parameters and the retrieval instant read from the recording alone, consults no provider-specific code, and issues no request"
    },
    {
      "name": "An oversized probe is refused",
      "input": "Register a boundary probe asserting a fourth literal beyond reading count, first wall-clock time and last wall-clock time",
      "observation": "The harness refuses the probe naming the extra assertion; the probe does not run"
    }
  ]
}
```

## Decomposition hints

- The recording envelope and the replay seam come first and are the only thing everything else
  depends on. Their own criteria are runnable against a synthetic recording of a synthetic source,
  so they do not wait on any capture.
- The refusal behaviours are cheaper than the captures and catch design errors earlier: an
  unmatched request failing, and a probe refusing a payload with no recorded request, are both
  runnable before a single real byte is captured. Order them before capture.
- Capture is supplied from outside the executor. Split any criterion that has an offline half:
  the envelope's shape and the refusal paths are offline; a real `usgs_nwis` or `ca_eccc` recording
  is a step input under attestation.
- `usgs_nwis` already has plausible real payloads including a DST-day fixture at 2023-03-12 and one
  boundary test; `ca_eccc` has a 1.1 KB payload and no boundary test at all, and is one of the two
  providers the audit called safe. Expect the `ca_eccc` recording to be the harder of the two and
  the one that tells you whether the apparatus works for a provider with nothing to start from.
- The `AGENTS.md` policy text and the NumPy-docstring constraint touch no code and block nothing;
  they can land in parallel with anything.
- The interior-baseline deletions and the fake-transport removal are the last thing, because they
  remove the current suite's only coverage of the affected paths and should follow the replacement
  rather than precede it.
- Moving ADR 0024 from Proposed to Accepted belongs with the package that makes its central claim
  real, not in a documentation package of its own.

## Open questions / risks

- Independent authorship has no mechanical enforcement and its failure mode leaves no trace in a
  diff: an author who ran the port before writing the three literals produces a passing probe that
  proves nothing. The run must not weaken the three-literal limit to make a probe easier to write,
  because that limit is the only thing keeping a wrong expectation visible to a reviewer.
- Whether any source will refuse to yield a boundary-straddling recording is unknown until capture
  is attempted. Under the settled rule such a provider delays its own port in #17 rather than
  shipping with a labelled unknown; nothing in this vision may introduce a path that ships an
  unproven boundary with a warning attached.
- The suite's correctness becomes a statement about a moment. A source that renames a field leaves
  every replayed test green while the library is broken against the live source. This is accepted
  and its answer is #9's; the run must not attempt to compensate for it with network access.
- The two providers this apparatus is proved against are the two the audit called least affected:
  `ca_eccc` is timezone-blind with no sub-daily product, and `usgs_nwis` was already the one
  provider with a boundary test. The apparatus may therefore look adequate here and prove
  insufficient at the first genuinely hostile source. Prefer a harness parametrised over providers
  from the first provider onward rather than one generalised later.
- `RawMode` and `RawPayload` are still importable from `_internal.observations` and still named in
  `tests/test_usgs_nwis_observations.py`, though ADR 0023 withdrew them. Recording work touching
  those imports may collide with #12's remaining milestones.
