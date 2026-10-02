# French publication service verification

Public API checks executed on 2026-09-21 after building independent source catalogues.
The retained files are selected from the private source archive, under
`maintenance/verification/french-publication-services/` in the external input tree.
`results.json` records requested scope, source-series facts, source calls and receipt hashes.
`publisher-payloads.tar.xz` contains the exact publisher payloads returned to parse,
under the original `.body` names recorded by `results.json`. For example,
`publisher-payloads.tar.xz!fr_hydroportail-1232000101-discharge-instantaneous-0.body`
names one raw response. `evidence-archives.json` records archive identities and byte-size
comparisons. Tests verify every member against its original receipt hash and length. These checks are bounded
access witnesses, not continuity or completeness claims. HydroPortail reports unknown
licence and citation as informational issues; no licence was inferred.

Run from the code repository root, with a new output directory outside source checkouts:

```sh
uv run python maintenance/verification/french-publication-services/verify_live_products.py \
  --out /path/to/private-output/live-products
```

The script contacts live services and writes responses and results to `--out`.
Keep that directory private. A new acquisition does not replace retained dated evidence
or establish unchanged historical behavior.

The HydroPortail variant checks require an explicit directory containing the selected
retained variant recordings:

```sh
uv run python tests/test_data/fr_hydroportail_variants/verify.py \
  --evidence-dir "$EVIDENCE_ROOT/tests/test_data/fr_hydroportail_variants"
uv run python tests/test_data/fr_hydroportail_variants/verify_public.py \
  --offline \
  --evidence-dir "$EVIDENCE_ROOT/tests/test_data/fr_hydroportail_variants" \
  --out-dir /path/to/private-output/hydroportail-variants
```

Omit `--offline` only for a separate live observation check. To acquire new variant
recordings, run `capture.py --out-dir /path/to/private-output/new-variants` in the same
scripts directory. Keep recordings and detailed failure output outside public logs.
