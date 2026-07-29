"""config : () → ProviderConfig."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Daily,
    DayDefinition,
    Instant,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId


@dataclass(frozen=True, slots=True)
class UsgsNwisSourceCoordinates:
    endpoint: Literal["dv", "iv"]
    parameter_code: str
    statistic_code: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str):
            raise TypeError("endpoint must be a string")
        if self.endpoint not in ("dv", "iv"):
            raise ValueError("endpoint must be 'dv' or 'iv'")
        if not isinstance(self.parameter_code, str):
            raise TypeError("parameter code must be a string")
        if re.fullmatch(r"[0-9]{5}", self.parameter_code) is None:
            raise ValueError("parameter code must be exactly five ASCII digits")
        if self.statistic_code is not None and not isinstance(self.statistic_code, str):
            raise TypeError("statistic code must be a string or None")
        if self.endpoint == "dv":
            if self.statistic_code is None or re.fullmatch(r"[0-9]{5}", self.statistic_code) is None:
                raise ValueError("DV statistic code must be exactly five ASCII digits")
        elif self.statistic_code is not None:
            raise ValueError("IV statistic code must be None")


_CONFIG = ProviderConfig(
    zone=ZoneValue("unknown"),
    products={
        ProductId("discharge_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("dv", "00060", "00003")),
            unit=Unit.FT3_S,
            semantics=Daily(DayDefinition("unknown")),
        ),
        ProductId("discharge_instantaneous"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("iv", "00060", None)),
            unit=Unit.FT3_S,
            semantics=Instant(),
        ),
        ProductId("stage_daily_mean"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("dv", "00065", "00003")),
            unit=Unit.FT,
            semantics=Daily(DayDefinition("unknown")),
        ),
        ProductId("stage_daily_max"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("dv", "00065", "00001")),
            unit=Unit.FT,
            semantics=Daily(DayDefinition("unknown")),
        ),
        ProductId("stage_daily_min"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("dv", "00065", "00002")),
            unit=Unit.FT,
            semantics=Daily(DayDefinition("unknown")),
        ),
        ProductId("stage_instantaneous"): ProductConfig(
            coordinates=SourceCoordinates(UsgsNwisSourceCoordinates("iv", "00065", None)),
            unit=Unit.FT,
            semantics=Instant(),
        ),
    },
    cache=None,
)


def config() -> ProviderConfig:
    return _CONFIG
