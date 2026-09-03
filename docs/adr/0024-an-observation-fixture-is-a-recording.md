# ADR-0024: An observation fixture is a recording

## Status

Accepted

## Context

Charting audited all thirteen providers for the fetch/clip calendar mismatch and found it
in eleven. The suite could not express any of it: no test constructed a request in a
non-UTC zone, and three providers' fake transports returned the same payload whatever
window was asked for. `ba_fhmzbih` ships a test that issues exactly the corrupting request
and asserts the corrupted answer, and it is green.

The Program has since moved every window arithmetic into the engine, with two always-on
invariants that raise on a fetch window that fails to contain the request or a row outside
it. That closes the arithmetic but not the declarations: a provider still declares its
window granularity, stop convention, rendering vocabulary and day definition, and the
engine obeys them without being able to check them. A wrong declaration reproduces the
original wrong day on top of a correct engine.

Eleven ports remain, and the corpus they would be graded against does not support grading.
Of the eleven unported providers, nine hold observation payloads under 2.5 KB written by
hand rather than captured — Czechia's entire daily-flow payload is five rows of round
numbers, Norway's hourly payload is three readings, Brazil's station is `12345000`. Only
Switzerland's CSVs and Bosnia's workbooks are real. The catalogue side of the repository is
the opposite: `AGENTS.md` carries per-provider attestation of every native station table
with exact URLs, retrieval instants, counts and digests, across four sanctioned capture
routes. That rigour was never extended to observation payloads, and the Map's count of "41
committed fixtures covering every provider" is true by count and false in substance.

Two alternatives were considered and rejected. Specifying payloads by hand from each
source's documentation, labelled honestly as specifications rather than captures, is cheap
and expressible — but a boundary probe against an authored payload authors the bug and then
authors its fix, and an interior comparison over authored numbers is two programs agreeing
about a river nobody measured. Re-running the retired implementations against a shared
recording to show the wrong answer and then the right one is the strongest possible
before-and-after — but ADR 0011 archived those eleven implementations as reference text to
read, executability would couple the new suite to code this Program deletes provider by
provider, and it is impossible for `ba_fhmzbih`, whose defect was aggregation into a
product that no longer exists.

The premise that capture is human work was withdrawn during discovery: it was a fact about
the PCE executor's network being disabled, not about capture. South Africa's 403 is a
`User-Agent` header, which the archived legacy client already sets.

## Decision

An observation fixture is a recording of a real interaction: the exact request issued, the
exact response bytes, the retrieval instant, and a digest, made and replayed at the single
injectable transport seam every provider already passes through. Replay resolves a request
and fails when it holds no recording for one, so a fake that ignores the requested window
cannot be written and a wrong window-rendering declaration surfaces as a missed lookup.
Recording is a repeatable procedure rather than a one-time campaign, and each recording
carries what to ask and when it was last asked. For the two bulk providers, which touch no
network at request time, the recording is a committed compiled store under the ADR 0022
shape.

Every ported provider-product additionally carries a boundary probe: the specific defect
the charting audit found for it, converted into an executable claim about what its source
published, over a recording whose readings straddle local midnight in the source's own
calendar. The probe asserts three literals — returned reading count, first wall-clock time,
last wall-clock time — and its expected values are authored from the recording and the
source's documentation by an author with no access to the port's code or output. The
retired implementation is not re-run.

Invented observation payloads ground nothing. They remain under
`reference/legacy_observations/` as ADR 0011 reading material and are never promoted into a
live fixture, and the interior baselines resting on them are deleted rather than ported
forward — superseding the Program decision that recorded interior baselines as still valid.

This vision performs no network access and detects no drift. It makes drift detectable by
whatever spends the seam later.

## Consequences

The defect class the audit found becomes structurally inexpressible rather than merely
absent: a window-ignoring fake is unconstructible, and the one declaration class the engine
cannot verify is verified by request matching.

The eleven remaining ports each acquire a recording campaign and a boundary probe, so #17
becomes heavier per provider. A source that will not yield a boundary-straddling recording
delays its own port rather than shipping a labelled unknown, because a user can reason about
a station whose zone is unknown and cannot reason about a provider whose edges might be off
by a day.

The suite's correctness becomes a statement about a moment. A source that changes its field
names leaves every replayed test green while the library is broken against the live source.
Detecting that is #9's on-demand live workflow and the scheduled monitor the Map still
leaves unspecified; this decision only guarantees the recorded request and instant they
would need.

Independent authorship binds only whoever reads `AGENTS.md`. It is a process rule with no
mechanical enforcement, and its failure mode — an author who ran the port before writing the
expectation — is invisible in the diff. The three-literal limit is the mitigation: it keeps
each expectation small enough that a wrong one is visible to a reviewer rather than buried
in a 2,500-line provider test, which is what the two existing ports look like today.

### Falsified consequence: South Africa's 403 is not a User-Agent header

On 2026-09-03 the `za_dws` port sent `HyData.aspx` requests from its network with the archived
legacy client's `Mozilla/5.0` header, a full current Chrome header, the python-requests default
and the engine's fixed `RivRetrieve` header, over IPv4 and IPv6, and every one returned HTTP 403
with the same Apache "You don't have permission to access this resource" body; the catalogue
acquisition had already met the same refusal from two other egress points on 2026-08-02. The
sentence in the context above attributing the 403 to a missing `User-Agent` is therefore
falsified: the host refuses those networks, not that header. The rule stands unchanged. Recording
the South African evidence requires an egress the host accepts, and no per-provider header
escape hatch is introduced; the exact attempts are recorded in `docs/provider_ports/za_dws.md`.
