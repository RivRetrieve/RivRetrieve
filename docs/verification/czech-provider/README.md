# Czech provider documentation verification

The provider page was checked on 2026-09-28 for
[PR #295](https://github.com/RivRetrieve/RivRetrieve/pull/295), against implementation
and catalogue revision `46028d1441a958cccb9a2863fda1f8c68fc09d6e`.
The private archive retains the original verification record, source research,
acquisition log and execution outputs. Follow [verification evidence](../../maintenance/evidence.md)
for access to those historical inputs. Source checks, recorded tests and offline
catalogue inspection establish different facts.

## Public example and catalogue inspection

[`example.py`](example.py) contains the provider page's Python example. It makes a
live request with `cache="bypass"`. Its historical output belongs to the archive;
a fresh run can return revised values or different availability.

[`inspect_catalogue.py`](inspect_catalogue.py) reads the packaged catalogue offline.
It checks location and series counts and the catalogue's inventory status. Listed
candidates do not establish observations for a requested period.

```sh
uv run python docs/verification/czech-provider/example.py
uv run python docs/verification/czech-provider/inspect_catalogue.py
```

## Source checks

[`check_sources.py`](check_sources.py) downloads current publisher documents and
extracts the historical dataset PDF. Supply an external output directory for fresh
responses, and keep the acquisition log outside the checkout:

```sh
uv run python docs/verification/czech-provider/check_sources.py \
  --out "$SOURCE_OUTPUT_ROOT" > "$SOURCE_CHECK_LOG"
```

`SOURCE_OUTPUT_ROOT` and `SOURCE_CHECK_LOG` must name external private locations.
The tool requires `--out` and rejects directories inside a source checkout.
These new acquisitions do not replace archived historical responses under their
original identities. The archive retains the original source research, quotations,
unofficial translations and acquisition context.

## Recorded tests

Retrieve the exact Czech inputs following the private archive instructions. Set
`RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external directory with the retained
repository-relative paths. Then run:

```sh
uv run pytest tests/test_cz_chmi_observations.py \
  tests/test_chmi_source_boundary_isolation.py \
  tests/test_cz_chmi_hourly_semantics_regression.py \
  tests/test_cz_chmi_boundary_probe.py -q --tb=no -p no:cacheprovider
uv run pytest tests/test_documentation.py tests/test_supporting_documentation.py \
  tests/test_reference_contracts.py -q --tb=no -p no:cacheprovider
uv run python scripts/generate_reference.py --check
```

Keep test temporary files and full output outside source checkouts. Missing retained
inputs fail the checks. Recorded tests check annual coalescing, source means, units,
conversion, nulls, public routing, exact receipts, hourly semantics and isolated
source failures. They do not establish current service availability.

## Interpretation limits

A successful live example establishes only the requested station, quantity and
week at the retrieval time. An empty issue tuple is not a scientific quality
assessment. Values and availability can change.

Neither the catalogue nor a directory listing establishes continuous coverage,
station-specific earliest dates, availability of every series, complete latest-year
observations, historical finality or averaging boundaries. Published institutional
duties do not establish that CHMI alone operates every station. Citation guidance
is practical advice, not a publisher-specified template.
