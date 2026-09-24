# Documentation

## Getting started

New here? Install RivRetrieve and run the [first retrieval](../README.md#install), then see what
comes back in [returned data and issues](usage.md#retrieve-and-inspect-results).

## Using RivRetrieve

- [Usage](usage.md): finding stations, selecting series, retrieving them, time windows, issues,
  credentials, cache and receipts.
- [CAMELS-US example](examples/camels-us.md): how to extend the original CAMELS time series to recent daily streamflow for three gauges.
- [Drainage-area metadata](drainage-areas.md): offline access to source area fields for selected gauges.
- [API reference](reference.md): the public functions, their arguments and the columns they return.

## Providers

RivRetrieve supports observation retrieval from national publication services. The
[README](../README.md#river-data-and-where-to-find-them) lists them with their station counts.

The data belong to those agencies, and they document their own networks far better than we could.
These pages therefore cover only what you need in order to work with a provider through
RivRetrieve, and link to the agency for everything else.

Whatever the provider, RivRetrieve gives you the same things:

- **Stations**: an identifier, a position where recorded, and the station’s catalogued products.
- **Products**: a variable (discharge, stage or water temperature), a statistic (mean, maximum,
  minimum or an instantaneous reading) and a time step (daily, hourly or irregular). Statistics
  and time steps remain unknown where they are not established.
- **Units**: discharge in m³/s, stage in m, and water temperature in °C.
- **Times**: as the agency publishes them, each with its time zone, which is `unknown` when the
  source meaning has not been established.
- **Terms and citation**: these stay with the agency. Check them before using the data.

A page for each provider, describing its network, what it measures and how to cite it, is being
written:

- [Brazil: ANA](providers/br_ana.md)
- [Canada: Environment and Climate Change Canada](providers/ca_eccc.md)
- [France: Hub'Eau (`fr_hubeau`)](providers/fr_hubeau.md)
- [France: HydroPortail (`fr_hydroportail`)](providers/fr_hydroportail.md)
- [Japan: MLIT](providers/jp_mlit.md)
- [Norway: NVE](providers/no_nve.md)
- [Switzerland: FOEN, through Existenz.ch](providers/ch_foen.md)
- [Thailand: ThaiWater](providers/th_thaiwater.md)
- [United States — USGS](providers/usgs_nwis.md)

## How it works

- [Architecture](architecture.md): responsibilities, a traced request, contracts and verification.
- [Catalogue evidence](catalogue-evidence.md): what RivRetrieve records about where catalogue facts
  came from, and how to inspect it.
- [Catalogue absence](catalogue-absence.md): why a missing fact is not the same as a source saying
  nothing.

## Maintaining the software

- [Physical products and source series](product_dictionary.md): structured physical meaning and source identity.
- [Catalogue provenance](catalogue-provenance.md): current catalogue maintenance conventions.
- [Observation store layout](design/observation-store-layout.md): the current normative store specification.
- [Development conventions](development-conventions.md).

## Provider evidence records

Provider port notes retain source research and acquisition history. Use the
[API reference](reference.md#shipped-software-capabilities) for current software access:
eleven live providers, Canada and Poland through bulk stores, and South Africa for
catalogue discovery only.

- [Evidenced inventory account](provider_ports/evidenced_coverage.md). Its recorded limitations
  still apply: it does not establish countrywide inventory completeness or continuous observation
  history.
- [Provider port notes](provider_ports/): what was established about each source when it was
  added.

<details>
<summary>Port notes, one per provider</summary>

- [ba_fhmzbih](provider_ports/ba_fhmzbih.md)
- [br_ana](provider_ports/br_ana.md)
- [ca_eccc](provider_ports/ca_eccc.md)
- [ch_foen](provider_ports/ch_foen.md)
- [cz_chmi](provider_ports/cz_chmi.md)
- [fr_hubeau and fr_hydroportail](provider_ports/fr_hubeau.md)
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
uv run --with rdflib pytest -q tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
```

The tests replay committed source bytes through the public API. They do not test whether a
provider's service is available today.
