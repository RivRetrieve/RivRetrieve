# SENAMHI frequency and statistic meanings

Establish evidence-backed frequency and statistic meanings for the supported
SENAMHI series, and carry the findings through mappings, tests and documentation.
Completing this work completes [#668](https://github.com/RivRetrieve/RivRetrieve/issues/668).
Publishing this vision does not complete the issue or authorize implementation.
Work targets `port/pe-senamhi`; keep `main` unchanged.

The provider page currently explains unknown frequency by reference to an unknown
statistic. These are independent facts: a series can publish one value per day
without establishing whether that value is a mean or an instantaneous reading.
Correct that explanation and investigate whether the current `not_established`
mappings omit facts supported by source evidence. Do not assume every unknown
can be resolved.

## Scope and interpretation

Cover PHISIS DAILY `current`, `minimum` and `maximum`, HOURLY `value`, and all nine
supported station-archive water-level fields:

- `NIVEL_DEL_RIO_06H`, `NIVEL_DEL_RIO_10H`, `NIVEL_DEL_RIO_14H`,
  `NIVEL_DEL_RIO_18H`, `NIVEL_DEL_RIO_PROMEDIO`;
- `N_NIVELAGUA`, `N_NIVELMEDIO`, `N_NIV_INST_00`, `N_NIV_INST_10`.

Assess frequency independently from statistic, temporal support, day boundaries
and time zone. Published labels are evidence to investigate, not automatically
standardized physical facts. Distinguish clock-hour labels from sampling
intervals and monthly request partitions from observation frequency. Do not
infer clock times from the less-understood `N_NIV*` suffixes, or daily means from
daily labels and regular timestamps. Preserve distinct series and source values.

For each field, establish what the evidence supports and where it applies.
Do not generalize a station practice or manual passage to every API field and
historical record without a supported connection. Where a fact remains unknown,
explain the missing evidence. Preserve the distinction between a fact not yet
established and one the source explicitly leaves unspecified.

## Research and evidence

Continue the private [SENAMHI research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md)
and the [series-meaning vision](2026-11-01-senamhi-series-identity-and-physical-meaning.md).
The retained frontend/manual findings support limited claims; they do not yet
establish all field meanings. The hydrometry manual describes scheduled readings
and an arithmetic average estimating daily level, with qualifications for high
flow. Its applicability to specific API fields and records needs investigation.
Earlier suggestions of daily means and Lima time were superseded; do not restore
them without new applicable evidence.

Start with retained material and bounded research in official documentation and
frontend behavior. Follow the [provider-port guide](../../docs/maintenance/provider-ports.md)
and [evidence process](../../docs/maintenance/evidence.md). Retain applicable
originals privately and bind adopted claims to reviewed evidence. Any further
source requests must be bounded and at most one per second. A full historical
scan is not required.

If gaps remain, return with focused questions and a proposed agency enquiry.
Sending requires explicit approval; no enquiry has been sent. An agency reply is
not a prerequisite for supported corrections or completion. Keep original
responses, correspondence and restricted receipts out of public repositories,
logs and distribution packages.

## Corrections and completion

Update supported mappings and aligned catalogue metadata where the evidence
warrants a change. Keep unsupported facts unknown and ensure they cannot satisfy
filters that require established physical facts. Use existing domain contracts;
leave reversible implementation details to the implementing agent. Broader
retrieval redesign, new products and changes to unrelated physical meanings are
outside this work.

Correct the [provider page](../../docs/providers/pe_senamhi.md) so its tables and
prose agree with the supported mappings. Explain frequency and statistic
separately and distinguish missing evidence from source silence. Keep research
details in the continuing private record rather than expanding user documentation
into an investigation log.

Protect changed behavior with focused tests under the [testing guide](../../docs/maintenance/testing.md).
Run affected source-independent checks and applicable full genuine-input checks
at reviewed revisions. Rebuild and review packaged products if their mappings
change. Synthetic tests establish library behavior, not source meaning. Missing
mandatory evidence blocks the affected claim; it is not a passing verification.

Completion requires findings for every scoped field, justified corrections in
mappings and documentation, applicable verification, and a clear account of
remaining unknowns and their evidence gaps. Report exact code and archive
revisions and verification outcomes. A complete investigation may leave values
unknown.

Under [Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534), this
bounded investigation and resulting corrections must finish before
[final review #610](https://github.com/RivRetrieve/RivRetrieve/issues/610).
Do not wait indefinitely for agency clarification. The existing requirement for
Thiago's explicit approval before merging the port into `main` remains unchanged.
