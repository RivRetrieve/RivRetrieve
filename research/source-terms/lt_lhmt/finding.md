# Source terms finding — lt_lhmt

Agency: Hydrometeorological Service LHMT
Country: Lithuania
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Page title | Lang | Why a candidate |
|---|---|---|---|
| https://api.meteo.lt/ | Meteo LT API | lt | The API's own docs, with a `Naudojimosi sąlygos` section and `Duomenų naudojimo sąlygos` / `Užklausų ribojimas` subsections; the attribution requirement lives here |
| https://www.meteo.lt/istaiga/atviri-duomenys/ | Atviri duomenys – Meteo LT | lt | LHMT's institutional open-data landing page; links onward but carries no terms text of its own |

**Not found:** no dedicated LHMT terms page beyond the api.meteo.lt section. Already
searched: meteo.lt "Teisės aktai", data.gov.lt, geoportal.lt, archyvas.meteo.lt.
Third-party flag: the licence *named* on api.meteo.lt links off-domain to creativecommons.org
for its legal text — the choice is on LHMT's domain, the wording is not. Record the LHMT page.

## licence

- Page URL: https://api.meteo.lt/
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T08:27:13+00:00
- Language: lt
- Agency publishes nothing: no

```text
Per Meteo LT API teikiami duomenys (toliau – duomenys) yra viešai prieinami ir nemokami visuomeniniam naudojimui, platinimui ir tolimesniam apdorojimui, laikantis šių duomenų naudojimo sąlygų: 1) duomenys, jeigu nenustatyta kitaip, teikiami pagal Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0) tarptautinę duomenų naudojimo licenciją, būtina susipažinti su licencijos sąlygomis;
```

## citation

- Page URL: https://api.meteo.lt/
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T08:27:13+00:00
- Language: lt
- Agency publishes nothing: no

```text
5) publikuojant, pakartotinai atkartojant ar kitaip naudojant duomenis, būtina nurodyti, kad duomenų šaltinis yra Tarnyba. Nenurodant duomenų šaltinio, gali būti nutraukta prieiga prie duomenų.
```

## Notes

Both slots come from the *Naudojimosi sąlygos → Duomenų naudojimo sąlygos* section of the API's
own documentation at `api.meteo.lt`, which is the host RivRetrieve reads. The section is a
numbered list of five conditions; the licence slot holds the preamble and condition 1, the
citation slot holds condition 5.

### The licence is ShareAlike

The named licence is **Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0)**, not plain
CC BY. It is the only ShareAlike licence found anywhere in this survey. Recorded plainly
because it differs from the CC BY named by `cz_chmi`, and the difference is the Service's, not
ours to interpret.

Condition 1 also opens with *"jeigu nenustatyta kitaip"* — "unless established otherwise" — so
the Service reserves the possibility of different terms for particular data. Nothing found says
different terms apply to the hydrological endpoints.

### Attribution is a condition of access, not only of courtesy

Condition 5 states that the source must be given as the Service, and adds that **without it
access to the data may be terminated**. Quoted in full in the citation slot rather than cut at
the attribution requirement, because the consequence is part of the same sentence and dropping
it would soften what the Service says.

The Service refers to itself throughout as *Tarnyba* — the Service. It does not print a
formatted citation string.

### Intellectual property in the API itself

The same section opens with a separate statement about the API rather than the data:

```text
Meteo LT API pavadinimas ir visos intelektinės nuosavybės teisės priklauso Tarnybai ir yra neperduodamos.
```

Recorded because it is adjacent to the data terms and a reader could otherwise mistake one for
the other.

### Stated rate limits, and what the provider does

The same page states hard limits:

```text
Užklausų kiekis iš vieno IP adreso ribojamas iki 180 užklausų per minutę. Prašome negeneruoti daugiau kaip 20.000 užklausų per vieną parą iš vieno IP adreso, nes viršijus nurodytą limitą Jūsų IP adresas gali būti užblokuotas be įspėjimo.
```

That is 180 requests per minute per IP, and a request not to exceed 20,000 per day per IP, with
IP blocking without warning above it.

**`lt_lhmt` implements no throttling.** There is no sleep, delay, backoff or rate limit anywhere
in the provider — checked across `config.py`, `origins.py`, `generate_catalogue.py` and
`bulk.py`, and no engine-level throttle was found either. The packaged catalogue holds **97
stations** and two products, and `provider.json` records the fetch strategy as *"monthly-chunk
requests per station-product pair"*, so a long multi-station request decomposes into a large
number of calls.

Recorded as a fact about the provider against a limit the Service publishes. No conclusion is
drawn here about whether any particular use would exceed it.

### The institutional page carries nothing further

`licence-2` is `meteo.lt/istaiga/atviri-duomenys/`, LHMT's open-data landing page. It was
recorded and read; it links onward and carries no terms text of its own, as the candidate table
expected.

### Third-party flag

The licence is **named** on LHMT's own domain, but its legal text is not — condition 1 requires
the reader to consult the licence conditions, which live at creativecommons.org. The choice is
the Service's; the wording is not. Same pattern as `cz_chmi` and `fr_hubeau`.

### Access notes

- Both pages recorded with `record.py` in one pass. Plain HTML, no login, no API key.
- The API documentation is Lithuanian only; no English version was found.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
