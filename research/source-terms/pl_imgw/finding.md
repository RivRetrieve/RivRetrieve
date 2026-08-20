# Source terms finding — pl_imgw

Agency: Institute of Meteorology and Water Management IMGW
Country: Poland
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://danepubliczne.imgw.pl/regulations | Regulamin Udostępniania Danych | pl | The open-data portal's own regulations page. **Confirmed reachable (HTTP 200). Start here** |
| https://danepubliczne.imgw.pl/datastore | Dane publiczne | pl | Reachable; search surfaces it under the same regulations title — may be the same document by another route |
| https://dane.imgw.pl/regulations | — | pl | Alias host, **not fetched**. Check whether it mirrors the above or is a distinct portal |

**No English version found. No separate citation page found** — the citation wording may sit
inside the regulations document itself, so read it for both slots before concluding one is
absent.

**Also read `TRAIL.md` in this folder.** That is the more important of your two jobs here.

## licence

- Page URL: https://danepubliczne.imgw.pl/regulations
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T08:47:07+00:00
- Language: pl
- Agency publishes nothing: no

The exact sentence stating the terms, in its original language, copied not retyped:

```text
Korzystający może używać nieodpłatnie udostępnionych danych do celów prywatnych, a w przypadku danych o wysokiej wartości w każdym celu. Jakikolwiek użycie danych w celach określonych w § 3 ust. 2 regulaminu wymaga podpisania umowy, która określi wysokość kosztów utrzymywania, odbudowy, rozbudowy i przebudowy sieci, systemów i biur lub koszty wykonania badań, pomiarów i ocen, jakie ma ponieść odbiorca.
```

## citation

- Page URL: https://danepubliczne.imgw.pl/regulations
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T08:47:07+00:00
- Language: pl
- Agency publishes nothing: no

The exact wording the agency asks to be credited with:

```text
Udostępnienie i korzystanie z danych następuje pod warunkiem wskazania źródła pochodzenia danych, poprzez umieszczenie przez korzystającego na wszelkiego rodzaju pracach lub produktach, opracowanych z użyciem danych IMGW-PIB informacji: „Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy”.
```

## Notes

**Both slots quote the same document.** IMGW publishes one *Regulamin Udostępniania Danych*
that carries the terms (§ 5 ust. 1) and the attribution wording (§ 5 ust. 3). There is no
separate citation page, so both slots name the single recording `licence-1` rather than
implying two sources. The quoted attribution sentence contains, in quotation marks, the exact
credit line IMGW asks to be placed on any work or product made with its data.

Verdicts on the three candidate leads, all checked on 2026-08-20:

- `danepubliczne.imgw.pl/regulations` — correct, and the whole document is in the served HTML.
  Plain HTML, no login, no JavaScript, no API key. `record.py` handled it in one call.
- `danepubliczne.imgw.pl/datastore` — a **different page** (33,114 bytes vs 24,298) that embeds
  the same regulations text inline beneath the data listing. Same wording, not a second
  document. Not recorded separately.
- `dane.imgw.pl/regulations` — **byte-identical** to the recorded page (both sha256
  `998edce594f80302…`, both 24,298 bytes). An alias host serving the same document, not a
  distinct portal.

**No English version exists.** `danepubliczne.imgw.pl/en/regulations` and `?lang=en` both return
the byte-identical Polish document (same sha256 as the recording). The site's PL/EN toggle
translates the portal chrome only, not the regulations. This confirms the folder's earlier
"no English version found" by fetching rather than by searching.

The document carries no version number and no publication date; § 12 states only
*"Regulamin obowiązuje od chwili jego publikacji."*

Sections of the same document not quoted above, by their own headings, all present in the
recording: § 3 *Odpłatne udostępnianie informacji w tym dla potrzeb działalności gospodarczej*,
§ 4 *Udostępnianie informacji podmiotom uprawnionym*, § 6 *Odpowiedzialności IMGW-PIB i jej
ograniczenia*, § 10 *Opłaty*. § 5 ust. 4 adds a second required statement where data have been
processed. Anyone deciding what these terms permit should read the recorded page whole rather
than the two quoted provisions alone.

**Scope note, established by the second job in this folder (`TRAIL.md`):** the terms quoted
above are IMGW's, and they govern the route RivRetrieve takes for Polish *observations*. The
1,301 Polish station *coordinates* in the packaged catalogue did not come through this portal
— they were received from the Global Runoff Data Centre by e-mail on 7 November 2025. Whatever
GRDC asks for that metadata is a separate question and is not answered by this page.
