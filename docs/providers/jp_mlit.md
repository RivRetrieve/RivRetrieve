# Japan: MLIT

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `jp_mlit` |
| Country | Japan |
| Published by | Ministry of Land, Infrastructure, Transport and Tourism (MLIT) |
| Read from | 水文水質データベース, the Water Information System (`www1.river.go.jp`) |
| Quantities | Discharge and stage, hourly and daily |
| Stations in the catalogue | 1,023. Availability depends on quantity and period |
| Credentials | No personal credentials required |
| Terms | Numerical data may be used freely; automated access has separate restrictions (see below) |
| Agency documentation | [水文水質データベース](https://www1.river.go.jp/), [利用上の注意 (notes on use)](https://www1.river.go.jp/caution.html) |

Retrieve two days of published daily discharge at station `305071285512040`.
Read [Automated access and caching](#automated-access-and-caching) before running requests.

```python
import rivretrieve as rr

selection = rr.find(
    provider="jp_mlit",
    station="305071285512040",
    quantity="discharge",
    frequency="daily",
)

result = rr.fetch(selection, start="2020-01-10", end="2020-01-11", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit")
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2020-01-10T00:00:00.000000,unknown,34.39,m3/s
2020-01-11T00:00:00.000000,unknown,32.14,m3/s
2
[('info', 'source_missing')]
```

The two rows give discharge in m³/s for January 10 and 11. Both days have a value.
The `source_missing` issue refers to other dates in the annual file that MLIT
supplies, not to these two days. RivRetrieve returns only the requested dates.

The time zone is `unknown`, so these timestamps should not be read as UTC or Japan
Standard Time. See [Time](#time) for how the source labels are represented, and
[Usage](../usage.md) for general selection and result inspection.

## Who measures, and who publishes

MLIT publishes observations through the Water Information System,
水文水質データベース. Its homepage describes stations under the jurisdiction of
its Water and Disaster Management Bureau:

> このデータベースは水文水質にかかわる国土交通省水管理・国土保全局が所管する観測所における観測データを公開することを目的としています。

In English, unofficially: this database aims to publish observation data from
stations under the jurisdiction of MLIT's Water and Disaster Management Bureau.
This quotation is retained from the original provider documentation; the homepage
content could not be independently rechecked on 2026-09-21.

Station pages identify the responsible local office. For example, the retained
page for 茂志利 (Moshiri), station `301011281104010`, names MLIT's Asahikawa
Development and Construction Department as manager. Administration and publication
do not establish who physically made every measurement. This provider does not
claim to cover all Japanese hydrometry.

RivRetrieve reads the database's observation pages and their linked download files.

## What you can retrieve

| Quantity filter | Frequency filter | Source and returned unit |
|---|---|---|
| `stage` | `hourly` | m |
| `stage` | `daily` | m |
| `discharge` | `hourly` | m³/s |
| `discharge` | `daily` | m³/s |

The catalogue lists these four candidates at each station. A station being listed
does not guarantee data for every quantity or requested period. The source station
inventory does not establish that availability.

RivRetrieve returns source-published values. It does not calculate daily values
from hourly observations. The statistic, averaging period, hours covered by a daily
value and stage datum have not been established for these records.

## Time

Returned `time` values are source clock labels accompanied by
`time_zone="unknown"`. Do not interpret them as UTC or assign Japan Standard Time
from the station's location. The datetime column itself has no time zone.

Daily dates are represented at midnight. Hourly source labels run from 1 to 24;
24 is represented at midnight on the following date. These representations do not
establish an interval's start or end, an averaging period, or a hydrological-day
definition. With an unknown time zone, RivRetrieve cannot convert these labels to UTC.

## Data status

MLIT's [notes on use](https://www1.river.go.jp/caution.html), retained on
2026-08-21, distinguish provisional and definitive values:

> 暫定値（青字表記）とは、現在の観測データから過去の統計データまでシームレスにお知らせすることを目的として、無人観測所から送られてくるデータをそのままデータベースに登録公表しているものであり、観測機器の故障、通信異常などによる欠測や異常値を含んでいる可能性があります。

> なお、正式に検定されたデータは後日確定値（黒字表記）としてデータベースに登録されますのでこちらを利用して下さい。

In English, unofficially: provisional values (shown in blue) are registered and
published as received from unmanned stations. They may contain gaps or anomalies
from equipment failure or communication problems. Formally verified data are
registered later as definitive values (shown in black), and MLIT asks users to use
those values.

MLIT marks provisional values and reasons for missing observations in its download
files. RivRetrieve reads those markers using MLIT's stated meanings:

- A number marked `*` (provisional) is returned, with a `source_tentative` issue.
- A cell marked `$` (missing), `#` (station closed), or `-` (unregistered) produces
  no observation row. RivRetrieve reports `source_missing`,
  `source_closed_station`, or `source_unregistered`, respectively.

The hourly files define all four markers; the daily files define only `$` and `-`.
RivRetrieve does not attach these markers to individual observations or offer them
as selectable variants. It summarizes each marker type in `result.issues`, with a
count and the first and last affected source labels. Those summaries cannot reliably
identify every provisional observation for filtering.

RivRetrieve makes no quality judgement of its own. A number without a marker does
not establish that MLIT has formally verified it. Missing observations are absent
rows, not rows containing null values; a failed request is reported separately.
See [Usage](../usage.md#issues) for interpreting issues and empty results.

## Automated access and caching

MLIT's notes on use describe the website as intended for ordinary browser viewing:

> ツール等による、自動的なデータ収集等はサーバに負荷がかかり、情報提供できなくなる恐れがありますので原則としてご遠慮ください。

In English, unofficially: please refrain in principle from automatic data
collection using tools, because it loads the server and may prevent information
provision. This quotation comes from the 2026-08-21 recording.

On 2026-09-21, software requests to the homepage, notes on use and terms PDF
returned HTTP 403 with “This site prohibits data acquisition using tools, etc.”
The observation example above succeeded that day. Technical success does not
establish unrestricted permission for automated access.

RivRetrieve retrieves programmatically. Keep requests limited to the stations,
quantities and periods needed for the study. Local caching can reduce repeated
requests; it does not create an exemption from MLIT's access guidance. MLIT also
warns of slower responses during floods and directs real-time users to
リアルタイム川の防災情報.

Daily retrieval downloads annual files, and hourly retrieval downloads monthly
files, even for a short requested period. Issues can therefore refer to dates
outside that period. In the first example, `source_missing` summarizes 17 missing
dates in the annual file, from April 30 to July 1, 2020.

Live retrieval defaults to `cache="bypass"`, which neither reads nor writes the
observation cache. To reuse a download, select the specific series and use
`cache="reuse"`, as below. Run this example in the same Python session as the first.

```python
series_id = rr.series(selection)["series_id"].item()
chosen = rr.pick(selection, series_id=series_id)

cached_result = rr.fetch(
    chosen, start="2020-01-10", end="2020-01-11", cache="reuse"
)

repeated_result = rr.fetch(
    chosen, start="2020-01-10", end="2020-01-11", cache="reuse"
)

print(repeated_result.data.select("value", "unit").rows())
print([(issue.severity, issue.code) for issue in repeated_result.issues])
```

Output:

```text
[(34.39, 'm3/s'), (32.14, 'm3/s')]
[('info', 'source_missing')]
```

With an initially empty cache, the first `reuse` call retrieves and stores this
series and period. The repeated covered request reads locally and retains the
missing-data issue. The earlier `bypass` call did not populate the cache.
Selecting the specific series tells RivRetrieve exactly which record to reuse.
Repeating the broader `selection` alone can require another source request because
RivRetrieve has not established whether other matching series exist.

The saved acquisition history includes both the HTML page and its linked DAT
download, with their original request details and retrieval times. A local read
keeps this history even when receipts are disabled. When receipts are enabled,
direct retrieval can return both publisher responses; reuse returns a generated
excerpt of the saved observations, not copies of those responses.

If the complete request is not covered, `reuse` retrieves the full requested scope
again, rather than downloading only missing dates. Saved values can differ from
later source corrections. Use `cache="refresh"` to request a current answer.
Set `RIVRETRIEVE_CACHE_DIR` to choose a local cache location; see
[Usage](../usage.md#cache-and-bulk-downloads).

Older MLIT caches can lack the HTML request in their saved acquisition history.
RivRetrieve refuses these caches before making a request, including when
`cache="refresh"` is selected. Use `rr.clear_cache("jp_mlit")` to remove the
provider’s saved observations, then retrieve the required series again. This
creates new acquisition history and retrieval times; it cannot restore the
missing original request.

## Terms and citation

The retained notes on use state:

> 水文水質データベースをご利用いただく際、掲載しているデータの利用について、許可等は必要ありません。「公共データ利用規約（第1.0版）」に従い、データをご利用ください。

In English, unofficially: no permission is needed to use the published data; use
them according to the Public Data Terms of Use, version 1.0 (PDL1.0).
This reuse statement is separate from the automated-access guidance above.

The [terms PDF](https://www1.river.go.jp/WDBrules_20251210.pdf), retained on
2026-08-21, says numerical data, simple tables and graphs are outside copyright
protection, so these rules do not apply to them and they may be used freely.
For content subject to the rules, PDL1.0 permits commercial use and is compatible
with CC BY 4.0, with qualifications for third-party rights and statutory restrictions.

Cite the database and consultation date using MLIT's example:

> 出典：国土交通省 水文水質データベース（https://www1.river.go.jp/）（○年○月○日に参照）、PDL1.0（http://www1.river.go.jp/）

Replace ○年○月○日 with the date of consultation. The PDF requests that date because
accuracy checks can lead to updates. It asks for processing and the responsible
party to be stated separately from the source, and for processed content not to be
presented as the original government content. These terms could not be freshly
content-checked on 2026-09-21.

## Sources

| Source | Evidence date and limitation |
|---|---|
| [水文水質データベース](https://www1.river.go.jp/) | Homepage quote retained from original documentation; content recheck refused on 2026-09-21 |
| [利用上の注意 (notes on use)](https://www1.river.go.jp/caution.html) | Recording from 2026-08-21; content recheck refused on 2026-09-21 |
| [公共データ利用規約（第1.0版）](https://www1.river.go.jp/WDBrules_20251210.pdf) | Recording from 2026-08-21; content recheck refused on 2026-09-21 |
| [Moshiri station page](http://www1.river.go.jp/cgi-bin/SiteInfo.exe?ID=301011281104010) | Retained station-page evidence; retrieval date not established here |
| MLIT observation pages and download legends | Recordings from 2026-09-02; two-day example retrieved live on 2026-09-21 |

The station count describes the packaged catalogue. The successful example verifies
one station, quantity and period, not service-wide availability.
