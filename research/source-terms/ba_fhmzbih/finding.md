# Source terms finding — ba_fhmzbih

Agency: Federal Hydrometeorological Institute FHMZBiH
Country: Bosnia and Herzegovina
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

**NOT FOUND.** No terms, licence or citation page was located. This is a genuine result,
not a gap to fill — but it deserves one manual pass before you accept it.

| URL | Lang | What was seen |
|---|---|---|
| https://vodostaji.voda.ba/ | bs | **JS-only** — the served HTML is a loading placeholder. `record.py` will save nothing useful; use a browser |
| https://www.voda.ba/vodostaji | bs | Nav and footer carry no legal link; a bare copyright line names *Agencija za vodno područje rijeke Save* |
| https://www.fhmzbih.gov.ba/latinica/HIDRO/vodostaji.php and `/HIDRO/index.php` | bs | No copyright, terms or data-use link |
| https://www.voda.ba/dokumenti | bs | **Not inspected.** Plausible home for a policy document — check this first |

**Note the operator split:** `vodostaji.voda.ba` is run by *Agencija za vodno područje
rijeke Save*, not by FHMZBiH. Terms could sit with either body, so look at both. If nothing
turns up, a direct enquiry to the agency is the right next step — record the reply.

## licence

- Page URL: https://vodostaji.voda.ba/data/html/impressum.html
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T09:31:25+00:00
- Language: bs
- Agency publishes nothing: yes

No statement of terms of use or licence is published by either body. The recording is the
service's only "about" document, saved as evidence that the statement is not there. The
nearest things found are quoted in Notes, and neither is a licence.

```text
```

## citation

- Page URL: https://vodostaji.voda.ba/data/html/impressum.html
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T09:31:25+00:00
- Language: bs
- Agency publishes nothing: yes

```text
```

## Notes

**The folder's "NOT FOUND" is superseded. There is a statement, and it is on the exact host
we fetch from.** `vodostaji.voda.ba` is a JavaScript application, but its Impressum is served
as a plain document at `https://vodostaji.voda.ba/data/html/impressum.html`, inside an iframe.
`record.py` fetched it directly — no hand-saving was needed. It was found by booting the app
in a browser, opening the `Impressum` menu item and reading the iframe's `src`.

**Neither body publishes terms of use.** Both slots are marked `Agency publishes nothing:
yes` under BRIEF §4, with the pages recorded as evidence of absence. Two statements were found
and neither is a licence; both are quoted here rather than in the slots, so that nobody later
reads them as the terms.

The Impressum, on the exact host we fetch from, says this about the data:

```text
Svi podaci koji se prikazuju i koji se dobiju kao rezultat pretrage su informativnog karaktera i ne mogu služiti kao zvanični podaci.
```

That is a statement about the standing of the data — informational in character, not usable as
official data. It is not a licence, not a grant or refusal of permission to reuse, and not a
citation request. No reading of what it permits is offered here.

**Citation: nothing published either.** No citation or attribution wording exists anywhere on
either host.

### The operator is not the agency this folder is named after

RivRetrieve's `ba_fhmzbih` provider fetches from three endpoints, all on `vodostaji.voda.ba`:

```
/data/internet/layers/20/index.json
/data/internet/stations/stations.json
/data/internet/stations/{group}/{station_id}/{code}/{file}
```

That host is run by **Agencija za vodno području rijeke Save (AVP Sava)**, not by FHMZBiH.
FHMZBiH is not in our data path at all. The folder raised the operator split as a possibility;
it is settled.

The payload itself carries a `BODY_RESPONSIBLE` field per station, whose values across the 230
stations in `stations.json` are:

| Stations | BODY_RESPONSIBLE |
|---|---|
| 146 | *(empty string)* |
| 54 | Ministarstvo za poljoprivredu, šumarstvo i vodoprivredu Srednjebosanskog kantona |
| 16 | Ministarstvo za poljoprivredu, šumarstvo i vodoprivredu Ze-Do kantona |
| 9 | Ministarstvo za poljoprivredu, šumarstvo i vodoprivredu BPK |
| 5 | AVP Sava |

FHMZBiH appears nowhere in it. Recorded as a fact about the payload, not as a conclusion about
who owns the data.

### The operator's own rights line, recorded separately as `licence-2`

Every page of `www.voda.ba` carries this in its footer, and it is the only rights assertion on
that site. Recorded from `https://www.voda.ba/vodostaji` so it is evidenced:

```text
Copyright © 2001-2020 - All rights reserved - Agencija za vodno područje rijeke Save
```

### Where else was looked

- The three JSON endpoints we actually consume: no licence, terms, copyright or attribution
  field of any kind. Checked by fetching and scanning the payloads.
- `voda.ba/dokumenti` is a filtered document repository whose listing loads over XHR from
  `/inc/doclist.wbsp`. **All 7 document types and all 9 groups were swept through that
  endpoint.** No terms of use, no data licence, no citation guidance. The nearest items are a
  form for requesting access to information (*Obrazac za podnošenje zahtjeva za pristup
  informacijama*) and a decision on processing personal data via video surveillance — neither
  is about reuse of hydrological data.
- `voda.ba/zakonski-okvir` — a lead not in the candidate table. Links to the laws, rulebooks,
  decisions and EU legislation governing the Agency. Governing law, not data terms.
- `voda.ba/`, `voda.ba/vodostaji` — footer copyright only.
- `fhmzbih.gov.ba` (`/latinica/index.php`, `/latinica/HIDRO/vodostaji.php`) — no terms, no
  copyright statement about data. Its only `copyright` strings are OpenStreetMap and
  OpenTopoMap attributions inside Leaflet map JavaScript.
- `vodostaji.voda.ba/data/html/` — directory listing forbidden (403). Probed for
  `disclaimer`, `uslovi`, `legal`, `about`, `informacije`, `info`, `impressum_en`: all 404.
  Only `impressum.html` and `kontakt.html` exist.

The Impressum carries no date and no version. The site footer reads `© 2001-2020` and
`December 2019`.

### The instructed next step: enquiry sent 2026-08-20

This folder's own note says: *"If nothing turns up, a direct enquiry to the agency is the right
next step — record the reply."* Nothing turned up, so an enquiry was sent.

| | |
|---|---|
| Sent | **2026-08-20** |
| To | `info@voda.ba` — the address on the data service's own Kontakt page, `https://vodostaji.voda.ba/data/html/kontakt.html` |
| By | Thiago Nascimento, Eawag |
| Language | Bosnian |

The two questions asked, verbatim:

```text
1. Postoje li objavljeni uslovi korištenja ili licenca za ponovno korištenje
   podataka sa vodostaji.voda.ba?

2. Na koji način želite da Vas navedemo kao izvor? Zanima nas tačna
   formulacija koju preferirate.
```

In English: whether published terms of use or a licence exist for reuse of the data, and what
exact wording the Agency wants to be credited with. The enquiry asked only what the Agency
publishes. It did not ask permission, and no permission is implied by it having been sent.

**No reply as of the date of this recording.** If one arrives it belongs here quoted verbatim
with its date. If none arrives, "asked on 2026-08-20, no reply" is the result, and it is a real
one — it distinguishes "we asked and heard nothing" from "nobody asked".

Postal and telephone contact, from the same page: Agencija za vodno područje rijeke Save,
ul. Hamdije Čemerlića 39a, 71000 Sarajevo, tel. +387 (0)33 726 400.

