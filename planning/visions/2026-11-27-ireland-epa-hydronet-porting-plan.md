# Ireland EPA HydroNet porting plan

Deliver faithful, traceable access to the agreed EPA HydroNet scope through
RivRetrieve's public discovery and retrieval APIs. Organize the work under
[Program #875](https://github.com/RivRetrieve/RivRetrieve/issues/875) using the
seven steps in the [provider-port guide](../../docs/maintenance/provider-ports.md).

This vision records the staged plan. Publishing it or creating the Efforts does
not complete #875. The Program's completion condition is delivery of the agreed
scope, required verification and user documentation, followed by approved final
review and merge into `main`. Final review is a Program completion condition,
not an eighth guide Effort.

## Efforts

| Step | Effort | Focus |
| --- | --- | --- |
| 1 | [Source, scope and access](https://github.com/RivRetrieve/RivRetrieve/issues/1101) | Recheck HydroNet access and terms. Establish the agency boundary and overlap with OPW, water-body types and candidate products, including whether spot gaugings belong in scope. |
| 2 | [Station catalogue and metadata](https://github.com/RivRetrieve/RivRetrieve/issues/1106) | Establish station identities, regional paths, descriptive metadata and actual station-product availability. Build toward reproducible offline discovery for the scope established in Step 1. |
| 3 | [Series identity and physical meaning](https://github.com/RivRetrieve/RivRetrieve/issues/1100) | Establish discharge and water-level meanings, relative versus absolute levels, units, vertical references, timestamps, DST and source annotations. Recheck the proposed interpretations in #875 against genuine evidence across relevant regions and products. |
| 4 | [Retrieval behavior](https://github.com/RivRetrieve/RivRetrieve/issues/1102) | Establish full-history versus rolling archive behavior, completeness, historical reach, revisions, empty responses and failures for the agreed scope. |
| 5 | [Provider integration](https://github.com/RivRetrieve/RivRetrieve/issues/1104) | Connect the agreed scope to public discovery and retrieval APIs, with focused tests. Use the catalogue, physical meaning and retrieval contracts established in Steps 2–4; return to research where an assumption remains unsupported. |
| 6 | [Verification](https://github.com/RivRetrieve/RivRetrieve/issues/1105) | Verify the complete integration against genuine retained source evidence, including historical reach and relevant cache, catalogue and distribution behavior. Investigate EStreams as a suitable observational comparison dataset; it is a research lead, not an established benchmark. |
| 7 | [User documentation](https://github.com/RivRetrieve/RivRetrieve/issues/1103) | Explain the delivered products, access, interpretation and limitations with a verified example. Follow the shared provider-page layout and keep documentation consistent with verified behavior. |

Step 1 establishes the source and product scope. Steps 2–4 establish the
catalogue, physical meaning and retrieval contracts needed for integration.
They may inform one another; later evidence can reopen an earlier conclusion.
Step 5 delivers the agreed behavior. Evidence retention, tests and documentation
develop throughout the work. Steps 6 and 7 finish against the delivered behavior.
These are meaningful handoffs, not a requirement to postpone all code until
Step 5 or all verification until Step 6.

## Decisions still to establish

The research in #875 is exploratory. Its endpoint descriptions, counts, proposed
filters, source mappings and architectural suggestions are leads to recheck,
not approved implementation requirements. No source or product scope was adopted
when this plan was published.

- Step 1 must resolve agency boundaries and OPW overlap, water-body types and
  candidate products, including spot gaugings. Do not silently include or exclude
  them based on the exploratory issue.
- Step 3 must establish physical meanings and series distinctions. In particular,
  recheck relative versus absolute water levels, historical vertical references,
  timestamp rendering, daily support and DST behavior. A single-station pattern
  does not justify a provider-wide time interpretation.
- Step 4 must establish acquisition behavior before choosing full-history or
  rolling archives. The issue's proposed implementation is not binding.
- Step 6 must determine whether EStreams supplies a suitable comparison dataset.
  Use the guide's comparison requirements when a suitable dataset is available;
  record why if none is suitable. Check historical reach separately.

Leave reversible implementation choices to the relevant Effort. Investigate
source facts rather than asking the maintainer to guess them. Bring material
scope trade-offs or unresolved blockers back for a maintainer decision.

## Evidence and acceptance

Follow the provider-port guide and its linked testing and evidence guides.
Find or establish one continuing research record in the private evidence archive,
shared by all seven Efforts. Keep original inputs, findings, corrections and open
questions connected through that process. Public issues carry safe summaries and
links; do not copy private material into this repository.

Preserve source identities, annotations and unknowns. Keep null values, absent
rows and failed requests distinct. Do not infer source judgment, time zones or
physical meaning. Pause only the capability that would otherwise require an
unsupported assumption, and expose the consequence for the maintainer. Obtain
authorization before sending agency correspondence.

Acceptance requires working public discovery and retrieval for the agreed scope,
checks backed by the required genuine evidence, and documentation that matches
what users can retrieve and how they should interpret it. Missing mandatory
evidence blocks acceptance. Keep [tracker #870](https://github.com/RivRetrieve/RivRetrieve/issues/870)
current; scaffolding this plan does not mean Step 1 has started.

## Starting point and handoff

At planning time, #875 had no adopted scope decisions or discussion comments,
tracker #870 listed it as unstarted, and current `main` had no `ie_epa` provider.
Recheck current issue decisions and repository state before starting an Effort.
The proposed provider identifier remains `ie_epa` pending Step 1.

Resume with `grill-me 1101` for source, scope and access. Each Effort
can develop its own confirmed handoff at the depth needed for its work. This
Program-level plan does not settle those details or authorize automatically
running all seven Efforts. Publication starts no research or implementation.
