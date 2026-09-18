# Documentation

## Getting started

New here? Install RivRetrieve and run the [first retrieval](../README.md#install), then see what
comes back in [returned data and issues](usage.md#retrieve-and-inspect-results).

## Using RivRetrieve

- [Usage](usage.md): finding stations, selecting series, retrieving them, time windows, issues,
  credentials, cache and receipts.
- [CAMELS-US example](examples/camels-us.md): how to extend the original CAMELS time series to recent daily streamflow for three gauges.
- [API reference](reference.md): the public functions, their arguments and the columns they return.

## Providers

RivRetrieve currently reads from 13 national agencies. The [README](../README.md#current-coverage) lists them
with their station counts. The data belong to those agencies, and each one describes its own network
best, so these pages cover what you need in order to use a provider through RivRetrieve.

Whatever the provider, RivRetrieve gives you the same things:

- **Stations**: an identifier, a position, and the products the station offers.
- **Products**: a variable (discharge, stage or water temperature), a statistic (mean, maximum,
  minimum or an instantaneous reading) and a time step (daily, hourly, irregular, or unknown where
  the agency does not state one).
- **Units**: discharge in m³/s, stage in m, and water temperature in °C.
- **Times**: as the agency publishes them, each with its time zone, which is `unknown` when the
  agency does not state one.
- **Terms and citation**: these stay with the agency. Check them before using the data.

A page for each provider, describing its network, what it measures and how to cite it, is being
written.

## How it works

- [Architecture](architecture.md): responsibilities, a traced request, contracts and verification.
- [Catalogue evidence](catalogue-evidence.md): what RivRetrieve records about where catalogue facts
  came from, and how to inspect it.
- [Catalogue absence](catalogue-absence.md): why a missing fact is not the same as a source saying
  nothing.

## Project records

The pages above describe the software as it is today. The records below preserve the reasoning at
the time they were written: their API names, provider counts and execution details may since have
been superseded. Read them as history rather than as instructions.

- [Domain vocabulary](../CONTEXT.md).
- [Catalogue provenance](catalogue-provenance.md).
- [Evidenced inventory account](provider_ports/evidenced_coverage.md). Its recorded limitations
  still apply: it does not establish countrywide inventory completeness or continuous observation
  history.
- [Provider port notes](provider_ports/): what was established about each source when it was
  added.
- [Design analyses](design/) and [delivery records](milestones/).
- [Development conventions](development-conventions.md).

<details>
<summary>Port notes, one per provider</summary>

- [ba_fhmzbih](provider_ports/ba_fhmzbih.md)
- [br_ana](provider_ports/br_ana.md)
- [ca_eccc](provider_ports/ca_eccc.md)
- [ch_foen](provider_ports/ch_foen.md)
- [cz_chmi](provider_ports/cz_chmi.md)
- [fr_hubeau](provider_ports/fr_hubeau.md)
- [jp_mlit](provider_ports/jp_mlit.md)
- [lt_lhmt](provider_ports/lt_lhmt.md)
- [no_nve](provider_ports/no_nve.md)
- [pl_imgw](provider_ports/pl_imgw.md)
- [th_thaiwater](provider_ports/th_thaiwater.md)
- [usgs_nwis](provider_ports/usgs_nwis.md)
- [za_dws](provider_ports/za_dws.md)

</details>

## Checking the docs locally

No site build, credentials or bulk download is needed. From a source checkout, run:

```bash
uv run python scripts/generate_reference.py --check
uv run pytest -q tests/test_documentation.py
```

The tests replay committed source bytes through the public API. They do not test whether a
provider's service is available today.
