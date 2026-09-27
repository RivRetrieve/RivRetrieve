# Fresh USGS source research

Acquired 2026-09-22 UTC. This is source-document research, not execution of the
provider-page examples or a verification of RivRetrieve's returned data.

## Acquisition and integrity

`manifest.json`, `manifest-followup.json`, and `manifest-access.json` record each
requested and final URL, UTC acquisition time, HTTP status, response headers,
byte count, SHA-256 hash, and response filename. `*.response.gz` files store the
unmodified HTTP entity bytes returned by the source in deterministic gzip
containers (`mtime=0`). Manifest byte counts and SHA-256 hashes describe the
decompressed response bytes, not the gzip container. Transfer framing is not
retained. Requests used `Accept-Encoding: identity`, without credentials.
Some responses were served from publisher CDNs; cache headers remain in manifests.

Commands, from the candidate worktree root:

```text
uv run python docs/verification/usgs-provider/source-research/acquire.py
uv run python docs/verification/usgs-provider/source-research/acquire.py -followup
uv run python docs/verification/usgs-provider/source-research/acquire.py -access
```

The guessed `/docs/api-keys/` URL returned HTTP 404. Its exact error response is
retained. Following links from the successful documentation page located
`/signup/` and `/docs/ogcapi/keys/`, both HTTP 200. This was ordinary link discovery,
not an access-restriction bypass. All other requests returned HTTP 200.

## Claims, evidence, and scope

| Claim usable in reader prose | Exact source evidence | Scope and limits |
| --- | --- | --- |
| USGS collects water data across the United States with automated sensors and manual measurements, and publishes through Water Data for the Nation. | `water-data.response.gz`: “collects water data at monitoring locations across the United States using automated sensors and manual data collection.” | Describes the source, not the geographical or quantity scope supported by RivRetrieve. |
| The national streamgaging network is primarily operated and maintained by USGS, with funding shared with federal, state, local and Tribal partners. | `national-streamgaging.response.gz`, “Unique Partnership”: “primarily operated and maintained by the USGS”; “most are funded in partnership with one or more of about 1,500 Federal, State, local, and Tribal agencies or organizations.” | Prefer the qualitative description. The page's network totals are explicitly dated October 2024 and are not RivRetrieve catalogue counts. Avoid claiming every gauge is jointly operated. |
| Station `07374000` is Mississippi River at Baton Rouge, Louisiana. | `station-07374000.response.gz`: “Mississippi River at Baton Rouge, LA - USGS-07374000”; agency USGS; site type Stream; state Louisiana. | Station page also lists US Army Corps of Engineers - New Orleans District among cooperators. Do not turn its category-wide date ranges into discharge-series coverage. Do not infer observation zones from station CST/DST metadata. |
| Personal credentials are optional for modest public API requests; a personal API key allows more requests before rate limiting. | `api-signup.response.gz`: different limits “with and without keys”; `ogcapi-keys.response.gz`: a key permits “more requests per hour” before HTTP 429. `v1-daily-collection.response.gz` was obtained without a key. | This research verified source guidance and an unauthenticated v1 collection request, not key transport inside RivRetrieve. Parent must check `USGS_API_KEY` configuration in current code. |
| Refer users to USGS access guidance rather than promising a fixed numerical limit. | `ogcapi-keys.response.gz` says endpoint responses provide `X-RateLimit-Limit` and `X-RateLimit-Remaining`; shows 1000/998 as an example. | The example is not a guaranteed quota. `api-signup.response.gz` says limits differ by API. No quota exhaustion or load test was performed. |
| Daily means, minima and maxima are publisher-computed daily statistics. | `v1-daily-collection.response.gz`, `description`: daily data today are generally a statistical summary of continuous data; “Daily data are automatically calculated from the continuous data of the same parameter code”. | Broad collection description, not a guarantee of complete intraday data or a known day definition. |
| USGS provisional data are subject to revision and have not received final approval. | `provisional.response.gz`: “preliminary or provisional and is subject to revision”; “has not received final approval”; subsequent review “may result in substantial revisions”. | Prefer “Provisional values can change after review” over claiming every recent value is provisional. This statement does not establish how RivRetrieve exposes approval or qualifier fields. |
| USGS-authored or produced data are in the U.S. Public Domain; credit USGS when using them. | `copyright.response.gz`: “USGS-authored or produced data and information are considered to be in the U.S. Public Domain”; “we ask that proper credit be given.” | The policy expressly excludes some third-party content. Do not assert all material on USGS websites is public domain. |
| Cite USGS Water Data for the Nation using DOI `10.5066/F7P55KJN` and the actual access date. | `citation.response.gz`: general citation example and instruction to replace bracketed publication year/access date; websites updated/published daily. | The source still calls the database National Water Information System. This wording is appropriate inside the citation, without claiming observation retrieval uses legacy services. |

## Suggested concise prose

The U.S. Geological Survey (USGS) publishes river measurements through Water Data
for the Nation. USGS primarily operates and maintains the national streamgaging
network, with funding shared with federal, state, local and Tribal partners.

The example uses station `07374000`, Mississippi River at Baton Rouge, Louisiana.

Small public requests do not require a personal API key. A key allows more
requests before USGS applies rate limits. Link to the
[USGS API-key guidance](https://api.waterdata.usgs.gov/docs/ogcapi/keys/) and add
RivRetrieve's configuration name only after checking current code.

Provisional values can change after USGS reviews field inspections and
measurements. Retrieval success does not establish source approval.

USGS-authored data are in the U.S. Public Domain. Credit USGS and cite Water Data
for the Nation with the date the data were accessed. A citation for data accessed
on this research date is:

> U.S. Geological Survey, 2026, USGS Water Data for the Nation: U.S. Geological
> Survey National Water Information System database, accessed September 22, 2026,
> at https://doi.org/10.5066/F7P55KJN.

Use the actual observation acquisition date in the final page if different.

## Conflicting or stale publisher documentation

Fresh access does not make every source statement current. The source OGC
getting-started and API-key pages still show v0 URLs. The versioning page even
states that only v0 is available. In contrast, the fresh v1 collection response
is HTTP 200 and carries `Api-Version: 1.3.0`. Preserve this discrepancy rather
than reproducing the stale version claims. The citation page also has a v0 API
example; use its general citation form instead. No source decommission schedule
is needed on the provider introduction.

The parent must separately verify current implementation, catalogue counts,
conversions, time representation, approval handling, series identities and all
final examples. These source documents do not establish those library behaviors.

## Station-specific published series: 02196000

Fresh metadata was acquired at 2026-09-22T19:29:48.847052+00:00, HTTP 200.
`manifest-series.json` records URL, response headers and hash;
`station-02196000-daily-discharge-metadata.response.gz` contains exact source bytes.
Reproduce with `uv run python docs/verification/usgs-provider/source-research/acquire.py -series`.

The v1 `time-series-metadata/items` request filters monitoring location
`USGS-02196000`, parameter `00060`, and statistic `00003`, with limit 100.
It returns exactly two features (`numberReturned: 2`) and no next-page link.
Both records explicitly give `computation_period_identifier: Daily`,
`computation_identifier: Mean`, `parameter_name: Discharge`, and
`unit_of_measure: ft^3/s`.

| Published ID (`properties.id`, also feature `id`) | `web_description` | `begin` | `end` |
| --- | --- | --- | --- |
| `0df18b246e8f48ec8e6547a92070e94a` | null | `1929-11-01T05:00:00+00:00` | `2026-09-20T04:00:00+00:00` |
| `4d186669708e4dc18f84d271efb953a1` | null | `1929-11-01T05:00:00+00:00` | `2005-09-29T04:00:00+00:00` |

Reader table descriptions can say “Not supplied” for each. The available
series descriptions do not explain the relationship between these two series.
These are station-specific IDs, not provider-wide categories. Metadata bounds
are dated source statements, not evidence of uninterrupted coverage, daily
physical boundaries, overlapping returned observations or a preferred series.
This request does not test values and does not establish numerical agreement or
differences. No interpretation of parent linkage or publisher preference was
made. Mapping these IDs to RivRetrieve `variant` remains a separate library check.
