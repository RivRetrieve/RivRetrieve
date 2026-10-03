# Bosnia and Herzegovina: AVP Sava

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ba_fhmzbih` |
| Country | Bosnia and Herzegovina |
| Published by | Agencija za vodno područje rijeke Save (AVP Sava), the Sava River Watershed Agency, Sarajevo |
| Read from | AVP Sava's hydrological monitoring site (`vodostaji.voda.ba`) |
| Quantities | Discharge, stage and water temperature |
| Stations in the catalogue | 60. Availability depends on quantity and period |
| Credentials | None |
| History available | Rolling yearly workbooks; records can be shorter and have gaps |
| Terms | Data are informational, not official. See [Terms and citation](#terms-and-citation) |
| Agency documentation | [Hydrological monitoring](https://vodostaji.voda.ba/), [Impressum](https://vodostaji.voda.ba/data/html/impressum.html) |

RivRetrieve reads the workbooks published by AVP Sava. Retrieve discharge for
three days at station `2310`, HS Ključ on the Sana:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ba_fhmzbih",
    station="2310",
    quantity="discharge",
)

result = rr.fetch(
    selection,
    start="2026-09-01",
    end="2026-09-03T23:59:59",
    cache="bypass",
)

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2026-09-01T01:00:00.000000,unknown,,m3/s
2026-09-01T02:00:00.000000,unknown,3.9330000000000003,m3/s
2026-09-01T03:00:00.000000,unknown,3.943,m3/s
69
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

The request returned 69 rows in m³/s, including six null values. The preview
shows the first three rows. The empty value at 01:00 is a published blank,
returned as `value=null`. There is no observation row for midnight on September 1.
These are different forms of missing data. The explicit end time includes
observations through the end of September 3; it does not request a daily mean.

The two informational issues mean that RivRetrieve has not established a licence
or citation for this provider. They do not report a failed observation request.
Successful retrieval does not establish measurement quality. Check
[issues](../usage.md#issues) before interpreting the result.

`cache="bypass"` requests the source rather than a local observation cache.
This output was checked live on 2026-09-28. The workbooks roll forward, so this
fixed period will eventually fall outside their available history. Published
values can also change. Choose a recent period when running the example later.
See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

Bosnia and Herzegovina's rivers drain towards the Black Sea through the Sava
and Danube, or towards the Adriatic Sea. AVP Sava's
[area of responsibility](https://www.voda.ba/agencija) is the Black Sea drainage
area within the Federation of Bosnia and Herzegovina, one of the country's two
entities. This is not nationwide coverage.

The agency organises hydrological monitoring and collects and distributes water
resource data. Its [water information system](https://www.voda.ba/informacioni-sistem-voda)
collects, processes and displays observations from automatic stations. These
institutional responsibilities do not establish the owner or measurement operator
of every station in RivRetrieve's catalogue.

The Federal Hydrometeorological Institute (FHMZBiH) is a separate institution.
Its [hydrology page](https://www.fhmzbih.gov.ba/latinica/HIDRO/index.php) directs
readers to AVP Sava and the Adriatic Sea Watershed Agency for observations
collected by their water information systems.

The provider identifier is `ba_fhmzbih`, but the publisher of the workbooks
RivRetrieve reads is AVP Sava. The identifier does not mean that RivRetrieve
provides a national inventory or all data held by Bosnia and Herzegovina's
hydrometeorological services. Broader geographical coverage and an AVP Sava
provider name with compatibility for `ba_fhmzbih` are on the roadmap
([#406](https://github.com/RivRetrieve/RivRetrieve/issues/406)).

## What you can retrieve

| Quantity filter | Source parameter | Source unit | Returned unit |
|---|---|---|---|
| `discharge` | Proticaj | m³/s | m³/s |
| `stage` | Vodostaj | cm | m |
| `temperature` | Temperatura vode | °C | °C |

RivRetrieve converts stage from centimetres to metres. Discharge and water
temperature need no unit conversion. Stage is water level; its vertical
reference or datum has not been established.

The catalogue contains 60 stations. Its recorded availability checks found
numerical discharge and stage values at all 60, and water temperature at 12.
Temperature availability remains unknown at the other 48, which are still
selectable. A station being listed does not guarantee that it has data for
every quantity or requested period.

The source does not establish whether these values are instantaneous readings
or averages. RivRetrieve leaves frequency, statistic and temporal support
unknown. Approximately hourly spacing does not establish an hourly mean.
Select by quantity without assuming a frequency or statistic.

## How far back, and how recent

RivRetrieve reads the source's yearly workbooks. These offer a rolling window,
not a permanent archive. On 2026-09-28, the discharge and stage workbooks at
HS Ključ held timestamps from September 29, 2025 to September 28, 2026, with
gaps. A yearly workbook need not contain a full year of readings or recent
values: the water-temperature workbook at HS Ilidža (`4110`) held only
September 29 to November 30, 2025.

A request can return only observations still present in the workbook. It cannot
recover older observations that have rolled out of the source file. Contact
the agency about longer records; this interface does not establish their
availability. Access to archival records is on the roadmap
([#407](https://github.com/RivRetrieve/RivRetrieve/issues/407)).

## Time and data status

The workbooks publish timestamps without an established time zone. RivRetrieve
returns these labels in `time`, paired with `time_zone="unknown"`. Do not infer
UTC or local civil time from the station's location. The period represented by
each value is also unknown.

The site's [Impressum](https://vodostaji.voda.ba/data/html/impressum.html) states:

> Svi podaci koji se prikazuju i koji se dobiju kao rezultat pretrage su informativnog karaktera i
> ne mogu služiti kao zvanični podaci.

In English, unofficially: all data displayed, and all data obtained as search
results, are for information only and cannot serve as official data.

The workbooks read here contain timestamps and values without observation-level
quality or approval flags. RivRetrieve makes no quality judgement of its own.
A published blank remains a row with `value=null`. An absent observation supplies
no row. A failed request remains an issue alongside any successful records.

## Terms and citation

The portal's [Impressum](https://vodostaji.voda.ba/data/html/impressum.html)
does not specify a reuse licence or a citation format. AVP Sava's
[main website](https://www.voda.ba/) carries an “All rights reserved” copyright
notice. These pages do not establish data-specific reuse permission. Check
reuse conditions with the agency before redistributing the data.

For traceability, name AVP Sava and retain the station, quantity, requested period
and access date. This is practical guidance, not a publisher citation template.

## Sources

Publisher pages checked on 2026-09-28:

- [FHMZBiH hydrological characteristics](https://www.fhmzbih.gov.ba/latinica/HIDRO/Hkarakteristike.php): Black Sea and Adriatic drainage.
- [AVP Sava responsibilities](https://www.voda.ba/agencija): jurisdiction within the Federation and monitoring duties.
- [AVP Sava water information system](https://www.voda.ba/informacioni-sistem-voda): automatic monitoring and publication.
- [FHMZBiH hydrology](https://www.fhmzbih.gov.ba/latinica/HIDRO/index.php): links to the water agencies' information systems.
- [Hydrological monitoring portal](https://vodostaji.voda.ba/) and [Impressum](https://vodostaji.voda.ba/data/html/impressum.html): publisher and informational data status.
- [AVP Sava main website](https://www.voda.ba/): copyright notice.

The station counts describe the packaged catalogue. The example was retrieved
live on 2026-09-28. The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains commands, source checks, exact output and the limits of these checks.
