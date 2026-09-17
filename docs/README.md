# Documentation

## Getting started

Follow the [installation and first retrieval](../README.md#install).
Then inspect the [returned data and issues](usage.md#retrieve-and-inspect-results).

## Software documentation

- [Usage](usage.md): discovery, selection, retrieval, windows, issues, supplied credentials,
  cache, receipts and optional mapping.
- [CAMELS-US example](examples/camels-us.md): retrieve recent daily streamflow for three gauges.
- [API and software reference](reference.md): public signatures, types and generated declarations.
- [Architecture](architecture.md): purpose, responsibilities, a traced request, contracts and verification.
- [Catalogue evidence](catalogue-evidence.md): normalized acquisition evidence and inspection.
- [Catalogue absence](catalogue-absence.md): distinguish withheld facts from source silence.

## Providers

Provider descriptions belong to the colleague responsible for source background, coverage
and credential acquisition. This section is a handoff placeholder, not a provider survey.
The [software reference](reference.md) records shipped declarations without interpreting coverage.

## Detailed and historical records

The pages above describe current software. Earlier design documents preserve the reasoning
at their recorded revision. Their API names, provider counts and execution details can be
superseded. Use them as history rather than as current usage instructions.

- [Accepted architecture decisions](adr/).
- [Domain vocabulary](../CONTEXT.md). Historical operational counts are not a capability census.
- [Catalogue provenance](catalogue-provenance.md).
- [Provider port evidence](provider_ports/) and [evidenced inventory account](provider_ports/evidenced_coverage.md).
- [Design analyses](design/) and [delivery records](milestones/).
- [Development conventions](development-conventions.md).

The inventory account's recorded limitations remain applicable. It does not establish
countrywide inventory completeness or continuous observation history.

Existing provider port evidence notes:

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

## Local documentation checks

Markdown reads directly on GitHub. No site build, credentials or bulk download is needed.
From a source checkout, run:

```bash
uv run python scripts/generate_reference.py --check
uv run pytest -q tests/test_documentation.py
```

The tests replay committed source bytes through the public API. They do not test current
service availability. Validation evidence is recorded in the
[documentation PR](https://github.com/RivRetrieve/RivRetrieve/pull/246).
Hosting is deferred and is not delivered by these pages.
