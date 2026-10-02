"""Transport seam : EngineRequest × ProviderStages × Transport → assembled observations."""

from datetime import datetime
from pathlib import Path

import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    ProductWindowDeclarations,
    RequestedWindow,
    StopConvention,
    WindowDeclaration,
    WindowEndpoint,
)
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
from tests.usgs_modern_recordings import ModernReplay, body

assert isinstance(declaration.observations, LiveStages)
usgs_nwis = declaration.observations.stages

_PRODUCT = ProductId("discharge_daily_mean")


class _ExclusiveStopUsgs:
    config = usgs_nwis.config
    fetch = staticmethod(usgs_nwis.fetch)
    parse = staticmethod(usgs_nwis.parse)
    window_declarations = ProductWindowDeclarations(
        products={
            **usgs_nwis.window_declarations.products,
            _PRODUCT: WindowDeclaration(
                granularity=usgs_nwis.window_declarations.products[_PRODUCT].granularity,
                rendering=usgs_nwis.window_declarations.products[_PRODUCT].rendering,
                stop_convention=StopConvention.EXCLUSIVE,
                size=usgs_nwis.window_declarations.products[_PRODUCT].size,
            ),
        }
    )


def _request() -> ObservationRequest:
    return ObservationRequest(
        provider_id=ProviderId("usgs_nwis"),
        stations=("07374000",),
        products=(_PRODUCT,),
        window=RequestedWindow(
            start=WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            end=WindowEndpoint.from_datetime(datetime(2024, 1, 7, 23, 59, 59, 999999)),
        ),
    )


def _provenance() -> ObservationProvenance:
    return ObservationProvenance(source="recording", provider_id=ProviderId("usgs_nwis"))


def test_stop_convention_flip_misses_exact_recording(retained_evidence_root: Path) -> None:
    import json

    request = _request()
    replay = ModernReplay("daily-07374000-discharge-mean", evidence_root=retained_evidence_root)
    baseline = drive(request, usgs_nwis, provenance=_provenance(), transport=replay)
    assert baseline.canonical_rows.height == 7
    assert set(baseline.canonical_rows["time_zone"]) == {"unknown"}
    expected = [
        float(feature["properties"]["value"]) * 0.028316846592
        for feature in json.loads(body("daily-07374000-discharge-mean", evidence_root=retained_evidence_root))[
            "features"
        ]
        if "2024-01-01" <= feature["properties"]["time"] <= "2024-01-07"
    ]
    assert baseline.canonical_rows["value"].to_list() == expected
    with pytest.raises(AssertionError, match="No exact modern recording") as exc_info:
        drive(request, _ExclusiveStopUsgs, provenance=_provenance(), transport=replay)
    assert "2023-12-30/2024-01-10" in str(exc_info.value)


def test_provider_modules_cannot_import_or_name_private_credential_request_authority() -> None:
    import ast

    provider_root = Path(__file__).parents[1] / "src" / "rivretrieve" / "_internal" / "providers"
    forbidden = {
        "_CredentialTransportRequest",
        "_ExecutableTransportRequest",
        "_make_credential_transport_request",
        "_is_authorized_credential_request",
    }
    violations: list[str] = []
    for source_path in provider_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden:
                        violations.append(f"{source_path}:{node.lineno}:{alias.name}")
            if isinstance(node, ast.Name) and node.id in forbidden:
                violations.append(f"{source_path}:{node.lineno}:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                violations.append(f"{source_path}:{node.lineno}:{node.attr}")
    assert violations == []
