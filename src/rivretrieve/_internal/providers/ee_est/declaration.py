"""Provider declaration for Estonia Keskkonnaagentuur (ee_est)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from types import MappingProxyType

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ee_est.config import config, window_declarations
from rivretrieve._internal.providers.ee_est.fetch import EeEstRequestPlanner, fetch
from rivretrieve._internal.providers.ee_est.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


def _load_station_codes(catalogue: Path) -> Mapping[str, tuple[int, ...]]:
    """Verify and load packaged station_codes.json against croissant.json digest."""
    try:
        descriptor = json.loads((catalogue / "croissant.json").read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FatalContractError(f"ee_est catalogue descriptor unreadable: {exc}") from exc
    if not isinstance(descriptor, dict) or not isinstance(distribution := descriptor.get("distribution"), list):
        raise FatalContractError("ee_est catalogue descriptor lacks distribution list")
    entries = {
        entry["contentUrl"]: entry
        for entry in distribution
        if isinstance(entry, dict) and isinstance(entry.get("contentUrl"), str)
    }
    file_entry = entries.get("station_codes.json")
    expected_digest = file_entry.get("sha256") if file_entry is not None else None
    if not isinstance(expected_digest, str) or not expected_digest:
        raise FatalContractError("ee_est catalogue descriptor lacks station_codes.json digest")
    try:
        payload = (catalogue / "station_codes.json").read_bytes()
    except OSError as exc:
        raise FatalContractError(f"ee_est station_codes.json unreadable: {exc}") from exc
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != expected_digest:
        raise FatalContractError(
            f"ee_est station_codes.json checksum mismatch: expected {expected_digest}, got {actual_digest}"
        )
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FatalContractError(f"ee_est station_codes.json invalid JSON: {exc}") from exc
    if not isinstance(decoded, dict) or not decoded:
        raise FatalContractError("ee_est station_codes.json must decode to a non-empty JSON object")
    codes: dict[str, tuple[int, ...]] = {}
    for station_id, raw_codes in decoded.items():
        if not isinstance(station_id, str) or not station_id or station_id.strip() != station_id:
            raise FatalContractError(f"ee_est station_codes.json invalid station_id: {station_id!r}")
        if not isinstance(raw_codes, list):
            raise FatalContractError(f"ee_est station_codes.json entry for {station_id!r} must be a list")
        parsed: list[int] = []
        seen: set[int] = set()
        for item in raw_codes:
            if type(item) is not int or item <= 0 or item in seen:
                raise FatalContractError(
                    f"ee_est station_codes.json invalid or duplicate jaam_kood {item!r} on {station_id!r}"
                )
            seen.add(item)
            parsed.append(item)
        codes[station_id] = tuple(parsed)
    return MappingProxyType(codes)


_CATALOGUE_DIR = Path(__file__).with_name("catalogue")
_STATION_CODES = _load_station_codes(_CATALOGUE_DIR)


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    request_planner = EeEstRequestPlanner(station_codes=_STATION_CODES)
    fetch = staticmethod(partial(fetch, station_codes=_STATION_CODES))
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=_CATALOGUE_DIR,
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
