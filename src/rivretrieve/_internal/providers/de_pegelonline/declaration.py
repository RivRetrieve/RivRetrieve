"""Germany PEGELONLINE (`de_pegelonline`) live-stage provider declaration.

Matches `ch_foen/declaration.py`'s shape exactly: no `shared_acquisition_products`
(unlike `lt_lhmt`), since each of the five products (`W`, `Q`, `WT`, `TRM`,
`TRM_WT`) is an independent per-station x product x window acquisition
(`fetch.py`'s own step-4 decision), not a co-published response.
"""

from pathlib import Path

from rivretrieve._internal.providers.de_pegelonline.config import config, window_declarations
from rivretrieve._internal.providers.de_pegelonline.fetch import fetch
from rivretrieve._internal.providers.de_pegelonline.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
