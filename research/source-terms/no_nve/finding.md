# Source terms finding — no_nve

Agency: NVE HydAPI
Country: Norway
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Page title | Lang | Why a candidate |
|---|---|---|---|
| https://hydapi.nve.no/UserDocumentation/ | NVE Hydrological API (HydAPI) — API documentation | en | The API's own docs, with explicit `License` and `Terms of use` headings and a line on referring to the service as data origin |
| https://api.nve.no/doc/hydrologiske-data/ | Hydrologiske data \| API.NVE.NO | no | NVE's umbrella API portal entry — plausibly the agency-level statement. **Not opened by the lead-finder; lower confidence.** |

HydAPI needs an API key for *data* (register at https://hydapi.nve.no/Users), but the
documentation page reads fine without one. Third-party flag: the named licence's text is at
https://data.norge.no/nlod/en — a Norwegian government domain, but not NVE's own.

## licence

- Page URL: https://hydapi.nve.no/UserDocumentation/
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T09:19:38+00:00
- Language: en
- Agency publishes nothing: no

```text
The data provided by the API is licensed under the Norwegian License for Open Government Data (NLOD) which is compatible with CC Navngivelse 3.0 Norge (CC BY 3.0).
```

## citation

- Page URL: https://hydapi.nve.no/UserDocumentation/
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T09:19:38+00:00
- Language: en
- Agency publishes nothing: no

```text
When using data from this service, if possible, please refer to this service as origin of data.
```

## Notes

Both slots come from the **License** section of HydAPI's own user documentation at
`hydapi.nve.no`, which is the host RivRetrieve reads. NVE writes this section in English on
that page, so no translation is involved.

### The citation ask is soft, and quoted as such

NVE says *"if possible, please refer to this service as origin of data"*. That is a request,
not a requirement, and it is quoted with its hedge intact. It names no formatted citation
string and no fixed wording — "this service" is as specific as NVE gets.

Contrast with `lt_lhmt`, where attribution is a condition of continued access. Recorded because
a reader skimming both findings could otherwise assume they say the same thing.

### The same statement in Norwegian, on the umbrella portal — `licence-2`

`api.nve.no/doc/hydrologiske-data/` carries the equivalent statement in Norwegian, scoped
slightly differently — to *"Data som ligger på api.nve.no"* rather than to this API — and it
adds where the licence text lives:

> Data som ligger på api.nve.no er lisensiert under Norsk lisens for offentlige data (NLOD) som
> er kompatibel med CC Navngivelse 3.0 Norge (CC BY 3.0). Lisensteksten finner du på
> data.norge.no/nlod/ og creativecommons.org/licenses/by/3.0/no/deed.no.

Its attribution sentence is *"Når du bruker data skal du så langt det lar seg gjøre lenke til
den aktuelle tjenesten"* — link to the service, rather than refer to it. Recorded as a
difference in wording between two NVE pages, not resolved here. The candidate table marked this
page "lower confidence"; it is a real NVE page and says materially the same thing.

### Warranty disclaimer, in the same section

```text
Data is provided by the API "as is". It can contain erroneous or missing data. NVE does not take any responsibility for data that can give wrong or misleading information.
```

### An API key is required, and NVE says why

```text
All requests to the API needs to be supported with an API-key in the request-header. We require this in order to provide all users a free, stable and reliable service.
```

RivRetrieve requires `NVE_API_KEY`, as `provider.json` records. The documentation page itself
reads without a key — only the data needs one — so this finding was made without registering.

### Rate limiting: what NVE publishes, and what the code does

NVE documents throttling explicitly, and unusually for this survey it exposes it in response
headers:

```text
Throttling: The API will only support a fixed number of requests from a client (API-key) per time unit, and will deny request when this limit is reached. Clients that violate this policy will be temporarily blocked by the API, and an error-message will show. Each response will contain information in the header (x-rate-limit-limit, x-rate-limit-remaining, x-rate-limit-reset).
```

The page adds that resolution metadata updates roughly every 10 minutes and station/series
metadata roughly every 4 hours, and recommends relating request intervals to those.

What RivRetrieve does, read from the code:

- `no_nve` contains no rate limiting of its own.
- The shared transport (`src/rivretrieve/_internal/transport.py`) applies a global
  `TRANSPORT_POLICY`: `minimum_interval_seconds = 1.0`, enforced by sleeping before an attempt
  that would otherwise start sooner, and `429` among the retryable status codes with backoff
  `(1.0, 2.0)` over three attempts.
- **Nothing reads `x-rate-limit-limit`, `x-rate-limit-remaining` or `x-rate-limit-reset`.**
  Searched across the whole of `src/rivretrieve/`. NVE publishes a live budget in every
  response and the client does not consult it; it reacts to `429` after the fact instead.

Recorded as a fact about the code against what the service documents. No conclusion is drawn
about whether any particular use would trip the limit.

### Third-party flag

The licence is **named** on NVE's own domain; its text is not. NLOD lives at `data.norge.no`,
a Norwegian government domain but not NVE's, and the CC compatibility statement points to
creativecommons.org. `licence-3` records the NLOD text at `data.norge.no/nlod/en/2.0` so the
named licence is in evidence, flagged as a third-party page. Same pattern as `cz_chmi`,
`fr_hubeau` and `lt_lhmt`.

### Access notes

- All three pages recorded with `record.py` in one pass, no key needed.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
