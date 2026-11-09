# Evidence-backed source annotation design

## Outcome

Explore, prototype and recommend a shared representation for source-published
annotations in RivRetrieve. Users should be able to discover what annotations
exist, understand their source meanings, inspect them alongside measurements and
apply their own analysis rules without parsing publisher receipts. Give discovery
and understanding equal emphasis to analysis workflows. Provider authors also
need a clear way to preserve and expose source information.

This vision authorizes the experiment in [#783](https://github.com/RivRetrieve/RivRetrieve/issues/783).
Completing its research, prototypes and evidence-backed recommendation completes
that experiment issue. Return the findings to the originating design discussion,
[#621](https://github.com/RivRetrieve/RivRetrieve/issues/621), which remains open.
The maintainer will resume that discussion to understand the recommendation and
prepare a presentable design with the team, including Thiago and Freddy. Team
review can revise it. Production adoption requires separate explicit authorization.

The deliverable is an opinionated recommendation supported by evidence, not just
a catalogue of alternatives. Lead with concrete user experience and examples,
then explain the representation, provider integration and supporting evidence.
The maintainer should not have to reconstruct the design from research logs.

## Established context

Read #783 and the later comments on #621 before starting. The latter supersede
its original production-oriented framing with a design-first outcome.

- #621 records that USGS validates then discards separate `approval_status` and
  `qualifier` fields. Its recorded live example contains observations that are
  both `Approved` and `ESTIMATED`. Recheck the current implementation and source
  evidence; preserve these as separate source facts.
- NRFA documentation describes a flag string alongside a value. Genuine examples
  and vocabulary remain work to verify in [#595](https://github.com/RivRetrieve/RivRetrieve/issues/595).
  Coordinate with that research rather than treating the documentation as proof
  of observed values or starting the whole NRFA port.
- [Architecture](../../docs/architecture.md) separates physical facts, source-series
  identity, observations and provenance. The current
  [store contract](../../docs/design/observation-store-layout.md) preserves native
  bulk columns without making them ordinary public observation annotations.
  Store-excerpt receipts cannot reconstruct publisher content discarded during
  live parsing. Storage retention alone does not meet this experiment's UX goal.
- Earlier source-series work in #284 excluded a general observation-qualifier
  carrier. Bulk preservation in #514/#517 does not settle the public design here.

These are starting facts and historical evidence, not constraints to preserve an
awkward existing API. Inspect the current checkout before designing around them.

## Explore broadly, deepen what is promising

No representation or preferred winner is selected. Explore credible clean
alternatives, try them in code, and deepen the promising ones as evidence develops.
There is no fixed cap of two designs or two provider integrations. Cheap prototypes
are useful for learning; they do not justify unnecessary production machinery or
an exhaustive tournament. Let material unanswered design questions guide effort.

Use contrasting providers and genuine source differences to challenge candidates.
USGS is a useful possible first end-to-end example, not the limit of research.
Adapt existing providers in isolated experimental work where that tests the design.
Awkward provider exceptions or information loss are reasons to revisit a candidate.
Select providers and prototype depth through investigation, not another routine
approval round with the maintainer.

Investigate observation-, interval- and whole-series annotations using concrete
source examples. These scopes are questions to test, not a commitment to a universal
metadata system. Do not manufacture a source example to fill a category. Record
unavailable evidence and distinguish synthetic demonstrations from genuine cases.

Exercise the complete path through retrieval, cache reuse, refresh and bundle
export/roundtrip for the promising designs. Compare user workflows and provider
authoring as well as representation mechanics. Show how users discover fields and
publisher meanings, inspect values and absence states, and apply their own rules
with ordinary analysis tools. Do not require a dedicated quality-filtering API.

Preservation without optional publisher receipts should be the proposed default.
Test that proposal across the complete path; do not make annotation availability
an incidental consequence of receipt retention. This does not change the library's
cache defaults or authorize national downloads without required consent.

## Fidelity and boundaries

Preserve source vocabulary, separate fields, types and established meanings,
including absent and unknown information. Link annotations to the observations or
published scope they describe. Preserve distinct source-series identities and
native duplicate multiplicity; time alone must not silently collapse distinct
observations. Keep null values, absent rows, successful empty answers and failed
requests distinct. Missing source knowledge must remain unknown.

Do not invent cross-provider quality scores, rank source judgement, automatically
exclude measurements or infer unpublished hydrological products. A user's explicit
analysis rule is their choice, not a library recommendation about scientific quality.
Investigate how annotations remain correctly associated through clipping, conversion,
partial results and successful or failed refreshes. Do not hide fatal internal
contract errors under caller issue policy.

[#602](https://github.com/RivRetrieve/RivRetrieve/issues/602) concerns provider-specific
station metadata. Capture transferable findings about typed source fields, original
names, shared projections and documentation/discoverability. Do not assume station
metadata and observation annotations need one representation. Implementing #602,
settling its open team questions, and building a universal metadata framework are
outside this experiment.

Experimental provider and shared-engine changes are authorized to obtain evidence.
They are not production adoption. Keep prototypes clearly separated from shipped
behavior, and do not rewrite current user documentation to present them as available
features. No production rollout, blanket provider migration or prototype merge into
the runtime is authorized by this vision.

## Evidence and deliverables

Use project-native tools and the existing testing approach. Follow
[provider research guidance](../../docs/maintenance/provider-ports.md),
[verification evidence requirements](../../docs/maintenance/evidence.md) and
[test guidance](../../docs/maintenance/testing.md). Run through `uv`; keep temporary
stores and caches isolated. Use test-first development for experimental code.

Retain genuine material through the private archive's maintained processes. Review
exact executable revisions before running with private inputs or credentials.
Keep controlled source bodies, receipts and detailed restricted outputs out of
public issues, code, logs and artifacts. Missing mandatory evidence is blocked,
not silently skipped or replaced by synthetic data. Provider notes are leads,
not substitutes for original responses and established meanings.

Return a concise synthesis to #621, linking durable, inspectable artifacts rather
than dumping research logs. Preserve safe prototype code and reproduction
instructions so a fresh agent can inspect the result. The handoff should contain:

- A recommended design with concrete inspection, discovery and analysis examples,
  an explanation of its representation and provider-author workflow, and why it
  best meets the objectives.
- The credible alternatives explored, what was actually prototyped, why candidates
  were discarded or revised, and the trade-offs behind the recommendation.
- Provider-fit evidence, including genuine source differences, supported annotation
  scopes, unknowns and any awkward exceptions. Distinguish verified behavior,
  synthetic demonstrations and untested proposals.
- Results for retrieval, cache reuse/refresh and export, with source fidelity and
  annotation associations checked rather than inferred from a successful run.
- Relevant cost measurements where they could change the recommendation. Separate
  correctness from performance; compare equivalent outputs and account for
  preparation or deferred work. State data/settings, revisions and measurement
  limits. No fixed timing target or new benchmarking platform is required.
- Limitations, unresolved evidence gaps, lessons relevant to #602 and the decisions
  the maintainer/team should discuss before adoption.

Completeness means enough contrasting evidence to defend a recommendation and its
limits, not implementing every possible representation or every provider. Do not
claim a supported source scope without its required evidence. If a material blocker
prevents a defensible recommendation, report its consequences instead of silently
narrowing the agreed outcome or declaring the experiment complete.

Candidate selection, implementation mechanisms, experiment ordering and routine
measurement choices remain the investigating agent's responsibility. Return to the
maintainer for substantive scope changes or decisions that evidence cannot resolve.
