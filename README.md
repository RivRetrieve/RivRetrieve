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

station_map = rr.map_stations(providers="ch_foen")
```

`ch_foen` currently provides catalogue data only. Observation retrieval is unavailable until its
provider pipeline is ported to the engine stage contracts.

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
