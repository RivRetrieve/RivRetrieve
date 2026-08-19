# A shipped value carries its acquisition record

RivRetrieve ships a station's value only where it can state, from its own records, how
that value came to be held: what was requested, from where, and when. Where it cannot,
the value is withheld and the withholding is declared. This is a claim about the limits
of our own knowledge, applied identically to all thirteen sources, and it is not a
reading of anyone's terms.

The alternative was to gate shipping on redistribution rights, which is what the Effort
ticket set out to do. It cannot be done without breaking ADR 0004. Deciding that a
source's terms forbid publishing its station list, and dropping that provider's
catalogue, publishes our interpretation more loudly than the rejected `open |
attribution | restricted` field ever would — silently, through what is absent from the
wheel, where nobody can read it or correct it. Relocating the gate to provenance removes
the interpretation entirely: the terms are still established and published, verbatim, as
the source's own words, and the judgement they support stays with the reader, which is
where ADR 0004 already put it.

Evidence in the ADR 0012 sense points at a source's own documentation and answers *what
the source says*. An acquisition record answers a different question — *how we came to
hold this* — and the two are not interchangeable. The four origin forms all assert a
source, so there was no way to declare an inherited value honestly, and a value with no
sayable origin was certified as coming from a named native column whose own origin was
never asked about. The gate was one level deep and the hole was one level down.

A finding about a source is a recording, on the terms ADR 0024 fixed for observation
fixtures. A licence claim backed by a bare URL proves what its author believed, and the
page it points at is overwritten by the agency without notice — the same failure that
let eleven providers hold a boundary defect while their tests passed. So a finding
carries the retrieved page, the instant, and a digest, and the quoted text must occur in
those bytes. That check is mechanical and it is the one that matters, because the
research is delegated and will be conducted with AI assistance: a plausible URL paired
with a plausible quotation is precisely what a language model produces when the page does
not say what it was asked to find.

## Consequence: one inherited file is a debt, and its stamp is already false

The two suspected orphans turned out not to be alike, and the difference is instructive.

`jp_mlit` is already compliant and was before this ADR existed. Its native table is built by
requesting MLIT's own per-station register once per station, keeping a manifest of the URL,
byte count, SHA-256, HTTP status and retrieval instant for each, and refusing any response
lacking the expected source marker. Its coordinates are MLIT's own `世界測地系` field in
degrees-minutes-seconds. The inherited `japan_sites.csv` is no longer read by anything.
Chasing it to the end was still worth it: a deleted script, `data-raw/GaugeData.R`, shows
those legacy coordinates were never MLIT's at all but a filtered extract of the GSIM archive
taken from a personal drive — so the file we stopped using was also mis-attributed.

`pl_imgw` is the real debt, and it is worse than unestablished. Its 1,301 coordinates arrived
in PR #83, "Update station catalog with more information", with no script and no source. The
shipped native table stamps every row `retrieved_at = 2025-10-10T18:46:34Z`, which is the git
commit timestamp of PR #22 — a commit that contained no coordinates at all. The coordinates
appeared seven weeks later. The catalogue therefore asserts a retrieval instant that precedes
the data it stamps, and no mechanism in the origin gate could have caught it, because the gate
checks that a value matches its native column and never asks what the native table's own stamp
means. Poland is partly re-derivable — the live IMGW roster yields about 881 usable coordinates
against 1,301, at coarser precision — because the endpoint the fetcher uses returns only id,
station name, river and hydrological code.

Forensics narrow the search rather than leaving it open: all 2,602 Polish coordinates are exact
multiples of 0.001 arc-seconds, with altitudes to the millimetre and catchment areas to
0.01 km². That is a degrees-minutes-seconds register converted to decimal degrees, not a web
API, and it is what should be looked for.

Withheld geometry is declared rather than deleted. The inherited file stays in the repository,
the columns state why they are withheld, and restoring them is a single edit once the
acquisition is established.
