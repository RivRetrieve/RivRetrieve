# Canada: Environment and Climate Change Canada

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ca_eccc` |
| Country | Canada |
| Published by | Water Survey of Canada, Environment and Climate Change Canada |
| Quantities | Daily mean discharge and stage |
| Stations in the catalogue | 8,057. Availability depends on quantity and period |
| Credentials | None |
| Access | Explicit national HYDAT download, then local retrieval |
| Terms | The official HYDAT dataset record lists the Open Government Licence – Canada; see [Terms and citation](#terms-and-citation) |
| Agency documentation | [Water Office](https://wateroffice.ec.gc.ca/), [National water data archive: HYDAT](https://www.canada.ca/en/environment-climate-change/services/water-overview/quantity/monitoring/survey/data-products-services/national-archive-hydat.html) |

First prepare the national archive. This transfers and compiles the whole dataset,
not just the station used below. Allow time and disk space for that operation;
see [Downloading the archive](#downloading-the-archive).

```python
import rivretrieve as rr

rr.download("ca_eccc")
```

Then retrieve one week of published daily mean discharge at station `05OG008`:

```python
selection = rr.find(
    provider="ca_eccc",
    station="05OG008",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(
    selection, start="1991-03-01", end="1991-03-07", cache="bypass"
)

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
1991-03-01T00:00:00.000000,unknown,0.090,m3/s
1991-03-02T00:00:00.000000,unknown,0.090,m3/s
1991-03-03T00:00:00.000000,unknown,0.090,m3/s
7
()
```

The request returned seven daily means in m³/s and no retrieval issues (the empty
tuple `()`). The preview shows three values rounded to three decimal places.
Both endpoint dates are included. RivRetrieve reads the published means; it does
not calculate them from more frequent observations. An empty issue tuple does
not establish the quality of the values.

For this bulk provider, `cache="bypass"` still reads the compiled local archive.
This example was checked using the July 17, 2026 HYDAT release. Historical
values may change in later releases. Run the snippets in order in the same Python session. See
[Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

The Water Survey of Canada (WSC), within Environment and Climate Change Canada
(ECCC), collects, interprets and publishes standardized water-quantity data.
The national hydrometric program operates through federal, provincial and
territorial partnerships and agreements with other organisations. WSC operates
stations for most provinces and territories; Quebec operates its own network.

WSC compiles the historical records in HYDAT and publishes near-real-time data
through the Water Office and other services. RivRetrieve reads the HYDAT SQLite
archive, not the near-real-time service. ECCC describes HYDAT updates as
quarterly. An archive edition date does not tell you the latest observation date
at each station or establish a fixed publication delay.

## Downloading the archive

`rr.download("ca_eccc")` explicitly downloads and compiles the national archive.
RivRetrieve never starts this transfer during `fetch`. Without a compiled store,
retrieval returns an empty result with a `bulk.store_missing` warning and an
instruction to run `download`.

The July 17, 2026 compressed SQLite archive was listed as approximately 266 MB
by the publisher. Compilation also needs space for the extracted database and
working files. The verified compiled store occupied about 413 MB; that is not
its peak working-space requirement. The fresh download and compilation took
about an hour on the verification machine. Size and duration vary by edition
and computer. RivRetrieve checks its configured free-space requirement before
starting; allow additional working space rather than treating the ZIP size as
the disk requirement.

Choose a cache location with `RIVRETRIEVE_CACHE_DIR` before preparing the archive;
see [cache configuration](../usage.md#cache-and-bulk-downloads). After preparation,
inspect the local copy without downloading it again:

```python
status = rr.cache_status("ca_eccc")

print(status.presence.value)
print(status.source_vintage)
```

Output for the verified copy:

```text
present
2026-07-17
```

The same compiled copy serves later requests for other stations and periods.
Both `cache="bypass"` and `cache="reuse"` read it locally. `cache="refresh"`
is refused: run `rr.download("ca_eccc")` explicitly to replace the store with
the latest available edition. Retrieval does not check for a newer archive.

## What you can retrieve

| Quantity filter | Published statistic | Source and returned unit |
|---|---|---|
| `discharge` | Daily mean | m³/s |
| `stage` | Daily mean | m |

Use `frequency="daily"` and `statistic="mean"` for either quantity.
Stage is water level, not water depth or automatically an elevation above sea
level. RivRetrieve has not established a vertical reference for these series.
Other HYDAT contents, including sediment and extremes, are outside this provider's
supported quantities and statistics.

A station being listed does not guarantee data for each quantity or requested
period. The packaged catalogue does not establish station record dates or
per-quantity availability. The example verifies only its station, quantity and
week, not continuous history or national coverage.

## Time and data status

Daily calendar dates appear at midnight with `time_zone="unknown"`.
Read `time` and `time_zone` together. RivRetrieve has not established the time
zone or the interval bounds for these historical daily series. The midnight
label does not make them UTC. ECCC's FAQ describes daily means using observations
between 00:00 and 24:00; this does not establish a zone for every historical
record returned here.

ECCC describes review and finalization before records enter its national
historical database. Values can still carry source symbols, including `B` for
ice conditions and `E` for estimates, and can be revised. RivRetrieve preserves
native symbol cells in its compiled store but does not add a per-row quality
column to `result.data` or interpret symbols as a quality ranking. Optional
[receipts](../usage.md#receipts-optional) retain selected stored source cells;
a store excerpt is not the original national ZIP archive.

A published null daily cell remains a row with `value=null`. An absent monthly
source record supplies no daily rows. A missing store or failed request is
reported separately; an empty result alone does not distinguish those cases.
Check [issues](../usage.md#issues) before interpreting gaps or empty results.

## Terms and citation

The official [Historical Hydrometric Data dataset record](https://open.canada.ca/data/en/dataset/1ee9e14d-0814-5201-a3be-705809d8ee0e)
links the HYDAT SQL download and lists the
[Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada).
It permits reuse, including commercial use, subject to its conditions, and requires
source attribution and, where possible, a licence link. Where no specific
attribution is supplied, its wording is:

> Contains information licensed under the Open Government Licence – Canada.

ECCC also publishes a separate [Data Services End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/),
which its hydrometric data-server documentation cites and RivRetrieve records
as a provenance source. Its attribution provisions include third-party
originators. These are distinct publisher licence statements. Check the linked terms
that apply to the source and intended use.

The [Water Office FAQ](https://wateroffice.ec.gc.ca/contactus/faq_e.html)
provides separate citations for its websites and for `HYDAT.mdb`.
That MDB-specific wording is not a prescribed SQLite citation. For the SQLite
archive, a practical reference should identify ECCC/WSC, HYDAT, the actual
SQLite edition, source URL and access date. This is suggested documentation of
the source, not an official citation template. The Water Office's conditions
for information on its website should not be assumed to define the archive's
reuse terms.

## Sources

Publisher pages checked on 2026-09-22:

- [WSC overview](https://www.canada.ca/en/environment-climate-change/services/water-overview/quantity/monitoring/survey.html), [Water Office FAQ](https://wateroffice.ec.gc.ca/contactus/faq_e.html): responsibilities, daily means and symbols, citation guidance.
- [HYDAT archive](https://www.canada.ca/en/environment-climate-change/services/water-overview/quantity/monitoring/survey/data-products-services/national-archive-hydat.html), [download directory](https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/): archive contents, publication and edition.
- [Historical Hydrometric Data record](https://open.canada.ca/data/en/dataset/1ee9e14d-0814-5201-a3be-705809d8ee0e), [Open Government Licence](https://open.canada.ca/en/open-government-licence-canada), [ECCC Data Services End-use Licence](https://eccc-msc.github.io/open-data/licence/readme_en/): terms and attribution.

The station count describes the packaged catalogue. Fresh national acquisition
and local example retrieval were checked on 2026-09-22–23. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme) retains the
commands, evidence and limits of these checks.
