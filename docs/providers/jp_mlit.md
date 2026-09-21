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

The request returned two values in m³/s on 2026-09-21. Bare dates include the whole
first and last day. `cache="bypass"` requests the source without reading or writing
the observation cache. Source corrections can change later answers.

The informational issue describes 17 missing source slots, with first label
`2020年4月30日` and last label `2020年7月1日`. Daily retrieval reads an annual
source file, then keeps only rows in the requested period. Issues can describe
that wider response: neither of these two January values is missing. Hourly
retrieval similarly reads monthly source files. A short request can therefore
transfer more observations than it returns.

`unknown` means RivRetrieve has not established the time zone. The daily label
does not establish a daily mean, so the selection does not use `statistic="mean"`.
See [Usage](../usage.md) for general selection and result inspection.
Run the remaining example in the same Python session.

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

| Quantity filter | Frequency filter | MLIT KIND | Source and returned unit |
|---|---|---|---|
| `stage` | `hourly` | 2 | m |
| `stage` | `daily` | 3 | m |
| `discharge` | `hourly` | 6 | m³/s |
| `discharge` | `daily` | 7 | m³/s |

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

The hourly download legend defines all four flags below. The daily legend lists
only `$` and `-`.

| Source flag | Meaning | RivRetrieve result |
|---|---|---|
| `*` | 暫定値, provisional | Numeric value returned; `source_tentative` issue |
| `$` | 欠測, missing | No observation row; `source_missing` issue |
| `#` | 閉局, station closed | No observation row; `source_closed_station` issue |
| `-` | 未登録, unregistered | No observation row; `source_unregistered` issue |

An unflagged number does not establish that the observation has been formally
verified. RivRetrieve summarizes affected source cells by issue type, with counts
and first and last source labels. `result.issues` does not identify every affected
row, and the observation table has no per-row provisional flag.

The non-observation markers above produce absent rows, not null-valued rows.
A failed request is a separate outcome. Inspect issues and series outcomes alongside
the data, especially when a result is empty. See [Usage](../usage.md#issues).

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

Live retrieval defaults to `cache="bypass"`. To opt into reuse, first fix the
selection to the one identified series shown by `rr.series(selection)`. This avoids
asking the cache to establish whether further matching series exist in an
incomplete source inventory.

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
missing-data issue. The earlier `bypass` call did
not populate the cache. Repeating the broader `selection` alone does not guarantee
reuse because its source inventory is incomplete.

If the complete request is not covered, `reuse` retrieves the full requested scope
again, rather than downloading only missing dates. Saved values can differ from
later source corrections. Use `cache="refresh"` to request a current answer.
Set `RIVRETRIEVE_CACHE_DIR` to choose a local cache location; see
[Usage](../usage.md#cache-and-bulk-downloads).

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
