# RivRetrieve

Find and download river data from national agencies around the world, through one consistent
Python interface.

## River data and where to find them

From floods to droughts: understanding and modelling rivers is a central environmental concern.
For that, we need data. Preferably open data. Many countries measure their rivers at thousands of
stations but compiling that information is often hard. Different data portals, different languages,
different formats. All of that adds up quickly for anyone interested in the data.

> The data exist, but accessing them is challenging.

RivRetrieve focuses on time series of streamflow (discharge), stage and water temperature (other
variables may come into play later, so stay tuned). It harmonises identifiers, units and returned
columns, and records where every value came from. It leaves source quality judgements and study
suitability to the reader. Think of RivRetrieve as a bridge between the original provider and the
user.

<!-- TODO: badges (PyPI version, supported Python, licence, DOI) once the package is released. -->

## Current coverage

RivRetrieve currently gives access to 67,000+ stations from 12 national agencies in
12 countries across the Americas, Asia and Europe.

![Map of RivRetrieve station locations](docs/assets/coverage-map.png)

*Station locations in the packaged catalogue.*

Most providers are open. Norway and Brazil ask for credentials, which you request from the agency
yourself. See the [usage guide](docs/usage.md#supplied-credentials) for how to supply them.

<details>
<summary>All 12 providers</summary>

| Country | Agency | Provider | Stations | Access |
|---|---|---|---:|---|
| Bosnia and Herzegovina | Agencija za vodno područje rijeke Save (AVP Sava) | `ba_fhmzbih` | 60 | open |
| Brazil | Agência Nacional de Águas e Saneamento Básico (ANA) | `br_ana` | 17,914 | credentials |
| Canada | Environment and Climate Change Canada (ECCC) | `ca_eccc` | 8,057 | open |
| Czechia | Czech Hydrometeorological Institute (CHMI) | `cz_chmi` | 831 | open |
| France | Hub'Eau / HydroPortail | `fr_hubeau` | 7,323 | open |
| Japan | Ministry of Land, Infrastructure, Transport and Tourism (MLIT) | `jp_mlit` | 1,023 | open |
| Lithuania | Lithuanian Hydrometeorological Service (LHMT) | `lt_lhmt` | 97 | open |
| Norway | Norwegian Water Resources and Energy Directorate (NVE) | `no_nve` | 3,804 | API key |
| Poland | Institute of Meteorology and Water Management (IMGW) | `pl_imgw` | 1,301 | open |
| Switzerland | Federal Office for the Environment (FOEN) | `ch_foen` | 246 | open |
| Thailand | Hydro-Informatics Institute (HII), ThaiWater | `th_thaiwater` | 825 | open |
| United States | U.S. Geological Survey (USGS) | `usgs_nwis` | 26,200 | open |

</details>

South Africa's Department of Water and Sanitation (`za_dws`) is in the catalogue with 2,905
stations, but its observations cannot be retrieved yet.

Our hope is that this map keeps filling up. Know a data source we're missing? Let us know:
potential-provider suggestions can include source links and relevant access information
in a [GitHub issue](https://github.com/RivRetrieve/RivRetrieve/issues).

## Install

Requires Python 3.13 or later. We recommend [uv](https://docs.astral.sh/uv/):

```bash
uv add rivretrieve
```

It also installs with pip: `pip install rivretrieve`.

For optional station maps, install the `map` extra: `uv add "rivretrieve[map]"`.

## Quick start

List the available providers:

```python
import rivretrieve as rr

rr.providers()
```

The table names each agency and says whether it needs credentials.

See which variables and time steps one provider offers:

```python
rr.products("usgs_nwis")
```

List the stations that offer one of them:

```python
selection = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
rr.as_frame(selection)
```

Everything so far reads a catalogue that ships with the package, so it works offline. Downloading
observations is the step that needs internet:

```python
selection = rr.pick(selection, station="07374000")
result = rr.fetch(selection, start="2023-01-01", end="2023-01-31")
print(result.data)
```

The result is a Polars frame with `time`, `time_zone`, `station_id`, `product_id` and `value`.
Discharge values use m³/s. Read timestamps together with their zone column. Also look at
`result.issues`, even when rows come back. A successful call does not establish continuous records
or scientific comparability.

Next: the [usage guide](docs/usage.md) covers selections, time windows, issues, credentials and
caching, and the [CAMELS-US example](docs/examples/camels-us.md) retrieves streamflow for several
gauges at once.

## What RivRetrieve does and does not do

- **No quality control or gap filling.** The values are the original ones, as published by the
  providers, with only units and format converted to a common standard.
- **No aggregation.** RivRetrieve does not aggregate data (e.g., from hourly to daily). Data are
  returned at the time step the provider publishes: daily data are available only where the
  provider already publishes daily values.
- **No hosting.** RivRetrieve does not host the data. Downloads come from the providers' own
  services.
- **Availability depends on the providers.** If a provider's service is down, changes or stops,
  the data are unavailable through RivRetrieve as well.

## Documentation

Start with the [documentation index](docs/README.md).

- [Usage](docs/usage.md): selections, results, windows, issues, credentials, cache and receipts.
- [Example: Recent streamflow for CAMELS-US gauges](docs/examples/camels-us.md).
- [Public API and software reference](docs/reference.md).
- [Architecture](docs/architecture.md): responsibilities, a traced request and contracts.

## How to cite

If you use RivRetrieve in your work, please cite the package. If you use data retrieved through it,
you must also cite the providers of that data: each one states its own terms and the citation it
asks for.

## Data rights

All data rights remain with the original providers. Users are responsible for reviewing and
following each provider's terms, which can be found on their respective homepages. The MIT licence
in the LICENSE file applies only to the code of this package, not to any data downloaded through
it.

## Background

RivRetrieve is under active development. Breaking changes should be expected between release
versions. See the [issues](https://github.com/RivRetrieve/RivRetrieve/issues) for what is being
worked on.

The package began as a Python translation of
[RivRetrieve for R](https://github.com/Ryan-Riggs/RivRetrieve) by Ryan Riggs, made by @kratzert with
the Gemini CLI and a few manual fixes for API changes. It has grown into a collaborative effort
since, with @simonmoulds, @thiagovmdon and @CooperBigFoot.

Questions, bug reports and collaboration are welcome through the
[issues](https://github.com/RivRetrieve/RivRetrieve/issues).

## Acknowledgements

Importantly, this project would not exist without the open APIs of so many data providers. We thank
them for their data and for supporting the philosophy of open data.

We also thank Henning Plessow at the Global Runoff Data Centre (GRDC) for the exchange around
[hydrodownloadR](https://github.com/bafg-bund/hydrodownloadR), which pursues the same goal as
RivRetrieve, but in R.
