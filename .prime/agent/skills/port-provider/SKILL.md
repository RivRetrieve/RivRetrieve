---
name: port-provider
description: Guide evidence-led research and integration of a new RivRetrieve provider or an expansion of an existing provider.
---

# Port a provider

Turn a source publication into a faithful RivRetrieve integration. Use the code
requirements to guide research: the catalogue supports selection, provider code
requests and reads source data, and the shared engine performs common operations.

Start from the relevant provider issue and current repository state. Treat earlier
research and third-party adapters as leads to recheck, not authority for source
meaning or current access. Identify the intended scope and the next unresolved
step before investigating. Use [the step guide](references/steps.md) for concrete
outcomes and code references; read the references needed for the current work.

## Progress through evidence-backed steps

1. Establish source, scope and access.
2. Establish the station catalogue and metadata.
3. Establish series identity and physical meaning.
4. Establish retrieval behavior.
5. Integrate the supported scope with the shared engine.
6. Verify the complete integration against genuine source evidence.
7. Document supported behavior and limitations for users.

These steps organize progressive research and meaningful delivery outcomes. When
planning a Program, use them as candidate Effort boundaries, adapting them to the
actual provider rather than inventing work. Do not research or implement the whole
port simply because this skill was loaded. Follow the user's requested scope and
existing discovery, planning and review workflows. Loading this skill does not
publish issues, contact an agency or authorize implementation.

Research thoroughly enough to defend each adopted claim. Recheck documentation,
representative responses and relevant exceptions. Validate apparent inconsistencies
before escalating them. Later findings can reopen an earlier conclusion. Evidence
retention, tests and documentation develop throughout, not only in the final steps.

## Keep one continuing research record

Use the private [verification-evidence repository](https://github.com/RivRetrieve/verification-evidence)
for the provider's continuing research document and evidence. Find an existing
record before creating another. Keep established findings, dated checks, supporting
references, corrections, correspondence and open questions together across Efforts.
For each material unknown, explain which implementation or user claim it affects.

Use the archive's existing intake and verification process for original material.
The research document connects evidence; it does not replace original responses or
certify a claim by recording it. Public issues carry safe summaries and handoffs.
Keep private material and correspondence out of public code, issues and artifacts.
Private storage does not establish permission to retain or disclose source material.

## Resolve or expose missing information

Investigate material gaps and prepare focused questions for the institution. Record
what was checked, what was asked and any answer. Obtain authorization before sending
correspondence. Do not treat silence as confirmation or require an answer to every
question before any independent capability can proceed.

- Proceed when required facts are established.
- Preserve unknown facts when the engine can represent them honestly.
- Pause an affected capability when proceeding would require guessing, such as
  assigning an unestablished quantity or unit, or claiming incomplete data is complete.
- Distinguish a missing source fact from a limitation in the shared engine.

When investigation and correspondence cannot resolve a material blocker, present
its consequences to the maintainer. The maintainer decides whether to narrow the
scope, deliver a truthful limited capability, defer it or abandon it. Documentation
cannot make an unsafe interpretation acceptable.

## Finish with a defensible result

Account for the supported scope, evidence behind material claims, completed checks
and remaining limitations. Use the existing [testing guide](../../../../docs/maintenance/testing.md)
and [evidence guide](../../../../docs/maintenance/evidence.md), not a new verification
system. Missing mandatory evidence blocks acceptance; it is not a passing check.
Keep user documentation consistent with the delivered behavior. Stop at the requested
handoff or review boundary.
