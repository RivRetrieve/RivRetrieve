"""SENAMHI live route wiring preserves physical unknowns."""

from rivretrieve._internal.engine import Unit, UnknownTemporalSupport
from rivretrieve._internal.providers.pe_senamhi.config import config, window_declarations


def test_complete_products_preserve_unknown_time_and_source_units():
    configuration = config()
    expected = {
        "phisis_daily_flow",
        "phisis_daily_level",
        "phisis_daily_level_above_sea_level",
        "phisis_hourly_flow",
        "phisis_hourly_level",
        "phisis_hourly_level_above_sea_level",
        "monthly_archive_nivel_del_rio_06h",
        "monthly_archive_nivel_del_rio_10h",
        "monthly_archive_nivel_del_rio_14h",
        "monthly_archive_nivel_del_rio_18h",
        "monthly_archive_nivel_del_rio_promedio",
        "monthly_archive_n_nivelagua",
        "monthly_archive_n_nivelmedio",
        "monthly_archive_n_niv_inst_00",
        "monthly_archive_n_niv_inst_10",
    }
    assert set(configuration.products) == expected
    assert set(window_declarations().products) == expected
    assert configuration.zone.value == "unknown"
    for product, definition in configuration.products.items():
        assert isinstance(definition.semantics, UnknownTemporalSupport)
        assert definition.unit == (Unit.M3_S if product.endswith("flow") else Unit.M)
        assert definition.coordinates.value.unit == (
            "m.s.n.m" if product.endswith("above_sea_level") else definition.unit.value
        )


def test_live_stages_share_monthly_requests_and_forward_selection():
    from datetime import UTC, datetime

    from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
    from rivretrieve._internal.providers.pe_senamhi.declaration import declaration
    from rivretrieve._internal.providers.registration import LiveStages
    from rivretrieve._internal.transport import TransportResponse
    from rivretrieve._internal.window_planning import plan_windows

    assert isinstance(declaration.observations, LiveStages)
    assert declaration.required_credentials == ()
    stages = declaration.observations.stages
    monthly_products = frozenset(
        product for product in stages.config.products if product.startswith("monthly_archive_")
    )
    assert stages.shared_acquisition_products == (monthly_products,)
    products = ("monthly_archive_n_nivelagua", "monthly_archive_n_nivelmedio")
    bounds = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 31, 23, 59, 59)),
    )
    windows = {product: plan_windows(bounds, stages.window_declarations.products[product]) for product in products}

    class Transport:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            return TransportResponse(
                content=b'{"status":true,"data":{"columns":[],"readings":[]}}',
                status_code=200,
                retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
                content_type="application/json",
                url=request.url,
                request_parameters=request.params,
            )

    transport = Transport()
    result = stages.fetch(("A",), products, windows, bounds, stages.config, transport)
    assert len(transport.requests) == 1
    assert transport.requests[0].params == {"period": "202601"}
    assert result.value[0].station_products == (("A", products[0]), ("A", products[1]))
    assert {series.product_id for series in result.series} == set(products)
