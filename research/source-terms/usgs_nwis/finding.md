# Source terms finding — usgs_nwis

Agency: U.S. Geological Survey NWIS
Country: United States
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

Two genuinely different documents. **Do not put the same recording in both slots.**

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits | Copyrights and Credits | en | The agency-wide copyright and credits policy. **Confirmed reachable** — this is the page used in `_example/` |
| https://waterdata.usgs.gov/citation/ | How should I cite USGS Water Data for the Nation data? | en | **Confirmed reachable.** The water-data-specific citation convention — the one that matters for NWIS, not the general FAQ |
| https://www.usgs.gov/data-management/data-citation | Data Citation | en | USGS data-management guidance; a possible third layer. Not fetched |
| https://www.usgs.gov/faqs/how-should-i-cite-usgs-website | How should I cite a USGS website or publication? | en | General FAQ, broader than water data. **URL unconfirmed** — a direct fetch returned 403 |

The DOI `10.5066/F7P55KJN` recurs as the Water Data for the Nation identifier. **Confirm it
from the citation page itself**, not from this table.

Access note: `www.usgs.gov` returns 403 to plain `curl` but serves normally to a browser.

## licence

- Page URL: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T08:46:24+00:00
- Language: en
- Agency publishes nothing: no

```text
USGS-authored or produced data and information are considered to be in the U.S. Public Domain.
```

## citation

- Page URL: https://waterdata.usgs.gov/citation/
- Recording: citation-1
- Retrieved (UTC): 2026-08-20T15:56:47+00:00
- Language: en
- Agency publishes nothing: no

```text
Example of how to cite USGS Water Data for the Nation in general: U.S. Geological Survey, [2024], USGS Water Data for the Nation: U.S. Geological Survey National Water Information System database, accessed [April 8, 2024], at https://doi.org/10.5066/F7P55KJN.
```

## Notes

Two genuinely different documents, as the candidate table required, and **the two slots name
different recordings**: the agency-wide copyright policy for the licence, and the water-data
citation page for the citation.

### The DOI, confirmed from the citation page itself

The candidate table asked that `10.5066/F7P55KJN` be confirmed from the page rather than taken
from the table. It appears **three times** in the recorded citation page, once in each of the
three worked examples. Confirmed.

### The API example is the one that matches our route

The citation page gives three examples. The slot holds the general one. The third is for API
services, which is how RivRetrieve reads USGS:

```text
Example of how to cite a specific API service with USGS Water Data for the Nation: U.S. Geological Survey, [2024], U.S. Geological Survey National Water Information System database, accessed [April 8, 2024], at https://doi.org/10.5066/F7P55KJN. [Data download directly accessible at https://api.waterdata.usgs.gov/ogcapi/v0/openapi.]
```

Note the URL inside it: the example points at `https://api.waterdata.usgs.gov/ogcapi/v0/openapi`.
RivRetrieve reads `https://waterservices.usgs.gov/nwis/site/`, the older NWIS web service, not
the OGC API. Both are USGS services and both are covered by the same DOI in the example text.
Recorded as an observation about the wording; whether the example is meant to cover the service
we use is not decided here.

The page also instructs that the bracketed publication year and access date be replaced by the
reader, and that *"USGS Water Data for the Nation websites are updated/published daily, so you
can use the current date as the publication date."* The bracketed placeholders are left exactly
as the agency printed them in the quote.

### A correction to an earlier note in this survey

An earlier pass recorded that `www.usgs.gov` renders its body via JavaScript and that
`record.py` captures only navigation chrome. **That was wrong.** The text is present in the
bytes. The mistake was a case-sensitive search for `public domain` when the page prints
*U.S.\xa0Public Domain* — capitalised, and with a non-breaking space after `U.S.`. The
checker matches it because `normalise()` casefolds and NFKC-folds `\xa0`; a plain `grep` does
not. `record.py` handles this provider without any browser.

Worth knowing for the rest of the survey: **a literal `grep` over recorded bytes is not a valid
test of whether a quote is present.** Only `check.py`'s own normalisation is.

### On the worked example in `_example/`

`_example/pages/licence-1.html` is byte-identical to `licence-1` here (same sha256, same 81,841
bytes), captured a day earlier. Its quote is written as *"in the U.S. public domain"* while the
page prints *"in the U.S. Public Domain"*. It passes because the checker casefolds. The quote in
the licence slot above uses the page's own capitalisation.

### What we actually fetch

`usgs_nwis` reads `https://waterservices.usgs.gov/nwis/site/`. That host is not
`www.usgs.gov` and not `waterdata.usgs.gov`; all three are USGS. The licence statement is
agency-wide and not scoped to a host, so no scope question arises of the kind seen for
`cz_chmi`.

### Also recorded

`licence-2` is the USGS *Data Citation* data-management guidance, listed in the candidate table
as a possible third layer. Kept as evidence; nothing is quoted from it, since the water-data
citation page is more specific to this data.

`https://www.usgs.gov/faqs/how-should-i-cite-usgs-website` was **not** recorded. The candidate
table marked its URL unconfirmed and noted a 403; the water-data page above answers the same
question for the data we actually use.

### Access notes

- All pages recorded with `record.py`. `www.usgs.gov` served it directly — the candidate
  table's warning that it returns 403 to plain `curl` did not reproduce.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
