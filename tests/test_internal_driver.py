from datetime import datetime, timedelta

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.assembly import _AssemblyResult
from rivretrieve._internal.assembly import assemble as real_assemble
from rivretrieve._internal.catalogues.schemas import CatalogueSchema
from rivretrieve._internal.catalogues.schemas import validate_catalogue as real_validate_catalogue
from rivretrieve._internal.conversion import convert as real_convert
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    FetchWindow,
    Instant,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    Rows,
    RowsSchema,
    SourceCoordinates,
    Unit,
    WindowEndpoint,
    WithIssues,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.observations import ObservationProvenance, RawPayload
from rivretrieve._internal.primitives import IssueSeverity, OnIssue, ProductId, ProviderId

_STATIONS = (
    "station-1",
    "station-2",
    "station-3",
    "station-4",
    "station-5",
)
_PRODUCTS = (ProductId("level"),)


class _ThrowawayProvider:
    def __init__(
        self,
        config: ProviderConfig,
        payloads: tuple[Payload, ...],
        rows_by_station: dict[str, Rows],
        parse_issues_by_station: dict[str, tuple[Issue, ...]],
        fetch_issues: tuple[Issue, ...],
        events: list[str],
    ) -> None:
        self.config = config
        self._payloads = payloads
        self._rows_by_station = rows_by_station
        self._parse_issues_by_station = parse_issues_by_station
        self._fetch_issues = fetch_issues
        self._events = events

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]:
        self._events.append("fetch")
        assert stations == _STATIONS
        assert products == _PRODUCTS
        assert all(payload.fetch_window == window for payload in self._payloads)
        assert isinstance(window, FetchWindow)
        assert not isinstance(window, RequestedWindow)
        assert config is self.config
        return WithIssues(value=self._payloads, issues=self._fetch_issues)

    def parse(
        self,
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]:
        station_id = payload.station_products[0][0]
        self._events.append(f"parse:{station_id}")
        assert payload in self._payloads
        assert config is self.config
        return WithIssues(
            value=self._rows_by_station[station_id],
            issues=self._parse_issues_by_station[station_id],
        )


def _issue(
    code: str,
    *,
    severity: IssueSeverity = "warning",
    station_id: str = "",
) -> Issue:
    return Issue(
        severity=severity,
        code=code,
        message=f"{code} occurred for {station_id}",
        details={"code": code, "station_id": station_id},
        provider_id=ProviderId("throwaway"),
    )


def _request(window: RequestedWindow) -> ObservationRequest:
    return ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=_STATIONS,
        products=_PRODUCTS,
        window=window,
    )


def _config(coordinates: SourceCoordinates) -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=Instant(),
            )
        },
    )


def _payload(
    station_id: str,
    coordinates: SourceCoordinates,
    fetch_window: FetchWindow,
) -> Payload:
    return Payload(
        source_coordinates=coordinates,
        station_products=((station_id, ProductId("level")),),
        fetch_window=fetch_window,
        content={"station_id": station_id},
    )


def _rows(
    station_id: str,
    hour: int,
    value: float,
    *,
    time_zone: str = "+00:00",
) -> Rows:
    return pl.DataFrame(
        {
            "station_id": [station_id],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, hour)],
            "value": [value],
            "time_zone": [time_zone],
        },
        schema=RowsSchema.polars_schema,
    )


def _provenance(request: ObservationRequest) -> ObservationProvenance:
    return ObservationProvenance(
        source="test",
        provider_id=request.provider_id,
        request={
            "stations": list(_STATIONS),
            "products": ["level"],
        },
    )


def _raw(request: ObservationRequest) -> RawPayload:
    return RawPayload(
        provider_id=request.provider_id,
        content_type="application/json",
        content=b'{"provider":"throwaway"}',
        metadata="throwaway payloads",
    )


def _windows() -> tuple[RequestedWindow, FetchWindow]:
    requested = RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 0)),
        end=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23)),
    )
    fetched = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 31, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 23)),
    )
    return requested, fetched


@pytest.mark.parametrize(
    ("case", "requested_start", "requested_end", "expected_start", "expected_end"),
    [
        (
            "month-seam",
            datetime(2026, 3, 1, 1, 2, 3, 456789),
            datetime(2026, 3, 30, 21, 22, 23, 654321),
            "2026-02-27T01:02:03.456789",
            "2026-04-01T21:22:23.654321",
        ),
        (
            "year-seam",
            datetime(2025, 12, 31, 12, 34, 56, 123456),
            datetime(2026, 1, 1, 23, 59, 59, 999999),
            "2025-12-29T12:34:56.123456",
            "2026-01-03T23:59:59.999999",
        ),
    ],
)
def test_drive_widens_fetch_window_by_exactly_two_calendar_days_across_month_and_year_seams(
    case: str,
    requested_start: datetime,
    requested_end: datetime,
    expected_start: str,
    expected_end: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(requested_start),
        WindowEndpoint.from_datetime(requested_end),
    )
    request = _request(requested)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    received: list[FetchWindow] = []

    class _CapturingProvider:
        def __init__(self) -> None:
            self.config = config

        def fetch(
            self,
            stations: tuple[str, ...],
            products: tuple[ProductId, ...],
            window: FetchWindow,
            supplied_config: ProviderConfig,
        ) -> WithIssues[tuple[Payload, ...]]:
            assert stations == _STATIONS
            assert products == _PRODUCTS
            assert supplied_config is config
            received.append(window)
            return WithIssues(value=())

        def parse(self, payload: Payload, supplied_config: ProviderConfig) -> WithIssues[Rows]:
            raise AssertionError("parse must not run without payloads")

    def recording_convert(
        rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        assert supplied_config is config
        assert window is requested
        return real_convert(rows, supplied_config, window)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    driver_module.drive(
        request,
        _CapturingProvider(),
        provenance=_provenance(request),
        raw=_raw(request),
    )

    assert case in {"month-seam", "year-seam"}
    assert len(received) == 1
    fetched = received[0]
    assert isinstance(fetched, FetchWindow)
    assert not isinstance(fetched, RequestedWindow)
    assert fetched.start.isoformat() == expected_start
    assert fetched.end.isoformat() == expected_end
    fetch_start = datetime(
        fetched.start.year,
        fetched.start.month,
        fetched.start.day,
        fetched.start.hour,
        fetched.start.minute,
        fetched.start.second,
        fetched.start.microsecond,
    )
    fetch_end = datetime(
        fetched.end.year,
        fetched.end.month,
        fetched.end.day,
        fetched.end.hour,
        fetched.end.minute,
        fetched.end.second,
        fetched.end.microsecond,
    )
    assert requested_start - fetch_start == timedelta(days=2)
    assert fetch_end - requested_end == timedelta(days=2)


def test_drive_accumulates_every_stage_issue_in_encounter_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested_window, fetch_window = _windows()
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    payloads = (
        _payload("station-1", coordinates, fetch_window),
        _payload("station-2", coordinates, fetch_window),
    )
    fetch_issues = (
        _issue("fetch.first", severity="info"),
        _issue("fetch.second", severity="error"),
    )
    parse_issues = {
        "station-1": (
            _issue("parse.station-1.first", severity="error"),
            _issue("parse.station-1.second", severity="info"),
        ),
        "station-2": (_issue("parse.station-2", severity="warning"),),
    }
    rows_by_station = {
        "station-1": _rows("station-1", 12, 250.0),
        "station-2": _rows("station-2", 13, 300.0, time_zone="unknown"),
    }
    provider = _ThrowawayProvider(
        config,
        payloads,
        rows_by_station,
        parse_issues,
        fetch_issues,
        events,
    )
    provenance = _provenance(request)
    raw = _raw(request)

    def recording_convert(
        supplied_rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        expected_rows = pl.concat(
            [
                rows_by_station["station-1"],
                rows_by_station["station-2"],
            ]
        )
        pl_testing.assert_frame_equal(supplied_rows, expected_rows)
        assert supplied_config is config
        assert window is requested_window
        assert window is not fetch_window
        return real_convert(supplied_rows, supplied_config, window)

    def recording_assemble(
        canonical_rows: CanonicalRows,
        supplied_provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        supplied_raw: RawPayload,
    ) -> _AssemblyResult:
        events.append("assemble")
        assert supplied_provenance is provenance
        assert tuple(issue.code for issue in issues) == (
            "fetch.first",
            "fetch.second",
            "parse.station-1.first",
            "parse.station-1.second",
            "parse.station-2",
        )
        assert supplied_raw is raw
        return real_assemble(canonical_rows, supplied_provenance, issues, supplied_raw)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    monkeypatch.setattr(driver_module, "assemble", recording_assemble)

    result = driver_module.drive(
        request,
        provider,
        provenance=provenance,
        raw=raw,
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 13),
            ],
            "time_zone": ["+00:00", "unknown"],
            "station_id": ["station-1", "station-2"],
            "product_id": ["level", "level"],
            "value": [2.5, 3.0],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.provenance is provenance
    assert tuple(issue.code for issue in result.issues) == (
        "fetch.first",
        "fetch.second",
        "parse.station-1.first",
        "parse.station-1.second",
        "parse.station-2",
    )
    assert result.raw is raw
    assert events == [
        "fetch",
        "parse:station-1",
        "parse:station-2",
        "convert",
        "assemble",
    ]


def test_drive_clips_unknown_zone_instants_at_both_closed_edges_without_warning() -> None:
    events: list[str] = []
    requested_window = RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 12)),
        end=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 13)),
    )
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 31, 12)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 13)),
    )
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    timestamps = (
        datetime(2026, 1, 2, 11, 59, 59, 999999),
        datetime(2026, 1, 2, 12),
        datetime(2026, 1, 2, 12, 30),
        datetime(2026, 1, 2, 13),
        datetime(2026, 1, 2, 13, 0, 0, 1),
    )
    payloads = tuple(_payload(station_id, coordinates, fetch_window) for station_id in _STATIONS)
    rows_by_station = {
        station_id: pl.DataFrame(
            {
                "station_id": [station_id],
                "product_id": ["level"],
                "time": [timestamp],
                "value": [value],
                "time_zone": ["unknown"],
            },
            schema=RowsSchema.polars_schema,
        )
        for station_id, timestamp, value in zip(
            _STATIONS,
            timestamps,
            (100.0, 200.0, 300.0, 400.0, 500.0),
            strict=True,
        )
    }
    provider = _ThrowawayProvider(
        config,
        payloads,
        rows_by_station,
        dict.fromkeys(_STATIONS, ()),
        (),
        events,
    )

    result = driver_module.drive(
        request,
        provider,
        provenance=_provenance(request),
        raw=_raw(request),
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 12, 30),
                datetime(2026, 1, 2, 13),
            ],
            "time_zone": ["unknown", "unknown", "unknown"],
            "station_id": ["station-2", "station-3", "station-4"],
            "product_id": ["level", "level", "level"],
            "value": [2.0, 3.0, 4.0],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == ()


def test_drive_returns_four_stations_and_one_issue_when_one_of_five_fails() -> None:
    events: list[str] = []
    requested_window, fetch_window = _windows()
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    successful_stations = (
        "station-1",
        "station-2",
        "station-4",
        "station-5",
    )
    payloads = tuple(_payload(station_id, coordinates, fetch_window) for station_id in successful_stations)
    rows_by_station = {
        "station-1": _rows("station-1", 11, 100.0),
        "station-2": _rows("station-2", 12, 200.0),
        "station-4": _rows("station-4", 14, 400.0),
        "station-5": _rows("station-5", 15, 500.0),
    }
    provider = _ThrowawayProvider(
        config,
        payloads,
        rows_by_station,
        dict.fromkeys(successful_stations, ()),
        (_issue("fetch.station-3-not-found", severity="error"),),
        events,
    )
    provenance = _provenance(request)
    raw = _raw(request)

    result = driver_module.drive(
        request,
        provider,
        provenance=provenance,
        raw=raw,
    )

    expected = pl.DataFrame(
        {
            "time": [
                datetime(2026, 1, 2, 11),
                datetime(2026, 1, 2, 12),
                datetime(2026, 1, 2, 14),
                datetime(2026, 1, 2, 15),
            ],
            "time_zone": ["+00:00", "+00:00", "+00:00", "+00:00"],
            "station_id": [
                "station-1",
                "station-2",
                "station-4",
                "station-5",
            ],
            "product_id": ["level", "level", "level", "level"],
            "value": [1.0, 2.0, 4.0, 5.0],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert tuple(issue.code for issue in result.issues) == ("fetch.station-3-not-found",)
    assert result.provenance is provenance
    assert result.raw is raw
    assert events == [
        "fetch",
        "parse:station-1",
        "parse:station-2",
        "parse:station-4",
        "parse:station-5",
    ]


def test_drive_all_source_failure_reaches_convert_and_assemble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    requested_window, _ = _windows()
    request = _request(requested_window)
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    fetch_issues = tuple(
        _issue("fetch.station_not_found", severity=severity, station_id=station_id)
        for station_id, severity in zip(
            _STATIONS,
            ("info", "warning", "error", "info", "error"),
            strict=True,
        )
    )
    provider = _ThrowawayProvider(
        config,
        (),
        {},
        {},
        fetch_issues,
        events,
    )
    provenance = _provenance(request)
    raw = _raw(request)

    def recording_convert(
        supplied_rows: Rows,
        supplied_config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        expected_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
        pl_testing.assert_frame_equal(supplied_rows, expected_rows)
        assert supplied_config is config
        assert window is requested_window
        return real_convert(supplied_rows, supplied_config, window)

    def recording_assemble(
        canonical_rows: CanonicalRows,
        supplied_provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        supplied_raw: RawPayload,
    ) -> _AssemblyResult:
        events.append("assemble")
        expected_canonical = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
        pl_testing.assert_frame_equal(canonical_rows, expected_canonical)
        assert supplied_provenance is provenance
        assert issues == fetch_issues
        assert supplied_raw is raw
        return real_assemble(canonical_rows, supplied_provenance, issues, supplied_raw)

    monkeypatch.setattr(driver_module, "convert", recording_convert)
    monkeypatch.setattr(driver_module, "assemble", recording_assemble)

    result = driver_module.drive(
        request,
        provider,
        provenance=provenance,
        raw=raw,
    )

    expected = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == fetch_issues
    assert result.provenance is provenance
    assert result.raw is raw
    assert events == ["fetch", "convert", "assemble"]
    assert {name for name in dir(provider) if not name.startswith("_")} == {
        "config",
        "fetch",
        "parse",
    }


class _BoundaryProvider:
    def __init__(
        self,
        config: ProviderConfig,
        payloads: tuple[Payload, ...],
        rows_by_payload: tuple[Rows, ...],
        events: list[str],
    ) -> None:
        self.config = config
        self._payloads = payloads
        self._rows_by_payload = rows_by_payload
        self._events = events

    def fetch(
        self,
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        window: FetchWindow,
        config: ProviderConfig,
    ) -> WithIssues[tuple[Payload, ...]]:
        self._events.append("fetch")
        assert stations == tuple(f"station-{index}" for index in range(1, len(self._payloads) + 1))
        assert products == (ProductId("level"),)
        assert window == self._payloads[0].fetch_window
        assert config is self.config
        return WithIssues(value=self._payloads)

    def parse(
        self,
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]:
        index = next(index for index, candidate in enumerate(self._payloads) if candidate is payload)
        self._events.append(f"parse-{index + 1}")
        assert config is self.config
        return WithIssues(value=self._rows_by_payload[index])


def _drive_boundary_rows(
    rows_by_payload: tuple[Rows, ...],
    events: list[str],
) -> _AssemblyResult:
    requested_window = RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 0)),
        end=WindowEndpoint.from_datetime(datetime(2026, 1, 2, 23)),
    )
    request = ObservationRequest(
        provider_id=ProviderId("throwaway"),
        stations=tuple(f"station-{index}" for index in range(1, len(rows_by_payload) + 1)),
        products=(ProductId("level"),),
        window=requested_window,
    )
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 12, 31, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 4, 23)),
    )
    coordinates = SourceCoordinates({"parameter": "height"})
    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("level"): ProductConfig(
                coordinates=coordinates,
                unit=Unit.CM,
                semantics=Instant(),
            )
        },
    )
    payloads = tuple(
        Payload(
            source_coordinates=coordinates,
            station_products=((station_id, ProductId("level")),),
            fetch_window=fetch_window,
            content={"payload_index": index},
        )
        for index, station_id in enumerate(request.stations, start=1)
    )
    provider = _BoundaryProvider(config, payloads, rows_by_payload, events)
    provenance = ObservationProvenance(
        source="test",
        provider_id=request.provider_id,
        request={"stations": list(request.stations), "products": ["level"]},
    )
    raw = RawPayload(
        provider_id=request.provider_id,
        content_type="application/json",
        content=b"{}",
        metadata="boundary payloads",
    )

    return driver_module.drive(
        request,
        provider,
        provenance=provenance,
        raw=raw,
    )


def test_drive_rejects_each_malformed_parse_result_before_later_parse_or_convert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    malformed_rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 12)],
            "value": [250.0],
        },
        schema={
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "time": pl.Datetime(),
            "value": pl.Float64,
        },
    )
    later_rows = pl.DataFrame(
        {
            "station_id": ["station-2"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 13)],
            "value": [300.0],
            "time_zone": ["+00:00"],
        },
        schema=RowsSchema.polars_schema,
    )

    def forbidden_convert(
        rows: Rows,
        config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        raise AssertionError("convert must not run after a malformed parse result")

    monkeypatch.setattr(driver_module, "convert", forbidden_convert)

    with pytest.raises(FatalContractError, match="Rows is missing required columns: time_zone"):
        _drive_boundary_rows((malformed_rows, later_rows), events)

    assert events == ["fetch", "parse-1"]


def test_drive_rejects_malformed_second_parse_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    first_rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 12)],
            "value": [250.0],
            "time_zone": ["+00:00"],
        },
        schema=RowsSchema.polars_schema,
    )
    malformed_rows = pl.DataFrame(
        {
            "station_id": ["station-2"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 13)],
            "value": [300.0],
        },
        schema={
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "time": pl.Datetime(),
            "value": pl.Float64,
        },
    )

    def forbidden_convert(
        rows: Rows,
        config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        raise AssertionError("convert must not run after a malformed parse result")

    monkeypatch.setattr(driver_module, "convert", forbidden_convert)

    with pytest.raises(FatalContractError, match="Rows is missing required columns: time_zone"):
        _drive_boundary_rows((first_rows, malformed_rows), events)

    assert events == ["fetch", "parse-1", "parse-2"]


def test_drive_rejects_malformed_canonical_rows_before_assemble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    parsed_rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["level"],
            "time": [datetime(2026, 1, 2, 12)],
            "value": [250.0],
            "time_zone": ["+00:00"],
        },
        schema=RowsSchema.polars_schema,
    )
    malformed_canonical_rows = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 12)],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [2.5],
        },
        schema={
            "time": pl.Datetime(),
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "value": pl.Float64,
        },
    )

    def malformed_convert(
        rows: Rows,
        config: ProviderConfig,
        window: RequestedWindow,
    ) -> WithIssues[CanonicalRows]:
        events.append("convert")
        return WithIssues(value=malformed_canonical_rows)

    def forbidden_assemble(
        canonical_rows: CanonicalRows,
        provenance: ObservationProvenance,
        issues: tuple[Issue, ...],
        raw: RawPayload,
    ) -> _AssemblyResult:
        events.append("assemble")
        raise AssertionError("assemble must not run after malformed canonical rows")

    monkeypatch.setattr(driver_module, "convert", malformed_convert)
    monkeypatch.setattr(driver_module, "assemble", forbidden_assemble)

    with pytest.raises(FatalContractError, match="CanonicalRows is missing required columns: time_zone"):
        _drive_boundary_rows((parsed_rows,), events)

    assert events == ["fetch", "parse-1", "convert"]


def test_drive_accepts_well_formed_empty_rows_at_both_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    validation_calls: list[tuple[str, int, OnIssue]] = []
    empty_rows = pl.DataFrame(schema=RowsSchema.polars_schema)

    def recording_validator(
        frame: pl.DataFrame,
        schema: CatalogueSchema,
        *,
        on_issue: OnIssue,
    ) -> list[Issue]:
        validation_calls.append((schema.name, frame.height, on_issue))
        return real_validate_catalogue(frame, schema, on_issue=on_issue)

    monkeypatch.setattr(driver_module, "validate_catalogue", recording_validator)

    result = _drive_boundary_rows((empty_rows,), events)

    expected = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    pl_testing.assert_frame_equal(result.canonical_rows, expected)
    assert result.issues == ()
    assert validation_calls == [
        ("Rows", 0, "raise"),
        ("CanonicalRows", 0, "raise"),
    ]
    assert events == ["fetch", "parse-1"]
