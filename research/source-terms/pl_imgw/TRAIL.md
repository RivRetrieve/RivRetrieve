# Trail: where did Poland's 1,301 station coordinates come from?

Read `../BRIEF.md` first. This is the second job for this folder, separate from finding
IMGW's terms of use.

## The question

RivRetrieve ships 1,301 Polish gauging stations with latitude, longitude, catchment area
and altitude. Nobody recorded where those numbers came from. We need two facts:

1. **What published source were they taken from?**
2. **Roughly when were they obtained?**

We do not need permission, an opinion, or a favour. Two facts.

## What is already established

All of this is checked and you do not need to redo it.

| When | What happened |
|---|---|
| 2025-10-10 | `poland_sites.csv` first appears in `github.com/kratzert/RivRetrieve-Python` (PR #22, commit `f67f6d8`, Frederik Kratzert). It has **three columns**: `gauge_id, gauge_name, river`. **No coordinates at all.** |
| 2025-11-29 | PR #83 (commits `2a3dff9`, `ec2b9cc`, Frederik Kratzert) rewrites the file with **seven columns**, adding `area, gauge_altitude, latitude, longitude`. The entire change description is *"Update station catalog with more information."* No script, no source, no link. |
| later | RivRetrieve inherits the file. It is now `tests/test_data/pl_imgw_stations.csv`, 1,301 rows. |

So the coordinates are about two months old at the time of writing and were added in one
undocumented step.

## A second defect, found while checking this

The shipped Polish native table stamps every row `retrieved_at = 2025-10-10 18:46:34 UTC`.

That is not a retrieval instant. It is **the git commit timestamp of PR #22** — the commit
that added the file with only three columns and **no coordinates at all**. The coordinates
did not exist until PR #83, seven weeks later, on 2025-11-29.

So the catalogue currently asserts a retrieval date that precedes the data it stamps by
seven weeks. Whatever the answer to the question above turns out to be, that stamp is
provably wrong and cannot be repaired by anything except establishing the real source. It
is the single clearest reason this job matters.

## The strongest clue — start here, not with the email

The numbers themselves say a lot about where they came from.

**Every one of the 2,602 coordinates is an exact multiple of 0.001 arc-seconds.** Not
approximately — all 2,602. For example `49.99362083333333` is exactly 49° 59′ 37.035″.
The long repeating decimals are the fingerprint of a degrees-minutes-seconds value
converted to decimal degrees, and the seconds carry three decimal places.

That is a precision of about **3 centimetres**. Alongside it, altitudes are given to the
millimetre (`184.806` m) and catchment areas to 0.01 km².

A web API does not publish gauge positions to 3 cm. **A surveyed geodetic register
does.** So the source is very likely an official IMGW station register, a hydrological
yearbook annex, or a Polish geodetic dataset — published as a document or a spreadsheet in
DMS, not as JSON from `danepubliczne.imgw.pl`.

**Look for that document.** If you find a published IMGW table whose coordinates match
these in DMS, you have answered the question without needing anyone to reply, and the
answer is stronger than a recollection would be. Save the page with `record.py` and put it
in the Notes of this file.

Useful cross-check: IMGW's live station list at
`danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv`
returns about 913 stations and carries **no** geometry — so it is definitely not the
source, and it is why the coordinates matter: without them we lose about a third of the
Polish network's positions.


### Already ruled out — do not repeat this

The IMGW **hydrological yearbook** is not the source. The full *Rocznik Hydrologiczny 2023*
PDF was downloaded and its own description of the station-list annex ("Wykaz stacji w
układzie hydrologicznym") read: the declared columns are ordinal, station code (CBDH), river
name, station name, W measurement source, river-km, catchment area, and gauge-datum elevation
(Normaal Amsterdams Peil). **No latitude or longitude in any form.**

Yearbook directory, confirmed reachable, if you want to check another edition:
`https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Roczniki/Rocznik%20hydrologiczny/`

### The better lead, untested

IMGW publishes an **INSPIRE Environmental Monitoring Facilities** service covering its
hydro-meteorological network. An EF service carries station *point geometry*, which is
exactly what the public API lacks:

`https://imgw.isok.gov.pl/wss/INSPIRE/INSPIRE_EF_SZS_WMS?service=WMS&request=GetCapabilities`

Nobody has probed it for a WFS counterpart or checked how it encodes coordinates, so whether
it emits DMS with three-decimal seconds is unknown. **Try this before emailing anyone.**

Also unchecked: `danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/`
may hold a station metadata file — only the parent directory was listed.

## The fallback: ask

Frederik Kratzert made the change and is contactable through the GitHub repository
(`github.com/kratzert/RivRetrieve-Python`, PR #83). Ask on the pull request itself so the
answer lands where the change lives.

Draft — keep it short and make it easy to answer:

> Hi Frederik — I'm working on provenance for RivRetrieve's packaged station catalogue and
> I'm trying to account for the Polish coordinates.
>
> PR #83 ("Update Poland station catalog", 29 Nov 2025) added `latitude`, `longitude`,
> `area` and `gauge_altitude` to `poland_sites.csv`. Could you say which published IMGW
> source those came from, and roughly when you obtained them?
>
> The values are all exact multiples of 0.001 arc-seconds, which suggests a DMS register
> rather than the public API — if you still have the original file or the link, that would
> settle it completely.
>
> Thanks!

## What to write down

Put the answer in this file under a `## Answer` heading: the source, the date, and how you
established it. If you got it from a page, record the page with `record.py`. If you got it
from a person, quote their reply verbatim and say where they said it.

**"I asked and got no reply" is a real answer.** Write it down with the date you asked.
Nobody will hold it against you, and it is what we act on.

## Answer

**Source: the Global Runoff Data Centre (GRDC). Obtained: 7 November 2025, by e-mail,
directly from GRDC.**

Established on 2026-08-20 by Thiago Nascimento, who received them. This is an attestation
from the person who obtained the data, not a published page — see *Standing of this answer*
below for exactly what is and is not evidenced.

### What this settles

The coordinates were **never taken from `danepubliczne.imgw.pl`**. They entered the project
through a private transfer from GRDC, a third party that holds national hydrological metadata
as supplied to it by national services. So the Polish rows in the packaged catalogue have two
different origins: the *observations* come from IMGW's public API, and the *coordinates,
catchment areas and altitudes* came from GRDC by e-mail. Anyone reading `finding.md` for
IMGW's terms should know that those terms were not the route these particular numbers took.

### The timeline now closes

| When | What |
|---|---|
| 2025-10-10 | `poland_sites.csv` added, three columns, no coordinates (PR #22) |
| **2025-11-07** | **coordinates received from GRDC by e-mail** |
| 2025-11-29 | coordinates committed, seven columns (PR #83), 22 days later |

The 22-day gap between receipt and commit is consistent with the attestation.

### What the numbers say, re-checked independently

The fingerprint recorded above was re-verified on 2026-08-20 against
`tests/test_data/pl_imgw_stations.csv` (1,301 rows):

- **All 2,602 coordinate values are exact multiples of 0.001 arc-seconds. Zero violations.**
- 2,335 of them use all three sub-second decimal digits, so the precision is really present
  and is not an artefact of rounding something coarser.
- Altitudes carry three decimals in 1,077 rows; catchment areas carry two in 1,167.

This is the signature of a degrees-minutes-seconds survey register, which is what a national
service supplies to GRDC and is not what IMGW's public API emits. The numbers are therefore
consistent with the attestation, and inconsistent with the public API as a source. That is
corroboration, not proof.

### Standing of this answer — read before relying on it

- **Evidenced:** the date, the sender and the route, by the recollection of the person who
  received the e-mail.
- **Consistent with:** the commit timeline, and the DMS fingerprint of the data itself.
- **Not established:** which GRDC product, extract or file this was; whether GRDC in turn
  obtained it from IMGW or from another Polish body; and whether GRDC attaches conditions to
  onward publication of station metadata.
- **No artefact is recorded.** The e-mail and its attachment are the evidence and they are
  not in this repository. If the original message can be saved into `pages/` — even just the
  headers, the date, the sender and the attachment's filename and SHA-256 — this answer stops
  resting on memory. Better still, if the attachment survives, its values can be compared
  against the shipped 2,602 directly, which would settle the question outright.

### Consequence for the wrong timestamp

The defect recorded above is now actionable. The shipped Polish native table stamps every row
`retrieved_at = 2025-10-10 18:46:34 UTC`, which is PR #22's commit timestamp and precedes the
coordinates by seven weeks. On this answer the honest instant for the coordinate columns is
**2025-11-07**, the date of receipt from GRDC.

That fix belongs in the library, not in this survey branch, and is left for a separate change
so this research PR stays reviewable as research.
