# Finland SYKE user documentation

Write `docs/providers/fi_syke.md`, completing step 7 of the
[provider-port guide](../../docs/maintenance/provider-ports.md) for
[Effort #759](https://github.com/RivRetrieve/RivRetrieve/issues/759) under
[Program #353](https://github.com/RivRetrieve/RivRetrieve/issues/353).

## A stale path in the Effort's own text

#759's body names `docs/provider_ports/fi_syke.md` as a second deliverable
("maintainer notes"). That path does not exist for any shipped provider:
checked directly against `au_bom`'s own real, merged step-7 commit
(`4eee2d0a`, PR #696) — it touched exactly `docs/providers/au_bom.md`,
`docs/README.md`, `docs/station-metadata.md` and `mkdocs.yml`, nothing under
`docs/provider_ports/`. That directory exists only on the unrelated
`research/new-country-candidates` branch, from an older pre-port research
process this port never used. Following the real, current precedent instead
of the Effort's stale boilerplate text.

## What I wrote

`docs/providers/fi_syke.md`, following `cz_chmi.md`'s overall shape (closest
structural match: three quantities, open access, no credentials, CC BY 4.0)
and `ba_fhmzbih.md`'s exact "What you can retrieve" table convention for an
undetermined statistic (`Frequency`/`Statistic` = `Unknown`, matching the
guide's own explicit instruction to reuse that handling rather than invent a
new one). Verified live against the real API on 2026-11-08 rather than
reusing a stale example: discharge at station `894` (Ruskeakoski, Jänisjoki),
January 2020, one week.

Headlines a genuinely unusual, already-established fact ahead of most other
providers' pages: stage is an absolute water-surface elevation relative to a
national height datum, not a small gauge-relative reading (step 3, #755) —
worth surfacing prominently since every other provider's stage section says
the opposite ("vertical reference not established" or "gauge zero").

Also states, from real external sources checked during this port (not
fabricated): some stations are measured by regional ELY-centres rather than
Syke directly (per CAMELS-FI's own metadata documentation), and `Paikka_Id`
is independently confirmed as the per-station identifier by both Syke's own
public map service and CAMELS-FI (steps 2-3, #754-755).

Updated the three supporting files exactly like `au_bom`'s precedent:
`docs/README.md` and `mkdocs.yml` (new Finland entry, alphabetically between
Czechia and France), and `docs/station-metadata.md`'s "Fields by provider"
table, regenerated via `docs/scripts/metadata_fields.py --write` (reverted
one incidental, unrelated line the generator also touched: `usgs_nwis`'s
field name had drifted from the currently-committed doc independently of
this work; out of scope here).

Did not add a `tests/test_fi_syke_documentation.py`-style recorded-replay
test that executes the page's example against pinned recordings. Several
provider pages have one, but `au_bom`'s own step 7 — the precedent this
whole port follows — did not add one either; staying consistent with what
actually shipped rather than introducing new scope.

## Verification

- `uv run pytest --logic-only tests/test_documentation.py tests/test_supporting_documentation.py`:
  10 passed.
- Full `uv run pytest --logic-only -q` stays green.
- The page's own example re-verified live on 2026-11-08, output pasted
  exactly as returned.

## Completion

Post a concise status update on #759. Keep #759 open until the PR merges.
