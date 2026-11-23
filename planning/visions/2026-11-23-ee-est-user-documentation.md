# Estonia Keskkonnaagentuur user documentation

Author the user-facing provider guide (`docs/providers/ee_est.md`) and register
navigation and metadata cross-links for Estonia's *Keskkonnaagentuur* (`ee_est`)
on `port/ee-est`. Delivering this vision and its documentation contract tests
completes [Effort #946](https://github.com/RivRetrieve/RivRetrieve/issues/946)
under [Program #352](https://github.com/RivRetrieve/RivRetrieve/issues/352).

Work targets `port/ee-est` and leaves `main` unchanged.
[Effort #947](https://github.com/RivRetrieve/RivRetrieve/issues/947) covers final
review and merge into `main` once Steps 1 through 7 and their controlled
verification receipts are complete.

## Scope

Follow [provider-port step 7](../../docs/maintenance/provider-ports.md#7-user-documentation)
and the [documentation language guidelines](../../docs/AGENTS.md):

- Add `docs/providers/ee_est.md` with the shared six-column retrieval table
  header (`| Quantity filter | Source field / \`variant\` | Frequency | Statistic | Source unit | Returned unit |`),
  a live- and replay-verified retrieval example at station `SJA8821000`
  (`Ahja HJ`), and clear explanations of national `SJA*`/`SJB*` identifiers,
  EstModel daily vs. `f_hydroseire` UTC hourly route separation, the `60`
  inland flowing-water river gauges (`56` active hourly + `4` EstModel-only,
  excluding `5` lakes, `15` coastal gauges, `60` hydrochemical stations,
  `type=VALIDATION`, `V`, `/estimates`, and `KAIA SWAT`), partial availability
  at `SJA5432000`, `SJB4433000`, and `SJB4488000`, `cm -> m` hourly stage
  conversion with `gauge_zero` vertical reference and unknown vertical datum,
  `EPSG:3301` -> `EPSG:4326` horizontal coordinates, single-source metadata (`nimi`,
  `veekogu_nimi`, `area` in `km2`, omitted `elevation`), 19th-century EstModel
  reach and 25-year chunking, `f_hydroseire` `20,000`-row cap and `timeline_ts_utc`
  handling with `vaartus: null`, `ee_est.estmodel` `qualityFlag` annotations,
  and `CC BY 4.0` + *Keskkonnaseire seadus* § 13(4) attribution terms.
- Register `docs/providers/ee_est.md` in `docs/README.md`, `mkdocs.yml`, and
  `docs/station-metadata.md` (regenerating the `fields-by-provider` table via
  `docs/scripts/metadata_fields.py --write` and noting *Keskkonnaagentuur*'s
  terms under `Data rights`), and update `docs/assets/coverage-map.png` via
  `docs/scripts/coverage_map.py`.
- Verify offline discovery claims, six-column table alignment against all `18`
  packaged products, zero em dashes, strict MkDocs site generation, and exact
  recorded example output in `tests/test_ee_est_documentation.py`.
