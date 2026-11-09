"""Explicit historical metadata selection at the catalogue boundary."""

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from rivretrieve._internal.issues import FatalContractError


@dataclass(frozen=True)
class HistoricalSource:
    consumer_directory: str
    series_ids: tuple[str, ...]


@dataclass(frozen=True)
class HistoricalRetention:
    historical_sources: tuple[HistoricalSource, ...]
    retained_station_ids: tuple[str, ...]

    @property
    def historical_series_ids(self) -> tuple[str, ...]:
        return tuple(identity for source in self.historical_sources for identity in source.series_ids)


def _identities(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FatalContractError("Retention identities must be a list")
    identities = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise FatalContractError("Retention requires nonblank identities")
        identities.append(item)
    if len(set(identities)) != len(identities):
        raise FatalContractError("Retention requires distinct identities")
    return tuple(identities)


def read_retention(path: Path) -> HistoricalRetention:
    """Read a schema-2 manifest with distinct series assigned to relative source directories."""
    document = json.loads(path.read_text())
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "historical_sources", "retained_station_ids"}
        or document["schema_version"] != 2
    ):
        raise FatalContractError("Invalid USGS retention manifest schema")
    if not isinstance(document["historical_sources"], list):
        raise FatalContractError("Historical sources must be a list")
    sources = []
    for item in document["historical_sources"]:
        if not isinstance(item, dict) or set(item) != {"consumer_directory", "series_ids"}:
            raise FatalContractError("Invalid historical source selection")
        directory = item["consumer_directory"]
        if (
            not isinstance(directory, str)
            or not directory
            or PurePosixPath(directory).is_absolute()
            or any(part in {"", ".", ".."} for part in directory.split("/"))
            or "\\" in directory
        ):
            raise FatalContractError("Historical consumer directory must be a relative path")
        sources.append(HistoricalSource(directory, _identities(item["series_ids"])))
    selection = HistoricalRetention(tuple(sources), _identities(document["retained_station_ids"]))
    if len({source.consumer_directory for source in sources}) != len(sources) or len(
        set(selection.historical_series_ids)
    ) != len(selection.historical_series_ids):
        raise FatalContractError("Historical sources and series must be distinct")
    return selection


def load_historical_features(selection: HistoricalRetention, evidence_root: Path) -> list[dict[str, object]]:
    """Read selected rows from each original source; fail if its assigned series are missing."""
    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import read_modern_metadata

    selected = []
    root = evidence_root.resolve()
    for source in selection.historical_sources:
        directory = (root / source.consumer_directory).resolve()
        if not directory.is_relative_to(root):
            raise FatalContractError("Historical source escapes the evidence root")
        features, _ = read_modern_metadata(directory)
        rows = [item for item in features if item.get("id") in source.series_ids]
        if {item["id"] for item in rows} != set(source.series_ids):
            raise FatalContractError("Selected historical series missing from source")
        if len(rows) != len(source.series_ids):
            raise FatalContractError("Selected historical series repeated in source")
        selected.extend(rows)
    return selected
