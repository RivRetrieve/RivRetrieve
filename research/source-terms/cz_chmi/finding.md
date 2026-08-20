# Source terms finding — cz_chmi

Agency: Czech Hydrometeorological Institute CHMI
Country: Czechia
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti | Vyloučení odpovědnosti | cs | Footer-linked as *Vyloučení odpovědnosti a licencování*; contains a *Podmínky použití* section covering licensing and attribution. **Primary target** |
| https://www.chmi.cz/-/jak-mohu-pou%C5%BE%C3%ADvat-otev%C5%99en%C3%A1-data-%C4%8Dhm%C3%BA- | Jak mohu používat otevřená data ČHMÚ? | cs | FAQ item directly on using the open data |
| https://www.chmi.cz/o-chmu/caste-dotazy-faq/open-data | Open data (FAQ section) | cs | Parent FAQ section |
| https://www.chmi.cz/documents/d/chmi.cz/vseobecne_obchodni_podminky?download=true | Všeobecné obchodní podmínky | cs | **PDF.** Also footer-linked, but likely governs *paid* data orders — **record separately so the two are not conflated** |
| https://opendata.chmi.cz/ | Index of / | — | Bare directory listing (`air_quality/`, `hydrology/`, `meteorology/`). No licence file at root — **look inside `hydrology/` for a README** |
| https://open-data-chmi.hub.arcgis.com/ | Open data CHMU (ArcGIS Hub) | cs/en | Secondary portal; per-dataset licence fields may appear |

Context only, do not record as terms: Czech law 262/2024 Sb. (in force 2025-01-01)
established the national hydrometeorological database and may be the statutory basis.

## licence

- Page URL: https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T15:24:48+00:00
- Language: cs
- Agency publishes nothing: no

```text
Produkty Českého hydrometeorologického ústavu dostupné na těchto webových stránkách podléhají licenci Creative Commons 4.0 CC-BY.
```

## citation

- Page URL: https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T15:24:48+00:00
- Language: cs
- Agency publishes nothing: no

```text
Dílo smíte sdílet a upravovat za podmínky uvedení původu (zdroje ČHMÚ).
```

## Notes

Both slots come from the *Podmínky použití* section of the page footer-linked as *Vyloučení
odpovědnosti a licencování*. The section is three sentences: the first names the licence and is
in the licence slot, the second states the condition of attribution and is in the citation slot,
and the third points to the licence text. They are one continuous passage in the recording.

The wording ČHMÚ uses for attribution is *uvedení původu (zdroje ČHMÚ)*. It does not give a
formatted citation string of the kind Canada or Poland provide — this is the whole of what the
Institute asks. No reading of what it requires in practice is offered here.

### The same licence, stated again in the FAQ — `licence-2`

The FAQ item *Jak mohu používat otevřená data ČHMÚ?* answers, in full:

```text
Otevřená data ČHMÚ můžete využívat bezplatně při respektování licence Creative Commons BY 4.0.
```

This matters for scope. The *Podmínky použití* passage in the slots is scoped to products
*"dostupné na těchto webových stránkách"* — available on these web pages, i.e. `www.chmi.cz`.
RivRetrieve does not read `www.chmi.cz`; it reads `opendata.chmi.cz`. The FAQ answer is scoped
instead to *Otevřená data ČHMÚ*, CHMI open data as such, which is the phrase that covers the
host we actually use. Both are the Institute's own words and both name CC BY 4.0. Recorded as
an observation about scope; which one governs is not decided here.

### What we actually fetch

`cz_chmi` reads two files, both under the open-data host:

```
https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json
https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf
```

`opendata.chmi.cz` is a bare directory listing — `air_quality/`, `hydrology/`, `meteorology/` at
the root. **There is no licence file, README or terms document at either the root or inside
`hydrology/`**, whose entries are `characteristic/`, `groundwater/`, `groundwater_quality/`,
`historical/`, `now/`, `product/`, `read_me/`, `recent/`, `surface_water_quality/` and one PDF.
The listing is recorded as `licence-3` so the absence is evidenced rather than asserted.

The `read_me/` directory was opened and every entry checked. It holds seven PDFs describing
datasets and code lists. One is titled *Průvodce otevřenými daty hydrologie* and looked like the
best candidate; it is a one-page navigation diagram whose entire extractable text is its own
title and subtitle. **None of the seven states terms or attribution.**

So the data host carries no terms of its own, and the statement has to be taken from
`www.chmi.cz`.

### Third-party flag

The licence is *named* on ČHMÚ's own domain, but its legal text is not. The *"Více informací"*
link resolves to `https://creativecommons.org/licenses/by/4.0/deed.cs` — off-domain. The choice
of licence is the Institute's; the wording of the licence is not. Recorded because the brief
asks that third-party statements be identified as such.

### The other recording

`licence-4` is *Všeobecné obchodní podmínky*, the general commercial terms, **a PDF** reached
from the footer. It is kept because the candidate table asked for it to be recorded separately
so the two are not conflated. Nothing from it is quoted in a slot: the checker cannot verify a
quote inside a PDF, and this document is not the open-data statement.

### Access notes

- All four recorded with `record.py` in one pass; no login, no key, no JavaScript.
- `www.chmi.cz` needs `SSL_CERT_FILE` pointed at the `certifi` bundle, as for `ca_eccc` and
  `ch_foen`.
- The two `www.chmi.cz` URLs contain percent-encoded Czech diacritics and must be passed exactly
  as recorded, in quotes, or the shell mangles them.
- The `open-data-chmi.hub.arcgis.com` portal in the candidate table was not recorded: the two
  statements above are on ČHMÚ's own domain, which the brief prefers over a secondary portal.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
