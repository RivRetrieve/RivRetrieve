# NRFA provider documentation

Finish the existing NRFA provider page so users can retrieve the supported data
and interpret its limits without reconstructing the source investigation.
Delivery of this vision completes [#593](https://github.com/RivRetrieve/RivRetrieve/issues/593).
Publishing this vision alone does not complete that issue.

## Scope

Review and finish `docs/providers/uk_nrfa.md` against the completed integration
and verification on `port/uk-nrfa`. This is a documentation finishing pass, not a
new provider implementation or a repeat of source verification.

- Explain the publisher, supported ten flow/stage products, access requirements,
  source-series distinctions, time and units, availability limits, annotations,
  terms and unresolved facts that affect interpretation.
- Check existing claims against delivered behavior and established evidence.
  Improve wording where users would otherwise need implementation knowledge.
  Preserve unknowns and distinctions rather than simplifying them into promises.
- Run and verify the existing practical daily-flow example through the public
  API. Explain what its result demonstrates and how to interpret it. Keep one
  concise example unless another is needed to explain a materially different
  product. Successful retrieval does not establish continuous coverage.
- Link general API guidance rather than repeat it. Follow `docs/AGENTS.md` and
  step 7 of `docs/maintenance/provider-ports.md`.

## Existing verification and evidence

[Step 6 (#583)](https://github.com/RivRetrieve/RivRetrieve/issues/583) is complete
on the port branch through [#905](https://github.com/RivRetrieve/RivRetrieve/pull/905)
at `f9c3d1d6e1de61cb7a0728a1e0990c2ba42e8ba0`. Its completion record covers
all ten products and the required reproducible ten-gauge CAMELS-GB comparison
of daily gauged flow through RivRetrieve's public API. Use those findings;
this documentation effort does not require repeating the comparison.
CAMELS-GB uses NRFA data, so the comparison is a shared-source consistency
check, not independent measurement validation or verification of the other
nine products.

Keep detailed research, correspondence and controlled evidence in the
[continuing private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-source-access.md).
The private archive also holds the
[comparison report](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-camels-gb-comparison.md)
and its ten-gauge figure. Their existence does not authorize republication in
public user documentation. Follow the established evidence process when
consulting controlled material or retaining new verification evidence.

## Delivery and autonomy

Resolve routine documentation choices and verification mechanics independently.
Return to the maintainer for unresolved source claims or meaningful scope changes;
do not guess source meaning or silently expand this into corrective implementation.
Missing evidence needed to verify the example or a material claim must remain
visible as a blocker.

Success means the page agrees with delivered behavior, its practical example has
been run and checked, and users can understand the supported capability and its
limits. Report the example checked, relevant documentation checks and remaining
limitations. Leave reversible wording, layout and example mechanics to the
implementing agent.

Keep documentation changes on `port/uk-nrfa`, following
[provider coordination #347](https://github.com/RivRetrieve/RivRetrieve/issues/347).
Final provider review [#597](https://github.com/RivRetrieve/RivRetrieve/issues/597)
and Thiago's explicit approval to merge the port into `main` remain separate.
This vision authorizes neither that merge nor expansion of the settled provider
scope.
