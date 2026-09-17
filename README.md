# RivRetrieve

RivRetrieve retrieves river-gauge observations through a shared Python API.
It harmonises identifiers, units and returned columns. It leaves source quality
judgements and study suitability to the reader.

## Install

Requires Python 3.13 or later. In your Python project:

```bash
uv add rivretrieve
```

For optional station maps, use `uv add "rivretrieve[map]"`.

## First retrieval

This example requests one day of USGS daily mean discharge. It requires network access,
not credentials. Discovery reads the packaged catalogue.

```python
import rivretrieve as rr

selection = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
selection = rr.pick(selection, station="07374000")
print(rr.as_frame(selection))

result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True)
print(result.data)
print(result.issues)
print(result.provenance)
```

The result contains a Polars frame with `time`, `time_zone`, `station_id`, `product_id`
and `value`. Discharge values use m³/s. Read timestamps together with their zone column.
Inspect issues even when retrieval returns rows. A successful call does not establish
continuous records or scientific comparability.

## Documentation

Start with the [documentation index](docs/README.md).

- [Usage](docs/usage.md): selections, results, windows, issues, credentials, cache and receipts.
- [Recent streamflow for CAMELS-US gauges](docs/examples/camels-us.md).
- [Public API and software reference](docs/reference.md).
- [Architecture](docs/architecture.md): responsibilities, a traced request and contracts.

Potential-provider suggestions can include source links and relevant access information
in a [GitHub issue](https://github.com/RivRetrieve/RivRetrieve/issues).
