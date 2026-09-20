from rivretrieve._internal.engine import StopConvention, Unit, UnknownTemporalSupport, ZoneValue
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.config import ChFoenSourceCoordinates, config, window_declarations


def test_three_reported_products_preserve_all_established_field_units() -> None:
    value = config()
    assert value.zone == ZoneValue("+00:00")
    assert set(value.products) == {
        ProductId("discharge_reported"),
        ProductId("stage_reported"),
        ProductId("water_temperature_reported"),
    }
    expected = {
        "discharge_reported": (("flow", Unit.M3_S), ("flow_ls", Unit.L_S)),
        "stage_reported": (("height_abs", Unit.M), ("height", Unit.M)),
        "water_temperature_reported": (("temperature", Unit.DEG_C),),
    }
    for product_id, alternatives in expected.items():
        product = value.products[ProductId(product_id)]
        assert isinstance(product.semantics, UnknownTemporalSupport)
        coordinates = product.coordinates.value
        assert isinstance(coordinates, ChFoenSourceCoordinates)
        assert tuple((field.name, field.unit) for field in coordinates.fields) == alternatives
    assert all(d.stop_convention is StopConvention.INCLUSIVE for d in window_declarations().products.values())


def test_declaration_selects_route_specific_stop_semantics_from_transport_capability() -> None:
    from rivretrieve._internal.driver import TransportWindowDeclarationProvider
    from rivretrieve._internal.providers.ch_foen.declaration import declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.recordings import ReplayTransport
    from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader

    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    assert isinstance(stages, TransportWindowDeclarationProvider)
    plain = ReplayTransport(())
    authenticated = AuthenticatedTransport(
        plain, (CredentialHeader("Authorization", "Token SENTINEL", ("https://influx.konzept.space",)),)
    )
    assert {value.stop_convention for value in stages.window_declarations_for_transport(plain).products.values()} == {
        StopConvention.INCLUSIVE
    }
    assert {
        value.stop_convention for value in stages.window_declarations_for_transport(authenticated).products.values()
    } == {StopConvention.EXCLUSIVE}


def test_exact_parameters_recording_attests_native_units() -> None:
    import json
    from pathlib import Path

    from rivretrieve._internal.recordings import read_recording

    recording = read_recording(Path("tests/test_data/ch_foen_parameters_2026-09-02.recording.json"))
    assert recording.request.url == "https://api.existenz.ch/apiv1/hydro/parameters"
    assert recording.request.parameters == {}
    assert recording.sha256 == "1d533be7715d55baf7ee36f8b07e6ec10a5b599ae653863c1d7e9f1e8eb78e39"
    document = json.loads(recording.content)
    units = {key: value["unit"] for key, value in document["payload"].items()}
    assert {name: units[name] for name in ("flow", "flow_ls", "height", "height_abs", "temperature")} == {
        "flow": "m3/s",
        "flow_ls": "l/s",
        "height": "m",
        "height_abs": "m",
        "temperature": "°C",
    }
