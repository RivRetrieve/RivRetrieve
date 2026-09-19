# Japan — MLIT

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `jp_mlit` |
| Country | Japan |
| Published by | Ministry of Land, Infrastructure, Transport and Tourism (MLIT), Water and Disaster Management Bureau |
| Read from | 水文水質データベース, the Water Information System (`www1.river.go.jp`) |
| Variables | Discharge, stage |
| Stations in the catalogue | 1,023 |
| Credentials | None |
| Terms stated by MLIT | Public Data Terms of Use, version 1.0 (PDL 1.0), compatible with CC BY 4.0 |
| Agency documentation | [水文水質データベース](https://www1.river.go.jp/), [利用上の注意 (notes on use)](https://www1.river.go.jp/caution.html) |

```python
import rivretrieve as rr

selection = rr.find(provider="jp_mlit", product="discharge_daily")
selection = rr.pick(selection, station="305071285512040")
result = rr.fetch(selection, start="2020-01-01", end="2020-12-31")
```

## Who measures, and who publishes

MLIT's Water and Disaster Management Bureau publishes the observations from the stations it
administers through the Water Information System, 水文水質データベース. The database's front
page states its purpose:

> このデータベースは水文水質にかかわる国土交通省水管理・国土保全局が所管する観測所における観測データを公開することを目的としています。

In English, unofficially: this database aims to publish the observation data from stations under
the jurisdiction of MLIT's Water and Disaster Management Bureau.

RivRetrieve reads the database's station pages and the data files it offers for download.

## What you can retrieve

| Product | MLIT kind | Unit | Stations listed |
|---|---|---|---:|
| `stage_hourly` | 2 | m | 1,023 |
| `stage_daily` | 3 | m | 1,023 |
| `discharge_hourly` | 6 | m³/s | 1,023 |
| `discharge_daily` | 7 | m³/s | 1,023 |

MLIT distinguishes these as numbered kinds of record, which the catalogue's `native_id` shows. The
product names carry no statistic because the catalogue records the statistic as `unknown`.

Availability is `unknown` for every station and product. The catalogue gives the reason: MLIT's
station table does not state which kinds of record each station holds.

## Data status

MLIT's [notes on use](https://www1.river.go.jp/caution.html) distinguish provisional from
definitive values:

> 暫定値（青字表記）とは、現在の観測データから過去の統計データまでシームレスにお知らせすることを目的として、無人観測所から送られてくるデータをそのままデータベースに登録公表しているものであり、観測機器の故障、通信異常などによる欠測や異常値を含んでいる可能性があります。

> なお、正式に検定されたデータは後日確定値（黒字表記）としてデータベースに登録されますのでこちらを利用して下さい。

In English, unofficially: provisional values (shown in blue) are registered and published as
received from unmanned stations, so they may contain gaps or anomalies from equipment failure or
transmission problems; formally verified data are registered later as definitive values (shown in
black), and those should be used.

MLIT's data files mark each value with a flag, and RivRetrieve keeps that distinction visible:

| MLIT flag | Meaning | What RivRetrieve does |
|---|---|---|
| none | Definitive value | Returns the value |
| `*` | 暫定値, provisional | Returns the value, and records a `source_tentative` issue |
| `$` | 欠測, missing | Returns no row, and records a `source_missing` issue |
| `#` | 閉局, station closed | Returns no row, and records a `source_closed_station` issue |
| `-` | 未登録, unregistered | Returns no row, and records a `source_unregistered` issue |

So `result.issues` tells you which values are still provisional. Values are also corrected after
publication: MLIT's front page announces such corrections, for example to water levels at one
station for July to December 2025, announced on 3 September 2026.

## Time

Values come back with `time_zone` `unknown`. MLIT's data files do not state a time zone, so
RivRetrieve does not fill one in.

## Automated access

MLIT's notes on use ask users, in principle, to refrain from collecting data automatically:

> ツール等による、自動的なデータ収集等はサーバに負荷がかかり、情報提供できなくなる恐れがありますので原則としてご遠慮ください。

In English, unofficially: automatic data collection with tools and the like loads the server and
may stop it providing information, so please refrain from it in principle.

RivRetrieve retrieves programmatically. Keep requests to what your study needs. MLIT also notes
that the database responds slowly during floods, when it points real-time users to a separate
service, リアルタイム川の防災情報.

## Terms and citation

MLIT's [notes on use](https://www1.river.go.jp/caution.html) state that no permission is needed:

> 水文水質データベースをご利用いただく際、掲載しているデータの利用について、許可等は必要ありません。「公共データ利用規約（第1.0版）」に従い、データをご利用ください。

In English, unofficially: no permission is needed to use the data; use them according to the
Public Data Terms of Use (version 1.0).

Those [terms](https://www1.river.go.jp/WDBrules_20251210.pdf) state that numerical data are not
protected by copyright and can be used freely, that they are compatible with Creative Commons
Attribution 4.0, and that you should cite the source. They give this example:

> 出典：国土交通省 水文水質データベース（https://www1.river.go.jp/）（○年○月○日に参照）、PDL1.0（http://www1.river.go.jp/）

Replace ○年○月○日 with the date you consulted the data. If you edit or process the data, the terms
ask you to say so, and by whom, separately from the source.

## Sources

| Page | Retrieved |
|---|---|
| [水文水質データベース](https://www1.river.go.jp/) | 2026-09-19 |
| [利用上の注意 (notes on use)](https://www1.river.go.jp/caution.html) | 2026-09-19 |
| [公共データ利用規約（第1.0版）](https://www1.river.go.jp/WDBrules_20251210.pdf) | 2026-09-19 |

Station counts come from the packaged catalogue. The flag meanings are those printed in MLIT's
data files and enforced by the provider's parser.
