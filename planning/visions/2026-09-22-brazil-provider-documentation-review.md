# Brazil provider documentation review

## Intended outcome

Update the existing Brazil provider documentation PR [#276](https://github.com/RivRetrieve/RivRetrieve/pull/276), branch `docs/provider-brazil`, targeting `main`. Deliver a revised `docs/providers/br_ana.md`, a correct link in `docs/README.md` that preserves the other provider links, and an accurate PR description. Preserve Thiago’s accurate explanations and useful structure where possible, while prioritizing consistency, clarity, and correctness.

The original PR predates API and behavior changes incorporated through [#300](https://github.com/RivRetrieve/RivRetrieve/pull/300). This is a migration of the documentation itself, not a migration guide. Readers need only the current behavior. There is no audience requiring backward-looking compatibility guidance.

This is a standalone vision. It does not create a Program or Effort, and publication of this vision does not authorize starting implementation.

## Reader-facing scope

Follow `docs/AGENTS.md` as mandatory writing guidance. Use the current merged provider pages as strong references:

- Switzerland, `docs/providers/ch_foen.md`, PR #289.
- France, `docs/providers/fr_hubeau.md` and `docs/providers/fr_hydroportail.md`, PR #264.
- Japan, `docs/providers/jp_mlit.md`, PR #290.
- United States, `docs/providers/usgs_nwis.md`, PR #266.

Write for an educated hydrology reader with basic Python knowledge. Explain Brazil’s national hydrological context, who measures and publishes the data, and what RivRetrieve provides. Distinguish network operators, measurement producers, and publication services where the evidence supports those distinctions.

Use a compact, practical retrieval example with actual output and explain what the reader should notice. Add examples where needed to explain Brazil-specific choices, particularly consistency levels. Keep the introduction focused rather than turning it into a mechanical API reference. Link to the usage guide for general selection and result handling.

Explain credentials, supported quantities and source selections, units and conversion, time, source status, availability limits, terms, and citation where they affect use. Preserve Portuguese source vocabulary and mark translations as unofficial. Preserve source qualifications and unknowns. Keep null observations, absent rows, and failed requests distinct. Do not infer quality rankings, temporal support, time zones, or national availability.

Keep evidence-gathering methods, catalogue audit mechanics, and receipt internals in maintainer verification records unless they are needed to understand returned data. Do not copy historical implementation narratives into the provider introduction. Avoid unsupported universal claims such as “ANA publishes no formatted citation”; state the bounded finding supported by the sources checked.

## Current repository facts and research leads

These findings were gathered during read-only discovery on 2026-09-22. Recheck them against the implementation revision used for delivery; historical evidence is not authority over current code.

- The original example uses `product=`. Current public selection uses physical filters through `rr.find` and source choices through `rr.pick(..., variant=...)`. Internal product identifiers are not public selection arguments.
- A current daily discharge selection is `rr.find(provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean")`, narrowed with `rr.pick(selection, variant="consistido")`. `tests/test_br_ana_public_daily.py` provides public-path test context. This vision has not executed that example live.
- Daily `bruto` and `consistido` represent source consistency levels 1 and 2. Preserve their separate identities. RivRetrieve does not prefer one, substitute another when the selected one has no observations, or average the levels together. Verify the exact current behavior before promising it.
- Adopted telemetry uses source variants `Vazao_Adotada` and `Cota_Adotada`. Current source facts establish measurement timestamps but do not establish frequency or statistic for those channels. Do not infer those facts from internal identifiers containing `instantaneous`.
- Time zone and daily temporal support remain unknown in the established ANA facts. Explain the practical interpretation without claiming ANA has never documented these facts anywhere.
- Catalogue selection works without credentials. Retrieval requires `ANA_IDENTIFICADOR` and `ANA_SENHA`. `rr.providers()` reports local credential presence, not successful ANA authentication. Process environment takes precedence over the working-directory `.env`, including blank environment values. The ANA identifier is not the account email. Verify the current public setup instructions and authoritative access-request guidance.
- The original page reports 17,914 stations and six candidates per station, with bounded observation evidence at station `15400000`. Recompute catalogue claims rather than carrying these numbers or availability statements forward unchecked. Inventory membership is not a promise of observations for every quantity, source selection, or requested period.
- `src/rivretrieve/_internal/discovery.py`, the ANA provider’s `config.py` and `series.py`, the packaged ANA catalogue, and `tests/test_br_ana_public_daily.py` are implementation leads.
- `docs/provider_ports/br_ana.md` and `tests/recordings/br_ana/` contain useful source dictionaries, daily comparisons, and acquisition evidence. The port document itself contains outdated public examples. Its snippets must not be copied as current API guidance.
- `tests/recordings/br_ana/daily-public-live-verification.json` and `public-live-verification.json` describe historical live checks. They do not prove that a newly authored snippet works through today’s public API.

No code defect was established during discovery. No ANA live request was made and credentials were not inspected. Live credential readiness remains unknown.

## Verification and success evidence

Check every factual claim against current code, the packaged catalogue, or authoritative sources, as appropriate. In particular, verify institutional responsibilities, access instructions, source meanings, and terms against authoritative ANA material rather than treating old PR prose as proof. Record the sources, dates, relevant revision, and limits of the checks. If a source cannot be freshly accessed, distinguish retained historical evidence from a fresh content check; do not invent confirmation.

Execute every final code snippet through the current public API in the project’s `uv` environment, in its documented order and with the stated prerequisites. Check non-Python setup examples safely as well. Use owner-provisioned credentials through normal composition boundaries; never request that secrets be pasted into chat or publish them in code, logs, recordings, receipts, or PRs.

Use live retrieval where applicable, rather than substituting recordings or cached observations for a live claim. Verify displayed values, row counts, units, time labels, series selections, issues, and promised behavior. Outputs must come from the exact final examples. Explain that source observations can change and bound successful retrieval evidence to the station, selection, and period actually tested. Prefer a small useful window over an unverified full-year example.

Retain inspectable verification evidence separately from the provider introduction. Clearly distinguish live checks, recorded-source regression tests, authored tests, and incomplete checks. A passing recorded test does not establish fresh service access. Missing credentials or a source outage is a verification blocker, not automatically a code defect; report it and do not claim the required live verification complete.

Review the complete PR diff and use independent review to check source fidelity, writing consistency, executable examples, and the accuracy of the revised PR description. The description must report actual changes, commands/results, and material limitations rather than repeat stale claims from the original PR. No production change, catalogue regeneration, new provider capability, general documentation rewrite, or migration guide belongs in this work.

## Mandatory code-defect stop condition

If implementation discovers a code defect, stop the documentation implementation. Open an issue labelled `bug`, assigned to `CooperBigFoot`, with reproducible steps and evidence. Use [#305](https://github.com/RivRetrieve/RivRetrieve/issues/305) and [#324](https://github.com/RivRetrieve/RivRetrieve/issues/324) as examples of precise reports that distinguish public-path failures, instrumentation failures, source failures, and test-assumption errors.

Include the tested revision, commands, expected and actual behavior, source-response evidence where available, and preserved evidence locations without secrets. Do not fix production code, bypass a broken path, or conceal the defect by changing the documentation example or claim. Preserve partial work and report the blocking issue. If issue creation or assignment fails, report that failure and remain stopped.

Wait until the user explicitly reports that the defect is repaired. An issue being closed or a repair commit appearing is not a substitute for that instruction. Then reverify the affected behavior and final examples against the repaired implementation before continuing.

## Delivery and human authority

Deliver by updating PR #276, not by replacing it with a new implementation PR. Preserve unrelated work and the original contribution where possible. Reconcile the existing branch with current `main` safely and keep the current provider index intact.

The user reviews the updated PR before merging and will provide feedback before the implementing agent concludes. Present the revised PR and verification evidence, wait for that feedback, and address it. Independent agent review does not replace this human gate. Do not declare the implementation complete while that gate is outstanding.

The implementing agent must never approve or merge PR #276 on the user’s behalf. Generic implementation-workflow merge authority does not override this restriction. The separate PR publishing this vision may be merged through the authorized vision-publication workflow; that grants no approval or merge authority over the Brazil documentation PR.
