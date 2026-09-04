# Vision: The library fails loud and states what it needs

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/15

## Goal / Why

A user of RivRetrieve should never be left holding a result that looks complete but is
not, never pay for a network call the library could have refused up front, and never
discover a prerequisite by reading a stack trace. Today the library keeps only part of
that promise.

Unknown identifiers are already refused before any fetch: `find()` and `pick()` raise
`UnknownStationError` or `UnknownProductError` against the packaged catalogue, and
`fetch()` refuses an empty selection with its retained reason. That half is settled and is
not reopened.

The requested window is stricter than it needs to be. `start` and `end` are both required
keyword arguments, so a user asking for "everything since 2020" types today's date by hand.
Nothing compares the window to the present, so a future `end` passes without comment.

Source failure is handled thirteen times, four of them not at all. Each provider's `fetch`
stage carries its own copy of the isolation logic (`usgs_nwis`, `no_nve`, `lt_lhmt`,
`th_thaiwater`), while `ba_fhmzbih`, `ch_foen`, `cz_chmi` and `fr_hubeau` let every
transport failure propagate. Where isolation exists it catches only retry exhaustion and
404, both at severity `warning`; any other non-2xx status raises `FatalContractError` and
discards every station that succeeded. No `error`-severity issue is reachable on the
observation path at all, so the severity the contract reserves for "this failed" is never
used. A per-station exception inside a multi-station `fetch()` aborts the whole call.

Credentials exist only for maintainers. The environment is read in two catalogue
generators and the recording tool; the public `fetch()` path builds a plain HTTP client
and never looks for a key. No `.env` template is committed, python-dotenv is not a
dependency, and `providers()` lists all thirteen ids with no way to tell which need a key
or whether the key is present. A maintainer's working `NVE_API_KEY` does nothing for a
user.

Success is that `fetch()` returns whatever succeeded together with issues that say exactly
what did not; that the window is stated by the caller or defaulted visibly and never
clipped by a guess; that a user can read from `providers()` which sources need what and
whether they have it; and that a missing credential fails once, clearly, before any request,
while the library works fully without it.

## Scope — In

1. **Window defaults.** Make `end` optional on `fetch()` and `fetch_by_provider()`,
   defaulting to the caller's local calendar date treated as a whole day, exactly as a
   bare `YYYY-MM-DD` end is treated today. `start` stays required. The requested window
   the receipt and provenance record is the window actually used, including a defaulted
   `end`. A future `end` is accepted unchanged and attaches one `info` issue stating that
   the window extends past the caller's local date. Nothing clips, because the engine
   cannot know the present in a station's own calendar.
2. **One engine-owned isolation point.** Move per-series source-failure isolation out of
   the providers and into the engine, once, at the point where the engine calls a
   provider's `fetch` stage for one series. Delete the provider-level copies. A
   provider's `fetch` stage raises `TransportFailure` or hands back the response it got;
   it no longer decides what a failure means.
3. **Severity contract for source failure.** For each series:
   - retry exhaustion, timeout, terminal sender failure, refused redirect, and any non-2xx
     status other than 404 produce one `error` issue naming the provider, station,
     product and the failure; the series contributes no rows and every other series is
     unaffected;
   - a 404 produces one `warning` issue, as today, because the source answered;
   - a 401 or 403 from a credentialed provider produces an `error` issue that names the
     credential variable(s) the provider declares, so a wrong key reads as a wrong key;
   - only contract violations remain exceptions: a parse stage returning the wrong shape,
     an undeclared window granularity, an unknown provider kind.
   Under `on_issue="warn"` the caller receives the partial frame and one `RuntimeWarning`
   per `warning` or `error` issue. Under `on_issue="raise"` every series is attempted and
   the engine then raises `IssuePolicyError` carrying all issues. When every series fails
   the result is an empty five-column frame with the issues that explain it, never an
   exception. A multi-station `fetch()` never aborts because one station failed.
4. **Credential declaration.** Each provider's `declaration.py` states the environment
   variable names it requires, as a static tuple beside its catalogue and engine kind:
   `("NVE_API_KEY",)` for `no_nve`, `("ANA_IDENTIFICADOR", "ANA_SENHA")` for `br_ana`,
   empty for the other eleven. Registration refuses a declaration whose required
   variables are malformed the same way it refuses an unknown kind.
5. **Credential resolution at the composition root.** `fetch()`, `fetch_by_provider()`
   and `providers()` are the only public readers of credentials. Resolution order is the
   process environment first, then a `.env` file in the current working directory, using
   python-dotenv without overriding existing environment values. python-dotenv becomes a
   runtime dependency and replaces the hand-rolled dotenv parser in the maintainer
   recording tool, which keeps its explicit `--env-file` behaviour. Resolved values are
   passed down as arguments to the authenticated transport that already exists; no
   provider module, engine module, or catalogue reader reads the environment, and the
   architecture test that bans `os.environ`, `getenv` and `dotenv` inside providers stays
   in force.
6. **Missing credential fails before any request.** When a selection names a provider
   whose declared variables are not all resolvable, `fetch()` raises
   `MissingCredentialError` naming the provider, every missing variable, the two places a
   value is read from, and the template file, before any transport call. A selection
   naming several providers through `fetch_by_provider()` fails as a whole before any
   request. Importing the package never touches credentials.
7. **Credentials never leak.** Resolved values appear in no receipt, provenance field,
   issue message, warning, exception message, log line, or recording. The existing
   secret-free recording and provenance tests extend to the new public path.
8. **A committed template.** Ship `.env.example` at the repository root listing every
   variable any built-in provider declares, each with a comment naming the provider it
   unlocks and the URL where the credential is obtained. `.env` stays gitignored. The
   template is generated or checked from the provider declarations so the two cannot
   drift: a test fails when a declared variable is absent from the template or the
   template names a variable no provider declares.
9. **Credential-aware `providers()`.** Replace the list of ids with a polars frame of
   thirteen rows and three columns:
   - `provider_id`: the manifest id;
   - `credentials`: the declared variable names, a list, empty for open providers;
   - `access`: computed at call time from the same resolution as `fetch()`, one of
     `open` (nothing declared), `ready` (every declared variable resolvable), or
     `missing <comma-separated names>`.
   No credential value is ever placed in the frame. Calling `providers()` again after
   editing `.env` reflects the change.
10. **Update `CONTEXT.md`** where this changes settled language: the isolation point, the
    severity of source failure, and the meaning of a defaulted window end.

## Scope — Out (explicit non-goals)

- Restoring the packaged catalogues of `no_nve` and `br_ana`, and everything about
  credentialed native acquisition and origins. That is Effort #90. Until it lands no
  public selection can name a Norwegian or Brazilian gauge, so this vision proves its
  credential path through an internal selection and the existing Norway recordings.
- Reopening the unknown-identifier rule. A typo raises; a valid combination with no
  catalogue edge is an empty selection with a reason. Landed in #14.
- Clipping, shifting, or reinterpreting any requested window endpoint.
- Retry policy, timeouts, or transport behaviour beyond classifying its outcomes.
- A user cache or serving repeat requests locally (#16).
- Documentation pages and the stale README examples (#18).
- Automating credential acquisition. The template says where to obtain a key; the
  library never requests one.
- Any credential store beyond the process environment and a working-directory `.env`:
  no keychain, no user config directory, no `rr.configure()` holding module state.
- Deleting `docs/adr/` and its references. That is a standalone cleanup outside this
  Effort.

## Constraints

- The observation frame stays `time | time_zone | station_id | product_id | value` and a
  result stays exactly frame, provenance, issues, raw, as #11 landed.
- A requested window is wall-clock and closed at both ends; an endpoint carrying a zone
  is refused. A defaulted `end` is a bare local date and carries no zone.
- `unknown` means the source does not tell us and is never used for a missing credential
  or a failed request.
- Issue severity is exactly `info | warning | error`; `apply_on_issue` acts on `warning`
  and `error` and never on `info`.
- AGENTS.md §2.4: a batch loop over independent items has exactly one named isolation
  point per pipeline. The engine's per-series call is that point.
- AGENTS.md §2.2: only the entry point reads environment variables. `fetch()`,
  `fetch_by_provider()` and `providers()` are the public entry points; the recording
  tool's `main()` is the maintainer one.
- The public surface is functions over an immutable selection; no user-facing object
  carries behaviour or mutable credential state.
- Nothing is published to PyPI, so changing the return type of `providers()` and the
  signature of `fetch()` breaks no released user.
- `CONTEXT.md` is the glossary of record; this vision cites code and `CONTEXT.md`, not
  ADR numbers.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "End defaults visibly",
      "input": "call fetch(selection, start='2024-01-01') with a transport that records every request, on a machine whose local date is D",
      "observation": "the requested window in the returned provenance ends at the last instant of D, the recorded request covers through D plus the engine's fixed padding, and no argument named end was required"
    },
    {
      "name": "Start is never guessed",
      "input": "call fetch(selection, end='2024-12-31') without start",
      "observation": "the call raises InvalidObservationRequestError stating that start is required, and no transport call is recorded"
    },
    {
      "name": "A future end is kept and noted",
      "input": "call fetch(selection, start='2024-01-01', end=<local date plus one year>)",
      "observation": "the provenance requested window ends exactly at the given date, the result carries one info issue saying the window extends past the local date, and on_issue='raise' does not raise for it"
    },
    {
      "name": "One failure does not empty the frame",
      "input": "fetch five series from one provider through a fake transport where the third series' responses time out until retries are exhausted and the fifth returns HTTP 500",
      "observation": "the frame holds rows for series one, two and four; issues hold exactly one error issue for series three naming the timeout and one error issue for series five naming status 500; under on_issue='warn' exactly two RuntimeWarnings are emitted"
    },
    {
      "name": "All failed is an answer, not a crash",
      "input": "fetch two series through a fake transport where both return HTTP 503",
      "observation": "fetch returns an empty five-column frame with two error issues; under on_issue='raise' an IssuePolicyError carrying both issues is raised only after both series were attempted"
    },
    {
      "name": "Isolation exists once",
      "input": "search every providers/*/fetch.py for except TransportFailure and for status-code branching that appends an issue",
      "observation": "no provider fetch stage catches TransportFailure or classifies a status into an issue; exactly one engine module does"
    },
    {
      "name": "A wrong key reads as a wrong key",
      "input": "fetch an internal no_nve selection with NVE_API_KEY set to a value the fake transport answers with HTTP 403",
      "observation": "the result carries one error issue that names NVE_API_KEY and the 403, the frame is empty, and the key's value appears nowhere in the issue, provenance, receipts or warning text"
    },
    {
      "name": "A missing key fails before the network",
      "input": "with NVE_API_KEY absent from the environment and no .env in the working directory, fetch an internal no_nve selection through a transport that records every call",
      "observation": "MissingCredentialError is raised naming no_nve, NVE_API_KEY, the environment, ./.env and .env.example, and the transport records zero calls"
    },
    {
      "name": "A key in .env is enough",
      "input": "with NVE_API_KEY absent from the environment but present in ./.env, fetch an internal no_nve selection through the recorded transport",
      "observation": "the request is made with the credential header, rows are returned, and the recorded request bytes, receipts and provenance contain no occurrence of the key's value"
    },
    {
      "name": "Environment wins over the file",
      "input": "set NVE_API_KEY to value A in the environment and value B in ./.env, then call providers() and fetch an internal no_nve selection",
      "observation": "the transport receives value A and never value B"
    },
    {
      "name": "Import needs nothing",
      "input": "in a fresh interpreter with an empty environment and no .env, import rivretrieve and call find(provider='usgs_nwis', product='discharge_daily_mean')",
      "observation": "import succeeds, the call returns a non-empty selection, and no credential lookup is performed"
    },
    {
      "name": "Providers say what they need",
      "input": "with only NVE_API_KEY set, call providers()",
      "observation": "a thirteen-row frame with columns provider_id, credentials, access; no_nve reads credentials ['NVE_API_KEY'] and access 'ready'; br_ana reads credentials ['ANA_IDENTIFICADOR', 'ANA_SENHA'] and access 'missing ANA_IDENTIFICADOR, ANA_SENHA'; every other row reads credentials [] and access 'open'; the string value of NVE_API_KEY appears nowhere in the frame"
    },
    {
      "name": "The template cannot drift",
      "input": "read .env.example and compare its variable names against the union of every provider declaration's required variables",
      "observation": "the two sets are equal, each template line carries the provider id and an acquisition URL, and a test fails when either side changes alone"
    },
    {
      "name": "Providers still cannot read the environment",
      "input": "run the provider architecture contract tests",
      "observation": "no module under providers/ references os.environ, getenv or dotenv, and the credential-resolution code lives outside providers/ and outside the engine stages"
    }
  ]
}
```

## Decomposition hints

- Start with the isolation point. It is the one change that reshapes the stage contract,
  it deletes code in four providers and adds none in the other four, and every severity
  criterion depends on it. Build the engine's per-series call with a fake transport
  that can fail in each `TransportFailureReason` and each status class before touching
  any provider.
- The severity table is small and should be one function from (failure, provider
  declaration) to `Issue`, so that "403 on a credentialed provider names the variable"
  is a lookup rather than a branch in a provider.
- The window default is independent and small: `ObservationRequest.from_inputs` already
  expands a bare end date to `time.max`; supplying the local date when `end` is `None` is
  the only new case, plus the `info` issue when the normalised end lies past the local
  date. Keep the "no zone on a defaulted end" rule explicit in a test.
- Credentials come in three slices that can land in order without blocking each other:
  the declaration field and its registration checks; the resolver (environment, then
  `.env`, python-dotenv) as one module the two public entry points call; then
  `providers()` and `MissingCredentialError` on top of both. Wire the existing
  `AuthenticatedTransport` and `CredentialExchangeTransport` from `fetch()` last, once
  the resolver exists, using the Norway recordings as the proof.
- Write the never-leaks criterion as part of the resolver slice, not after: search every
  byte of every output for the resolved value while the seams are still being decided.
- The template and its drift test are the tail of the declaration slice.
- Replace the recording tool's dotenv parser with python-dotenv at the same time the
  dependency is added, so there is one resolver in the package.

## Open questions / risks

- The public credential path can be proven only through an internal `no_nve` selection
  until #90 restores that catalogue. If #90 changes how a credentialed provider declares
  itself, the declaration field here is the seam to reconcile; the resolver and the
  `providers()` table should not need to move.
- `br_ana` is `CatalogueOnly` today and its token exchange lands with #213. Its
  declaration here is two variable names; the exchange itself is not wired by this
  Effort and `fetch()` on a Brazilian selection stays impossible until #213 and #90.
- The local calendar date comes from the caller's machine. A user running in a container
  set to UTC will get a UTC date as their default `end`; the receipt shows it, and a user
  who cares passes `end` explicitly.
- Turning non-404 HTTP failures from exceptions into `error` issues means a source that
  is entirely down produces an empty frame and warnings rather than a crash under the
  default policy. That is the intended contract; a caller who wants a crash sets
  `on_issue="raise"`.
- Moving isolation into the engine changes the `fetch` stage contract from #7. Every
  ported provider's recorded tests should pass unchanged, since recordings capture
  responses rather than provider branching; a recording that only exists to exercise a
  provider's own isolation branch is evidence that branch was engine work.
