# French provider documentation verification

Checked on 2026-09-21 against target `31bd527169b6fb67f0a7b3b692eed53a7fd190d7`.
No provider implementation changed. This record supports the two provider guides;
it is not a claim of continuous availability or complete historical coverage.

## Exact documented examples

From the repository root, use a **new** output directory:

```sh
uv run python maintenance/verification/french-provider-documentation/verify_live_examples.py --out .worktrees/evidence/french-provider-examples-fresh
```

The verifier reads every Python/Output block in each final page and executes the
code verbatim, in page order, through RivRetrieve's public API. Both retrievals
explicitly use `cache="bypass"`. RecordingTransport wraps the normal live HttpClient;
it does not supply recorded responses. Each displayed output is compared exactly.
The dated directory retains page hashes, output comparisons, row counts, source
identities, every reported issue, and exact v2 source exchange recordings.

- Hub'Eau: seven daily mean discharge rows for Y251002001, 2024-01-01..07;
  unknown daily zone; m³/s; no issues.
- HydroPortail: 50 validated station-own instantaneous discharge rows for
  Y251002001, 2020-01-01..02; UTC clock labels; m³/s. Two informational issues
  remain visible: unknown licence and citation. Both dependent selection snippets
  show their actual identities. No failed source requests or verification gaps.

Offline replay reads these same source envelopes and executes the same markdown:

```sh
uv run pytest -q tests/test_fr_hubeau_documentation.py
```

The original Hub'Eau recording and all delivered HydroPortail scientific regressions
remain unchanged. Replay demonstrates reproducibility, not current reachability.
Initial output collection used a `PENDING` placeholder for the new HydroPortail
output and deliberately failed comparison. Observed output replaced it before
final verification. That initial evidence is preserved locally under
`.worktrees/evidence/effort-313-initial-example-run/`, not presented as acceptance.

## Provider facts and authoritative references

`sources/REPORT.md` maps claims to current code, catalogues, retained functional
research and freshly checked authoritative pages. `sources/authoritative-pages.tar.xz`
retains exact response bytes, check scripts, full URL/status/date/SHA-256 manifests,
text extractions and catalogue inspection output. Paths in that report refer to
archive members unless they identify repository evidence. `sources/SHA256SUMS`
identifies the archive itself. Extract to a new evidence directory to inspect or
rerun its acquisition scripts with `uv run`; never overwrite the dated acquisition.

Every source-table URL returned HTTP 200 on the check date. The current station
form, rather than the incomplete measurement-series help list, establishes all
four HydroPortail selectors. The temperature page's stale approximate count and
conflicting update-cadence prose are not copied. Unknown daily day boundaries,
temperature zone/support, HydroPortail licence and historical measurement authorship,
and the `most_valid` algorithm remain unknown in the pages.

The fresh Hub'Eau example payload also retains `code_statut`, `libelle_statut`,
`code_methode`, `libelle_methode`, `code_qualification` and `libelle_qualification`.
This supports the metadata paragraph without deriving a quality ranking or
claiming observation flags appear in the harmonised table.

## Primary and supporting documentation review

The required human review set is `README.md`, `docs/usage.md`,
`docs/providers/fr_hubeau.md`, and `docs/providers/fr_hydroportail.md`.
README and usage were read in full. Their counts, distinct provider identities,
selection behavior and issue guidance are already correct; they remain unchanged.

```sh
uv run python maintenance/verification/french-provider-documentation/inspect_provider_counts.py
```

`provider-counts.txt` records 14 registered providers: 11 live, 2 bulk, 1
catalogue-only. Observation access therefore covers 13 providers, as README states.
French catalogue station counts remain 7,347 and 6,409. The source report also
checks Hub'Eau's 6,475 hydrometry and 872 temperature stations.

`docs/README.md` now links both reader-facing pages and accurately labels the
existing combined French maintainer port note. There is no separate HydroPortail
port-note file to link. No generated reference change is needed.

## Acceptance boundary

A review-ready PR is not completed delivery. Explicit approval from Nicolas Lazaro
is required before merge. No issue closure, delivery marker, landed marker or
Program Map change is authorized by this verification.
