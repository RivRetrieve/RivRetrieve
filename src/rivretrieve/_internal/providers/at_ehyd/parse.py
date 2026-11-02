"""Normalize Austria eHYD CSV and JSON observations with honest coverage and gap rules."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.at_ehyd.config import (
    AtEhydInfoCoordinates,
    AtEhydOwfCoordinates,
    AtEhydPegelCoordinates,
    AtEhydPegelEndpointCoordinates,
)
from rivretrieve._internal.providers.at_ehyd.fetch import resolve_messstellen_info_files
from rivretrieve._internal.providers.at_ehyd.series import (
    _OWF_ROUTE_SPECS,
    IN_SCOPE_OWF_FTYPES,
    OWF_MISSING_VALUE_TOKEN,
    UNITS,
    parse_owf_header_facts,
    source_series,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
)

_PROVIDER_ID = ProviderId("at_ehyd")
_OWF_ENDPOINT_EVIDENCE = "https://ehyd.gv.at/services/MessstellenExtraData/owf"
_PEGEL_ENDPOINT_EVIDENCE: dict[str, str] = {
    "pegel_bgis": "https://ehyd.gv.at/services/Diagram/pegelBgis",
    "pegel_longterm": "https://ehyd.gv.at/services/Diagram/pegelLongterm",
}
_OWF_TIMESTAMP_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}$")
_OWF_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:,\d+)?$")
_OWF_INVALID_BODY_RE = re.compile(r"^Invalid\s*;\s*Lücke$")
_EZ_BRACKET_RE = re.compile(
    r"^\[(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?::\d{2})?),(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?::\d{2})?)\]$"
)
_EZ_BIS_RE = re.compile(
    r"^(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?::\d{2})?)\s*;\s*bis\s*;\s*(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(?::\d{2})?)$"
)
_PEGEL_BGIS_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_PEGEL_LONGTERM_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMPTY_PEGEL_LONGTERM_KEYS: frozenset[str] = frozenset(
    {
        "points_in_time",
        "current_value",
        "min_data",
        "min_year",
        "max_data",
        "max_year",
        "mit_data",
        "p5_data",
        "p95_data",
        "last_year_value",
    }
)


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one eHYD payload while confining malformed publisher bytes to bounded failures."""
    if not payload.station_products:
        raise FatalContractError("at_ehyd payload requires at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("at_ehyd payload must identify a single station")

    # Validate configured coordinate contracts upfront before source structure handling.
    for _, product in payload.station_products:
        _validated_product_coordinates(payload.source_coordinates.value, product, provider_config)

    if len(payload.station_products) > 1:
        frames: list[pl.DataFrame] = []
        definitions: dict[str, SourceSeries] = {}
        inventories: list[InventorySnapshot] = []
        outcomes: list[RetrievalOutcome] = []
        issues: list[Issue] = []
        for station, product in payload.station_products:
            pair_scope = (
                payload.scope.model_copy(update={"station_ids": (station,), "product_ids": (str(product),)})
                if payload.scope is not None
                else None
            )
            narrowed = replace(payload, station_products=((station, product),), scope=pair_scope)
            part = _parse_single_pair(narrowed, provider_config)
            if not part.rows.is_empty():
                frames.append(part.rows)
            for item in part.series:
                definitions[item.series_id] = item
            inventories.extend(part.inventories)
            outcomes.extend(part.outcomes)
            issues.extend(part.issues)
        combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
        return ParsedSeries(
            combined,
            tuple(definitions.values()),
            tuple(inventories),
            tuple(outcomes),
            tuple(issues),
        )

    return _parse_single_pair(payload, provider_config)


def _parse_single_pair(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    station, product = payload.station_products[0]
    product_coords = _validated_product_coordinates(payload.source_coordinates.value, product, provider_config)
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(
        provider_ids=("at_ehyd",),
        station_ids=(station,),
        product_ids=(str(product),),
    )
    try:
        if isinstance(payload.source_coordinates.value, AtEhydInfoCoordinates):
            return _parse_info_prerequisite(payload, station, product, window, retrieved, scope)
        if isinstance(product_coords, AtEhydOwfCoordinates):
            return _parse_owf_csv(payload, station, product, product_coords, window, retrieved, scope)
        return _parse_pegel_json(payload, station, product, product_coords, window, retrieved, scope)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "failed"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=retrieved,
        )
        issue = Issue(
            severity="error",
            code="source.unsupported_structure",
            message=reason,
            details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
            provider_id=_PROVIDER_ID,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,), (issue,))


def _validated_product_coordinates(
    payload_coords: object,
    product: ProductId,
    provider_config: ProviderConfig,
) -> AtEhydOwfCoordinates | AtEhydPegelCoordinates:
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"at_ehyd product is absent from provider config: {product}") from error

    if isinstance(payload_coords, AtEhydInfoCoordinates):
        if not isinstance(configured, AtEhydOwfCoordinates):
            raise FatalContractError("at_ehyd Messstellen/info payload must target an owf product")
        return configured
    if isinstance(payload_coords, AtEhydOwfCoordinates):
        if payload_coords != configured:
            raise FatalContractError("at_ehyd owf payload coordinates contradict configured product")
        return payload_coords
    if isinstance(payload_coords, AtEhydPegelCoordinates):
        if payload_coords != configured:
            raise FatalContractError("at_ehyd Pegel Aktuell payload coordinates contradict configured product")
        return payload_coords
    if isinstance(payload_coords, AtEhydPegelEndpointCoordinates):
        if not isinstance(configured, AtEhydPegelCoordinates) or payload_coords.subsystem != configured.subsystem:
            raise FatalContractError("at_ehyd Pegel Aktuell endpoint payload contradicts configured subsystem")
        return configured
    raise FatalContractError(f"at_ehyd payload has unsupported coordinate type: {type(payload_coords)!r}")


def _parse_info_prerequisite(
    payload: Payload,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    file_map = resolve_messstellen_info_files(payload.content, station)
    if product in file_map:
        # Valid prerequisite lookup; the child CSV payload or FailedSourceRequest owns this pair.
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())

    evidence = f"source-call:{payload.acquisition_id}"
    reason = f"eHYD Messstellen/info lists no owf file for station {station} product {product}"
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, str(product), "info-no-match-inventory"),
        scope=scope,
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access="messstellen_info",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
    )
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "info-no-match"),
        series_id=None,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.NO_MATCH,
        reason=reason,
        retrieved_at=retrieved,
    )
    issue = Issue(
        severity="warning",
        code="source.no_match",
        message=reason,
        details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (outcome,), (issue,))


def _parse_owf_csv(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: AtEhydOwfCoordinates,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    if payload.content == b"":
        raise UnsupportedSourceStructureError(f"eHYD owf CSV response for {station} {product} is empty (0 bytes)")

    try:
        header = parse_owf_header_facts(payload.content)
    except FatalContractError as error:
        raise UnsupportedSourceStructureError(str(error)) from error

    if header.hzbnr != station:
        raise UnsupportedSourceStructureError(
            f"eHYD owf CSV HZB-Nummer {header.hzbnr!r} contradicts requested station {station!r}"
        )

    evidence = f"source-call:{payload.acquisition_id}"
    exp_param, _, exp_kind, exp_stat, exp_period, _ = _OWF_ROUTE_SPECS[coords.ftyp]
    _, exp_unit = IN_SCOPE_OWF_FTYPES[coords.ftyp]

    if header.unit is None:
        definition = _reused_series(
            source_series(
                station,
                "owf",
                coords.ftyp,
                units=(None,),
                origin="response",
                evidence=_OWF_ENDPOINT_EVIDENCE,
            ),
            payload.known_series,
        )
        return _unsupported_series_result(
            payload,
            definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=coords.ftyp,
            reason="Source unit is not established in eHYD owf CSV header",
        )

    descriptor = header.descriptor
    assert descriptor is not None
    try:
        descriptor_stat = descriptor.canonical_statistic
    except FatalContractError as error:
        raise UnsupportedSourceStructureError(str(error)) from error

    if descriptor.parameter != exp_param or descriptor.kind_code != exp_kind or descriptor_stat != exp_stat:
        raise UnsupportedSourceStructureError(
            f"eHYD Exportzeitreihe {descriptor.raw!r} contradicts requested series {coords.ftyp!r}"
        )
    if exp_kind == "I":
        if not header.has_interval_rule:
            raise UnsupportedSourceStructureError(f"eHYD interval series {coords.ftyp!r} lacks interval validity rule")
        if (descriptor.period_code, descriptor.period_step) != (exp_period, "1"):
            raise UnsupportedSourceStructureError(
                f"eHYD interval series {coords.ftyp!r} has unexpected period {descriptor.period_code},{descriptor.period_step}"
            )
    else:
        if header.has_interval_rule:
            raise UnsupportedSourceStructureError(
                f"eHYD instantaneous extrema {coords.ftyp!r} carries interval validity rule"
            )
        valid_extrema_period = (descriptor.period_code == "M" and descriptor.period_step in {"1", "0"}) or (
            descriptor.period_code == "T" and descriptor.period_step == "1"
        )
        if not valid_extrema_period:
            raise UnsupportedSourceStructureError(
                f"eHYD extrema series {coords.ftyp!r} has unexpected period {descriptor.period_code},{descriptor.period_step}"
            )

    if header.unit != exp_unit and header.unit in UNITS:
        raise UnsupportedSourceStructureError(
            f"eHYD owf unit {header.unit!r} contradicts expected unit {exp_unit!r} for {coords.ftyp!r}"
        )

    definition = _reused_series(
        source_series(
            station,
            "owf",
            coords.ftyp,
            units=(header.unit,),
            origin="response",
            descriptor=descriptor,
            evidence=_OWF_ENDPOINT_EVIDENCE,
        ),
        payload.known_series,
    )
    fact = definition.facts[0]
    if admission(fact).status != "supported":
        return _unsupported_series_result(
            payload,
            definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=coords.ftyp,
            reason=f"Source unit {header.unit!r} is not supported",
        )

    finite_bounds = _parse_owf_exportzeitraum(header.exportzeitraum_raw)
    t_end = finite_bounds[1] if finite_bounds is not None else None

    _, _, body_bytes = payload.content.partition(b"Werte:")
    try:
        body_text = body_bytes.decode("cp1252", errors="strict")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError("eHYD owf CSV observation body is not valid Windows-1252 text") from error

    non_empty = [line.strip() for line in body_text.splitlines() if line.strip()]
    if not non_empty:
        raise UnsupportedSourceStructureError("eHYD owf CSV lacks observation or Lücke lines after Werte:")

    numeric_rows: list[dict[str, object]] = []
    gap_labels: list[str] = []

    if len(non_empty) == 1 and _OWF_INVALID_BODY_RE.fullmatch(non_empty[0]) is not None:
        pass
    else:
        prev_ts: datetime | None = None
        prev_was_gap = False
        for index, raw_line in enumerate(non_empty):
            parts = raw_line.split(";")
            if len(parts) < 2 or any(cell.strip() for cell in parts[2:]):
                raise UnsupportedSourceStructureError(f"Malformed eHYD owf observation line {index}: {raw_line!r}")
            ts_label = parts[0].strip()
            if _OWF_TIMESTAMP_RE.fullmatch(ts_label) is None:
                raise UnsupportedSourceStructureError(
                    f"Malformed eHYD owf observation timestamp {ts_label!r} on line {index}"
                )
            try:
                timestamp = datetime.strptime(ts_label, "%d.%m.%Y %H:%M:%S")
            except ValueError as error:
                raise UnsupportedSourceStructureError(
                    f"Invalid eHYD owf calendar timestamp {ts_label!r} on line {index}"
                ) from error
            if prev_ts is not None and timestamp < prev_ts:
                raise UnsupportedSourceStructureError(
                    f"Out-of-order eHYD owf timestamp {ts_label!r} after {prev_ts.isoformat()}"
                )
            prev_ts = timestamp

            val_token = parts[1].strip()
            if val_token == OWF_MISSING_VALUE_TOKEN:
                is_closing_boundary = (
                    index == len(non_empty) - 1
                    and not prev_was_gap
                    and exp_kind == "I"
                    and (t_end is None or timestamp == t_end)
                )
                if not is_closing_boundary:
                    gap_labels.append(ts_label)
                prev_was_gap = True
                continue

            if _OWF_NUMERIC_RE.fullmatch(val_token) is None:
                raise UnsupportedSourceStructureError(
                    f"Malformed eHYD owf observation value {val_token!r} at {ts_label}"
                )
            value = float(val_token.replace(",", "."))
            if not isfinite(value):
                raise UnsupportedSourceStructureError(f"Non-finite eHYD owf observation value at {ts_label}")
            numeric_rows.append(
                {
                    "station_id": station,
                    "product_id": str(product),
                    "time": timestamp,
                    "value": value,
                    "time_zone": "unknown",
                    "series_id": definition.series_id,
                    "facts_id": fact.facts_id,
                    "source_unit": fact.source_unit.value,
                }
            )
            prev_was_gap = False

    issues: list[Issue] = []
    outcomes: list[RetrievalOutcome] = []

    covered_bounds: tuple[datetime, datetime] | None = None
    if finite_bounds is not None:
        t_start, raw_t_end = finite_bounds
        first_time = cast("datetime", numeric_rows[0]["time"]) if numeric_rows else None
        last_time = cast("datetime", numeric_rows[-1]["time"]) if numeric_rows else None
        cand_start = min(t_start, first_time) if first_time is not None else t_start
        cand_end = (
            raw_t_end if (last_time is not None and last_time >= raw_t_end) else raw_t_end - timedelta(microseconds=1)
        )
        if cand_start <= cand_end:
            covered_bounds = (cand_start, cand_end)

    if covered_bounds is not None:
        covered_start, covered_end = covered_bounds
        covered_window = SeriesWindow(start=covered_start, end=covered_end)
        positive_outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "interval"),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=covered_window,
            status=OutcomeStatus.SUCCESS if numeric_rows else OutcomeStatus.EMPTY,
            facts_ids=(fact.facts_id,),
            retrieved_at=retrieved,
            coverage="interval",
        )
        outcomes.append(positive_outcome)
        _append_disjoint_unresolved_bounds(
            outcomes,
            acquisition_id=payload.acquisition_id,
            series_id=definition.series_id,
            station=station,
            product=str(product),
            facts_id=fact.facts_id,
            window=window,
            active_start=covered_start,
            active_end=covered_end,
            retrieved_at=retrieved,
            pre_reason="Requested interval precedes published eHYD Exportzeitraum start",
            post_reason="Requested interval extends beyond published eHYD Exportzeitraum end",
        )
        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "owf-inventory"),
            scope=scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, (fact.facts_id,)),),
            completeness=InventoryCompleteness.COMPLETE,
            access=coords.ftyp,
            origin="response",
            acquired_at=retrieved,
            window=covered_window,
            evidence=(evidence,),
        )
        primary_outcome_id: str | None = positive_outcome.outcome_id
    else:
        if numeric_rows:
            active_start = cast("datetime", numeric_rows[0]["time"])
            active_end = cast("datetime", numeric_rows[-1]["time"])
            obs_keys = tuple(
                dict.fromkeys((fact.facts_id, cast("datetime", row["time"]), "unknown") for row in numeric_rows)
            )
            obs_outcome = RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "observations"),
                series_id=definition.series_id,
                station_id=station,
                product_id=str(product),
                window=SeriesWindow(start=active_start, end=active_end),
                status=OutcomeStatus.SUCCESS,
                facts_ids=(fact.facts_id,),
                retrieved_at=retrieved,
                coverage="observations",
                observation_keys=obs_keys,
            )
            outcomes.append(obs_outcome)
            _append_disjoint_unresolved_bounds(
                outcomes,
                acquisition_id=payload.acquisition_id,
                series_id=definition.series_id,
                station=station,
                product=str(product),
                facts_id=fact.facts_id,
                window=window,
                active_start=active_start,
                active_end=active_end,
                retrieved_at=retrieved,
                pre_reason="Open eHYD Exportzeitraum does not establish coverage before the first observation",
                post_reason="Open eHYD Exportzeitraum does not establish coverage after the last observation",
            )
            primary_outcome_id = obs_outcome.outcome_id
        else:
            unresolved_outcome = RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "open-unresolved"),
                series_id=definition.series_id,
                station_id=station,
                product_id=str(product),
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                facts_ids=(fact.facts_id,),
                reason="Open eHYD Exportzeitraum without numeric rows does not establish empty interval coverage",
                retrieved_at=retrieved,
            )
            outcomes.append(unresolved_outcome)
            primary_outcome_id = unresolved_outcome.outcome_id
        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "owf-open-inventory"),
            scope=scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, (fact.facts_id,)),),
            completeness=InventoryCompleteness.INCOMPLETE,
            access=coords.ftyp,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason="Open eHYD Exportzeitraum bounds do not establish bounded interval coverage",
        )

    if gap_labels:
        issues.append(
            Issue(
                severity="info",
                code="source.gap_marker",
                message=f"eHYD owf series {station} {product} contains {len(gap_labels)} Lücke gap transition marker(s)",
                details={
                    "station_id": station,
                    "product_id": str(product),
                    "series_id": definition.series_id,
                    "facts_id": fact.facts_id,
                    "count": len(gap_labels),
                    "first_source_label": gap_labels[0],
                    "last_source_label": gap_labels[-1],
                    **({"outcome_id": primary_outcome_id} if primary_outcome_id is not None else {}),
                },
                provider_id=_PROVIDER_ID,
            )
        )

    return ParsedSeries(
        pl.DataFrame(numeric_rows, schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        tuple(outcomes),
        tuple(issues),
    )


def _parse_pegel_json(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: AtEhydPegelCoordinates,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    if payload.content == b"":
        reason = "Empty HTTP 200 Pegel Aktuell response establishes no concrete source-series identity"
        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, station, str(product), "empty-200-inventory"),
            scope=scope,
            members=(),
            completeness=InventoryCompleteness.INCOMPLETE,
            access=coords.subsystem,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason=reason,
        )
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "empty-200"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.UNRESOLVED,
            reason=reason,
            retrieved_at=retrieved,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (outcome,))

    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError(f"eHYD {coords.subsystem} response is not valid JSON") from error
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError(f"eHYD {coords.subsystem} response must be a JSON object")

    if (
        coords.subsystem == "pegel_longterm"
        and set(document) == _EMPTY_PEGEL_LONGTERM_KEYS
        and all(value == [] for value in document.values())
    ):
        reason = "Empty pegelLongterm JSON skeleton establishes no concrete source-series identity"
        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, station, str(product), "empty-skeleton-inventory"),
            scope=scope,
            members=(),
            completeness=InventoryCompleteness.INCOMPLETE,
            access=coords.subsystem,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason=reason,
        )
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "empty-skeleton"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.UNRESOLVED,
            reason=reason,
            retrieved_at=retrieved,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (outcome,))

    if coords.subsystem == "pegel_bgis":
        raw_hzb = document.get("hzbnr")
        if type(raw_hzb) not in (int, str) or str(raw_hzb).strip() != station:
            raise UnsupportedSourceStructureError(
                f"eHYD pegelBgis hzbnr {raw_hzb!r} contradicts requested station {station!r}"
            )

    observed_param = document.get("parameter")
    if observed_param not in ("Abfluss", "Wasserstand"):
        raise UnsupportedSourceStructureError(
            f"eHYD {coords.subsystem} response lacks a supported parameter field: {observed_param!r}"
        )
    if observed_param != coords.parameter:
        reason = f"eHYD {coords.subsystem} endpoint publishes parameter {observed_param!r}, not {coords.parameter!r}"
        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, station, str(product), "param-no-match-inventory"),
            scope=scope,
            members=(),
            completeness=InventoryCompleteness.INCOMPLETE,
            access=coords.subsystem,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason=reason,
        )
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "param-no-match"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.NO_MATCH,
            reason=reason,
            retrieved_at=retrieved,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (outcome,))

    raw_unit = document.get("einheit")
    if not isinstance(raw_unit, str):
        raise UnsupportedSourceStructureError(f"eHYD {coords.subsystem} response lacks a string einheit field")
    unit = raw_unit.strip() or None
    expected_unit = "m³/s" if coords.parameter == "Abfluss" else "cm"
    if unit is not None and unit != expected_unit and unit in UNITS and UNITS[unit] != UNITS[expected_unit]:
        raise UnsupportedSourceStructureError(
            f"eHYD {coords.subsystem} unit {unit!r} contradicts parameter {coords.parameter!r}"
        )

    definition = _reused_series(
        source_series(
            station,
            coords.subsystem,
            coords.parameter,
            units=(unit,),
            origin="response",
            evidence=_PEGEL_ENDPOINT_EVIDENCE[coords.subsystem],
        ),
        payload.known_series,
    )
    fact = definition.facts[0]
    if admission(fact).status != "supported":
        reason = (
            "Source unit is not established in Pegel Aktuell response"
            if unit is None
            else f"Source unit {unit!r} is not supported"
        )
        return _unsupported_series_result(
            payload,
            definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=coords.subsystem,
            reason=reason,
        )

    if coords.subsystem == "pegel_bgis":
        return _parse_pegel_bgis_rows(payload, document, definition, fact, station, product, window, retrieved, scope)
    return _parse_pegel_longterm_rows(payload, document, definition, fact, station, product, window, retrieved, scope)


def _parse_pegel_bgis_rows(
    payload: Payload,
    document: dict[str, object],
    definition: SourceSeries,
    fact: PhysicalFacts,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    val_count = document.get("valCount")
    categories = document.get("categories")
    data = document.get("data")

    if val_count == 0 and categories in (None, []) and data in (None, []):
        return _unresolved_telemetry_result(
            payload,
            definition,
            fact,
            station,
            product,
            window,
            retrieved,
            scope,
            access="pegel_bgis",
            reason="Empty rolling pegelBgis buffer does not establish retention or empty interval coverage",
        )

    if not isinstance(categories, list) or not isinstance(data, list) or len(categories) != len(data):
        raise UnsupportedSourceStructureError("eHYD pegelBgis categories and data must be equal-length arrays")
    if type(val_count) is int and val_count != len(data):
        raise UnsupportedSourceStructureError("eHYD pegelBgis valCount contradicts array length")
    if not categories:
        return _unresolved_telemetry_result(
            payload,
            definition,
            fact,
            station,
            product,
            window,
            retrieved,
            scope,
            access="pegel_bgis",
            reason="Empty rolling pegelBgis buffer does not establish retention or empty interval coverage",
        )

    rows: list[dict[str, object]] = []
    prev_ts: datetime | None = None
    for index, (raw_ts, raw_val) in enumerate(zip(categories, data, strict=True)):
        if not isinstance(raw_ts, str) or _PEGEL_BGIS_TIME_RE.fullmatch(raw_ts) is None:
            raise UnsupportedSourceStructureError(f"Malformed eHYD pegelBgis timestamp at index {index}: {raw_ts!r}")
        try:
            timestamp = datetime.strptime(raw_ts, "%Y-%m-%d %H:%M:%S")
        except ValueError as error:
            raise UnsupportedSourceStructureError(
                f"Invalid eHYD pegelBgis calendar timestamp at index {index}: {raw_ts!r}"
            ) from error
        if prev_ts is not None and timestamp < prev_ts:
            raise UnsupportedSourceStructureError("Out-of-order eHYD pegelBgis timestamp sequence")
        prev_ts = timestamp
        number = _validated_json_number(raw_val, context=f"pegelBgis[{index}]")
        rows.append(
            {
                "station_id": station,
                "product_id": str(product),
                "time": timestamp,
                "value": number,
                "time_zone": "+01:00",
                "series_id": definition.series_id,
                "facts_id": fact.facts_id,
                "source_unit": fact.source_unit.value,
            }
        )

    active_start = cast("datetime", rows[0]["time"])
    active_end = cast("datetime", rows[-1]["time"])
    obs_keys = tuple(dict.fromkeys((fact.facts_id, cast("datetime", row["time"]), "+01:00") for row in rows))
    outcomes: list[RetrievalOutcome] = [
        RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "bgis-observations"),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=SeriesWindow(start=active_start, end=active_end),
            status=OutcomeStatus.SUCCESS,
            facts_ids=(fact.facts_id,),
            retrieved_at=retrieved,
            coverage="observations",
            observation_keys=obs_keys,
        )
    ]
    _append_disjoint_unresolved_bounds(
        outcomes,
        acquisition_id=payload.acquisition_id,
        series_id=definition.series_id,
        station=station,
        product=str(product),
        facts_id=fact.facts_id,
        window=window,
        active_start=active_start,
        active_end=active_end,
        retrieved_at=retrieved,
        pre_reason="Requested interval precedes rolling pegelBgis retention start",
        post_reason="Requested interval extends beyond latest rolling pegelBgis timestamp",
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "bgis-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="pegel_bgis",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason="Rolling pegelBgis snapshot does not establish exhaustive historical coverage",
    )
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        tuple(outcomes),
    )


def _parse_pegel_longterm_rows(
    payload: Payload,
    document: dict[str, object],
    definition: SourceSeries,
    fact: PhysicalFacts,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    points_in_time = document.get("points_in_time")
    current_value = document.get("current_value")
    if (
        not isinstance(points_in_time, list)
        or not isinstance(current_value, list)
        or not points_in_time
        or len(points_in_time) != len(current_value)
    ):
        raise UnsupportedSourceStructureError(
            "eHYD pegelLongterm points_in_time and current_value must be non-empty equal-length arrays"
        )

    parsed_pairs: list[tuple[datetime, float | None]] = []
    last_non_null_index: int | None = None
    prev_ts: datetime | None = None
    for index, (raw_date, raw_val) in enumerate(zip(points_in_time, current_value, strict=True)):
        if not isinstance(raw_date, str) or _PEGEL_LONGTERM_DATE_RE.fullmatch(raw_date) is None:
            raise UnsupportedSourceStructureError(
                f"Malformed eHYD pegelLongterm points_in_time entry at index {index}: {raw_date!r}"
            )
        try:
            timestamp = datetime.strptime(raw_date, "%Y-%m-%d")
        except ValueError as error:
            raise UnsupportedSourceStructureError(
                f"Invalid eHYD pegelLongterm calendar date at index {index}: {raw_date!r}"
            ) from error
        if prev_ts is not None and timestamp <= prev_ts:
            raise UnsupportedSourceStructureError("Non-increasing eHYD pegelLongterm points_in_time sequence")
        prev_ts = timestamp
        number = _validated_json_number(raw_val, context=f"pegelLongterm[{index}]")
        if number is not None:
            last_non_null_index = index
        parsed_pairs.append((timestamp, number))

    if last_non_null_index is None:
        return _unresolved_telemetry_result(
            payload,
            definition,
            fact,
            station,
            product,
            window,
            retrieved,
            scope,
            access="pegel_longterm",
            reason="All-null current_value telemetry series does not establish empty interval coverage",
        )

    active_pairs = parsed_pairs[: last_non_null_index + 1]
    rows = [
        {
            "station_id": station,
            "product_id": str(product),
            "time": timestamp,
            "value": number,
            "time_zone": "unknown",
            "series_id": definition.series_id,
            "facts_id": fact.facts_id,
            "source_unit": fact.source_unit.value,
        }
        for timestamp, number in active_pairs
    ]
    active_start = active_pairs[0][0]
    active_end = active_pairs[-1][0] + timedelta(days=1) - timedelta(microseconds=1)
    obs_keys = tuple(dict.fromkeys((fact.facts_id, timestamp, "unknown") for timestamp, _ in active_pairs))
    outcomes: list[RetrievalOutcome] = [
        RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "longterm-observations"),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=SeriesWindow(start=active_start, end=active_end),
            status=OutcomeStatus.SUCCESS,
            facts_ids=(fact.facts_id,),
            retrieved_at=retrieved,
            coverage="observations",
            observation_keys=obs_keys,
        )
    ]
    _append_disjoint_unresolved_bounds(
        outcomes,
        acquisition_id=payload.acquisition_id,
        series_id=definition.series_id,
        station=station,
        product=str(product),
        facts_id=fact.facts_id,
        window=window,
        active_start=active_start,
        active_end=active_end,
        retrieved_at=retrieved,
        pre_reason="Requested interval precedes current-year pegelLongterm start",
        post_reason="Requested interval extends beyond latest published pegelLongterm date",
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "longterm-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="pegel_longterm",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason="Current-year pegelLongterm telemetry snapshot does not establish exhaustive historical coverage",
    )
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        tuple(outcomes),
    )


def _append_disjoint_unresolved_bounds(
    outcomes: list[RetrievalOutcome],
    *,
    acquisition_id: str,
    series_id: str,
    station: str,
    product: str,
    facts_id: str,
    window: SeriesWindow,
    active_start: datetime,
    active_end: datetime,
    retrieved_at: datetime | None,
    pre_reason: str,
    post_reason: str,
) -> None:
    if window.start < active_start:
        pre_end = min(window.end, active_start - timedelta(microseconds=1))
        if window.start <= pre_end:
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(acquisition_id, series_id, facts_id, "pre"),
                    series_id=series_id,
                    station_id=station,
                    product_id=product,
                    window=SeriesWindow(start=window.start, end=pre_end),
                    status=OutcomeStatus.UNRESOLVED,
                    facts_ids=(facts_id,),
                    reason=pre_reason,
                    retrieved_at=retrieved_at,
                )
            )
    if window.end > active_end:
        post_start = max(window.start, active_end + timedelta(microseconds=1))
        if post_start <= window.end:
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(acquisition_id, series_id, facts_id, "post"),
                    series_id=series_id,
                    station_id=station,
                    product_id=product,
                    window=SeriesWindow(start=post_start, end=window.end),
                    status=OutcomeStatus.UNRESOLVED,
                    facts_ids=(facts_id,),
                    reason=post_reason,
                    retrieved_at=retrieved_at,
                )
            )


def _validated_json_number(value: object, *, context: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise UnsupportedSourceStructureError(f"eHYD {context} value must be numeric or null")
    try:
        number = float(cast("int | float", value))
    except OverflowError as error:
        raise UnsupportedSourceStructureError(f"eHYD {context} value overflows float64") from error
    if not isfinite(number):
        raise UnsupportedSourceStructureError(f"eHYD {context} value must be finite")
    return number


def _parse_owf_exportzeitraum(raw: str | None) -> tuple[datetime, datetime] | None:
    if raw is None or not raw.strip():
        raise UnsupportedSourceStructureError("eHYD owf CSV lacks an Exportzeitraum header line")
    cleaned = raw.strip()
    match = _EZ_BRACKET_RE.fullmatch(cleaned) or _EZ_BIS_RE.fullmatch(cleaned)
    if match is not None:
        start = _parse_header_timestamp(match.group(1))
        end = _parse_header_timestamp(match.group(2))
        if start > end:
            raise UnsupportedSourceStructureError(f"Ordered Exportzeitraum bounds violated: {cleaned!r}")
        return start, end
    if any(token in cleaned for token in ("Datenbeginn", "+-Infty", "Invalid")):
        return None
    raise UnsupportedSourceStructureError(f"Malformed eHYD Exportzeitraum header: {cleaned!r}")


def _parse_header_timestamp(label: str) -> datetime:
    fmt = "%d.%m.%Y %H:%M:%S" if len(label) == 19 else "%d.%m.%Y %H:%M"
    try:
        return datetime.strptime(label, fmt)
    except ValueError as error:
        raise UnsupportedSourceStructureError(f"Invalid eHYD Exportzeitraum timestamp {label!r}") from error


def _reused_series(definition: SourceSeries, known_series: tuple[SourceSeries, ...]) -> SourceSeries:
    candidate = next((item for item in known_series if item.series_id == definition.series_id), None)
    if candidate is None:
        return definition
    retained = {_fact_signature(fact): fact for fact in candidate.facts}
    return definition.model_copy(
        update={
            "identity": candidate.identity,
            "facts": tuple(retained.get(_fact_signature(fact), fact) for fact in definition.facts),
        }
    )


def _fact_signature(fact: PhysicalFacts) -> tuple[object, ...]:
    return (
        fact.quantity.value,
        fact.source_unit.value,
        fact.normalized_unit,
        fact.frequency.value,
        fact.statistic.value,
        fact.temporal_support.value,
        fact.day_definition.value,
        fact.timestamp_anchor.value,
        fact.time_zone.value,
        fact.vertical_reference.value,
        fact.vertical_datum.value,
        fact.clipping_axis,
        fact.label_time,
    )


def _unsupported_series_result(
    payload: Payload,
    definition: SourceSeries,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    *,
    access: str,
    reason: str,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    fact = definition.facts[0]
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "unsupported"),
        series_id=definition.series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.UNSUPPORTED,
        facts_ids=(fact.facts_id,),
        reason=reason,
        retrieved_at=retrieved,
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "unsupported-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason=reason,
    )
    issue = Issue(
        severity="warning",
        code="source.unsupported_series",
        message=reason,
        details={
            "station_id": station,
            "product_id": str(product),
            "series_id": definition.series_id,
            "outcome_id": outcome.outcome_id,
        },
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        (outcome,),
        (issue,),
    )


def _unresolved_telemetry_result(
    payload: Payload,
    definition: SourceSeries,
    fact: PhysicalFacts,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    *,
    access: str,
    reason: str,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "unresolved"),
        series_id=definition.series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.UNRESOLVED,
        facts_ids=(fact.facts_id,),
        reason=reason,
        retrieved_at=retrieved,
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "unresolved-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason=reason,
    )
    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        (outcome,),
    )
