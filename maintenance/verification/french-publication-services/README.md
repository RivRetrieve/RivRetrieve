# French publication service verification

Public API checks executed on 2026-09-21 after building independent source catalogues.
`results.json` records requested scope, source-series facts, source calls and receipt hashes.
The `.body` files are exact publisher payloads returned to parse. These checks are bounded
access witnesses, not continuity or completeness claims. HydroPortail reports unknown
licence and citation as informational issues; no licence was inferred.

Run from the repository root with `uv run python maintenance/verification/french-publication-services/verify_live_products.py`.
The script writes a new `live-products/` output directory beside itself. Do not replace
retained dated evidence without recording the new acquisition.
