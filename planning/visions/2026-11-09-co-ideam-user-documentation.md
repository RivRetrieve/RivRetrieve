# Colombia IDEAM user documentation

Author the user-facing provider guide (`docs/providers/co_ideam.md`) and register
navigation and metadata cross-links for Colombia's IDEAM (`co_ideam`) on
`port/co-ideam`. Delivering this vision and its documentation contract tests
completes [Effort #727](https://github.com/RivRetrieve/RivRetrieve/issues/727)
under [Program #460](https://github.com/RivRetrieve/RivRetrieve/issues/460).

Work targets `port/co-ideam` and leaves `main` unchanged.
[Effort #728](https://github.com/RivRetrieve/RivRetrieve/issues/728) covers final
review and merge into `main` once Steps 1 through 7 and their controlled
verification receipts are complete.

## Scope

Follow [provider-port step 7](../../docs/maintenance/provider-ports.md#7-user-documentation)
and the [documentation language guidelines](../../docs/AGENTS.md):

- Add `docs/providers/co_ideam.md` with the shared six-column retrieval table
  header (`| Quantity filter | Source field / \`variant\` | Frequency | Statistic | Source unit | Returned unit |`),
  a live- and replay-verified retrieval example at station `0011017010`
  (`AGUASAL [11017010]`), and concise explanations of ten-digit zero-padded
  station codes, flowing-watercourse catalogue scope (`1,372` river gauges),
  separation from legacy `HIS_*` Socrata views, unknown `Frequency` and
  `Statistic` on `CAUDAL_H` and `NIVEL_H`, `cm -> m` `gauge_zero` stage scaling
  with unknown vertical datum and horizontal `crs`, daily S3 regeneration and
  bounded `[first_observation, last_observation]` local caching, 1992-1993
  *Hora Gaviria* wall-clock shifts and preserved `nivelAprobacion` source
  labels, and `CC BY-SA 4.0` ShareAlike attribution terms.
- Register `docs/providers/co_ideam.md` in `docs/README.md`, `mkdocs.yml`, and
  `docs/station-metadata.md` (regenerating the `fields-by-provider` table via
  `docs/scripts/metadata_fields.py --write` and noting IDEAM's `CC BY-SA 4.0`
  ShareAlike terms under `Data rights`).
- Verify offline discovery claims, six-column table alignment against all `20`
  packaged series, zero em dashes, strict MkDocs site generation, and exact
  recorded example output in `tests/test_co_ideam_documentation.py`.
