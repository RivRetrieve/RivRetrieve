"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

import hashlib
import json
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from types import MappingProxyType

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.registration import CredentialHeaderBinding, LiveStages, ProviderDeclaration
from rivretrieve._internal.providers.usgs_nwis.config import config, window_declarations
from rivretrieve._internal.providers.usgs_nwis.fetch import fetch
from rivretrieve._internal.providers.usgs_nwis.parse import parse


def _load_monitoring_locations(catalogue: Path) -> Mapping[str, str]:
    """Resolve and validate the packaged source identities at provider composition."""
    try:
        content = (catalogue / "monitoring_locations.json").read_bytes()
        descriptor = json.loads((catalogue / "croissant.json").read_bytes())
        entries = [
            entry for entry in descriptor["distribution"] if entry.get("contentUrl") == "monitoring_locations.json"
        ]
        if len(entries) != 1 or entries[0].get("sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("monitoring-location identity recording hash does not match the catalogue")
        locations = json.loads(content)
        if (
            not isinstance(locations, dict)
            or not locations
            or any(
                not isinstance(station, str)
                or not station.strip()
                or not isinstance(location, str)
                or not location.strip()
                or not location.endswith("-" + station)
                for station, location in locations.items()
            )
        ):
            raise ValueError("monitoring locations must map station strings to acquired agency-site identifiers")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise FatalContractError(f"Invalid packaged USGS monitoring-location identities: {error}") from error
    return MappingProxyType(locations)


class _Stages:
    """USGS live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(
        partial(
            fetch,
            monitoring_locations=_load_monitoring_locations(Path(__file__).with_name("catalogue")),
        )
    )
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    optional_credentials=("USGS_API_KEY",),
    credential_headers=(CredentialHeaderBinding("USGS_API_KEY", "X-Api-Key", ("https://api.waterdata.usgs.gov",)),),
)
