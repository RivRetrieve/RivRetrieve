# RivRetrieve

A Python package for downloading global river gauge data.

## Installation

```bash
pip install rivretrieve
pip install "rivretrieve[map]"  # optional station-map backend
```

## Usage

```python
import rivretrieve as rr

rr.providers()
rr.stations()
rr.products()

provider = rr.provider("ch_foen")
provider.stations()
provider.products()
provider.station_products()

result = provider.observations(
    stations="2206",
    products="discharge_instantaneous",
    start="2024-01-01",
    end="2024-01-02",
)
data = result.to_polars()

same_result = rr.observations(
    provider="ch_foen",
    stations="2206",
    products="discharge_instantaneous",
    start="2024-01-01",
    end="2024-01-02",
)

station_map = rr.map_stations(providers="ch_foen", country="Switzerland")
```

## Development

```bash
uv run pytest                  # run tests
uv run ruff check --fix        # lint
uv run ruff format             # format
```

## Adding Dependencies

```bash
uv add <package>               # runtime dependency
uv add --group dev <package>   # dev dependency
```
