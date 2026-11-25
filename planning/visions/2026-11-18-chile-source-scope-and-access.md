# Chile source, scope and access

Establish the source, supported products and geography, access and terms for an initial Chile provider. This vision delegates the whole of [#739](https://github.com/RivRetrieve/RivRetrieve/issues/739), step 1 of [Program #734](https://github.com/RivRetrieve/RivRetrieve/issues/734), to the executing agent. Successful delivery completes #739; publication of this vision does not. The outcome is an evidence-backed source and scope decision with a usable handoff to later Efforts, not provider implementation.

## Direction and authority

Historical and operational river data remain desired. Compare DGA and CR2 without a preferred winner. The agent owns investigation and selection of the supported initial source, products and geographical scope, including narrowing that scope where evidence requires it. Do not return routine research or engineering choices to the maintainer. Escalate material blockers that prevent a defensible result or require changing these agreed boundaries.

Nicolas reported no DGA reply as of 2026-11-18. Continue without making correspondence a blanket blocker. Silence does not confirm source meaning or grant permission. Establish required facts from available authoritative evidence, preserve unknown facts where they can be represented honestly, and defer capabilities that would require guessing. A later reply can reopen the scope decision and lead to provider updates. Do not send new correspondence without authorization.

## Starting evidence

Read #739 and its comments, the current Program context and the [port vision](2026-11-06-chile-provider-port.md). Continue the existing [private Chile research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/cl-dga-source-access.md). It contains correspondence context and exploratory observations from 2026-11-06, not certified source inputs. Recheck material findings before adopting them; do not repeat the interview or wait indefinitely for an agency reply.

The recorded starting position is:

- DGA historical daily and monthly discharge downloads worked for one region. The sample had three stations and gaps; national completeness was not established. Daily aggregation, time zone and some coordinate interpretations were unresolved.
- CR2 Explorer returned genuine daily discharge and explicitly described daily means, but catalogue counts and documented coverage disagreed. Bulk access, versioning, freshness and terms remained unresolved. CR2 is a compilation and must not be presented as an unchanged agency publication.
- Successful operational discharge retrieval was not established. Earlier HTTP 403 responses described those requests from that environment, not universal unavailability or permission to bypass access controls.
- Public accessibility did not settle automation, storage, reuse, redistribution or attribution conditions. Neither DGA nor CR2 had a fully established applicable terms basis for the intended integration.

These are research leads, not a selected source or implementation contract.

## Required result

Follow step 1 of the [provider-port guide](../../docs/maintenance/provider-ports.md) and the existing [evidence process](../../docs/maintenance/evidence.md). Investigate enough to select and justify an initial scope:

- Identify the measuring agency and publication route, supported products and geography, and meaningful differences between direct DGA publication and CR2 compilation.
- Establish ordinary access routes, access requirements and applicable use conditions, including automation, storage, reuse, redistribution and attribution. Distinguish what the sources explicitly establish from unresolved applicability; do not infer an open licence from a download button or apply the software licence to source data.
- Obtain small genuine metadata and observation examples for the selected routes through the archive's established intake process, subject to retention permissions. Link adopted claims to evidence and distinguish documented scope from observed coverage and freshness.
- Record which capabilities are supported, deferred or blocked and why. Operational discharge remains deferred unless a working, supported route is established. Missing facts such as daily aggregation or time zone must remain unknown, not guessed. Unknown required quantity or unit, unsupported access conditions, or claims of completeness without evidence cannot be repaired by a caveat.
- Hand off source-specific questions to the later catalogue, physical-meaning and retrieval Efforts when they do not block step 1. Explain the affected capability and what those Efforts still need to establish. Do not expand step 1 into full catalogue construction, provider integration or source certification.

Keep one continuing private research record with dated findings, supporting references, correspondence status, corrections and open questions. Use the archive's existing processes for retained original material; authored notes do not replace original evidence. Keep controlled material and correspondence out of the public repository, issues, logs and artifacts. Report unavailable mandatory evidence as blocked.

## Program coordination and completion

Update #739 with a safe summary of the selected source and initial scope, access and terms findings, evidence links, limitations and handoff. Close it only when step 1 has a defensible result. If no viable scope can be established, leave it open and report the precise blocker and maintainer decision needed; an unanswered inquiry alone is not a blocker for every independent capability.

Update the Effort list in #734 to reflect the established scope and actual progress. Mark step 1 complete only when #739 is completed. Adjust descriptions or scope notes for affected later Efforts where the findings require it, preserving their links and unfinished status. Keep deferred capabilities and their consequences visible; do not silently drop operational ambitions or mark research as provider delivery. Preserve unrelated Program content and explain material scope changes in a concise comment.

The remaining delivery boundaries stay unchanged: work belongs on `port/cl-dga`; this vision does not authorize implementing steps 2–7, merging the provider to `main`, or weakening the mandatory ten-basin CAMELS-CL comparison in step 6. Thiago (@thiagovmdon), confirmed in #734's comments, owns final review in #738 after all seven delivery steps. Research findings may identify downstream blockers, but do not authorize changing those acceptance requirements.

Completion leaves a fresh agent able to explain what the initial provider will retrieve, from whom, through which supported route, under which established conditions, and what remains for later Efforts. Source selection and reversible research methods are delegated; unsupported interpretations and permissions are not.
