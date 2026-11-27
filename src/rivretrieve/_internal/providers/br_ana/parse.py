"""ANA parse : Payload × ProviderConfig → WithIssues[Rows] (native source variants, no quality policy).

Contributed by: Thiago von Däniken
"""

import hashlib
import json
import re
from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, narrow_payload_for_pair
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.br_ana.annotations import (
    BR_ANA_DAILY_COTAS_SCHEMA,
    BR_ANA_DAILY_VAZAO_SCHEMA,
    BR_ANA_TELEMETRY_COTA_SCHEMA,
    BR_ANA_TELEMETRY_VAZAO_SCHEMA,
)
from rivretrieve._internal.providers.br_ana.config import (
    BrAnaDailySourceCoordinates,
    BrAnaSharedEndpointCoordinates,
    BrAnaSourceCoordinates,
)
from rivretrieve._internal.providers.br_ana.issue_codes import BrAnaObservationIssueCodes
from rivretrieve._internal.providers.br_ana.series import _DAILY_EVIDENCE, _TELEMETRY_EVIDENCE, describe_series
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    ObservationAnnotationTable,
    filter_native_with_annotations_by_expr,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)

_PROVIDER = ProviderId("br_ana")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?")
_NUMBER = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")


class SourceStructureError(ValueError):
    """A publisher series cannot be decoded without unsupported interpretation."""


@dataclass(frozen=True, slots=True)
class _DecodedObservations:
    rows: Rows
    issues: tuple[Issue, ...]
    annotations: tuple[dict[str, str | None], ...]


def _telemetry_rows(
    observations: list[dict[str, object]],
    station: str,
    product: ProductId,
    coordinates: BrAnaSourceCoordinates,
) -> _DecodedObservations:
    entries: list[tuple[dict[str, object], dict[str, str | None]]] = []
    status_field = f"{coordinates.field}_Status"
    for index, observation in enumerate(observations):
        if observation.get("codigoestacao") != station:
            raise SourceStructureError(f"ANA observation {index} station differs from the requested station")
        label = _time(observation.get("Data_Hora_Medicao"), index)
        if coordinates.field not in observation or status_field not in observation:
            raise SourceStructureError(f"ANA observation {index} is missing an adopted value or status field")
        status = observation[status_field]
        if status is not None and not isinstance(status, str):
            raise SourceStructureError(f"ANA observation {index} adopted status must be a source string or null")
        entries.append(
            (
                {
                    "station_id": station,
                    "product_id": product,
                    "time": label,
                    "value": _value(observation[coordinates.field], index),
                    "time_zone": "unknown",
                },
                {status_field: status},
            )
        )
    # Unordered source arrays are not chronology. Retain duplicate multiplicity and
    # differing values: neither the status nor the update label authorizes selection.
    entries.sort(key=lambda item: cast(datetime, item[0]["time"]))
    frame = pl.DataFrame(
        [row for row, _ in entries],
        schema={
            key: value
            for key, value in RowsSchema.polars_schema.items()
            if key not in {"series_id", "facts_id", "source_unit"}
        },
    )
    issues: tuple[Issue, ...] = ()
    if not observations:
        issues = (
            Issue(
                severity="warning",
                code=BrAnaObservationIssueCodes.MISSING_DATA,
                message="ANA response contains no adopted telemetry observations",
                details={"station_id": station, "product_id": product},
                provider_id=_PROVIDER,
            ),
        )
    return _DecodedObservations(frame, issues, tuple(annotation for _, annotation in entries))


def _daily_rows(
    observations: list[dict[str, object]],
    station: str,
    product: ProductId,
    coordinates: BrAnaDailySourceCoordinates,
) -> _DecodedObservations:
    """Decode monthly source day slots for one exact mean/consistency variant."""
    entries: list[tuple[dict[str, object], dict[str, str | None]]] = []
    consistency_field = "nivelconsistencia" if coordinates.field_prefix == "Cota" else "Nivel_Consistencia"
    method_field = "Tipo_Medicao_Cotas" if coordinates.field_prefix == "Cota" else "Metodo_Obtencao_Vazoes"
    for index, observation in enumerate(observations):
        if observation.get("codigoestacao") != station:
            raise SourceStructureError(f"ANA observation {index} station differs from the requested station")
        mean = observation.get("Mediadiaria")
        consistency = observation.get(consistency_field)
        if mean not in ("0", "1") or consistency not in ("1", "2"):
            raise SourceStructureError(f"ANA observation {index} has an invalid mean or consistency code")
        # Flag0 headers legitimately carry07:00/17:00. They are outside this
        # mean product, not malformed daily means and never averaging inputs.
        if mean != "1" or consistency != coordinates.consistency:
            continue
        header = _time(observation.get("Data_Hora_Dado"), index)
        if header.day != 1 or header != datetime(header.year, header.month, 1):
            raise SourceStructureError(f"ANA observation {index} daily mean requires a midnight first-of-month header")
        if method_field not in observation:
            raise SourceStructureError(f"ANA observation {index} is missing daily method field {method_field}")
        method_value = observation[method_field]
        if method_value is not None and not isinstance(method_value, str):
            raise SourceStructureError(f"ANA observation {index} daily method field must be a source string or null")
        last_day = monthrange(header.year, header.month)[1]
        for day in range(1, 32):
            field = f"{coordinates.field_prefix}_{day:02d}"
            status_field = f"{field}_Status"
            if field not in observation or status_field not in observation:
                raise SourceStructureError(f"ANA observation {index} is missing a daily value or status field")
            raw = observation[field]
            status = observation[status_field]
            if status is not None and not isinstance(status, str):
                raise SourceStructureError(f"ANA observation {index} daily status must be a source string or null")
            if day > last_day:
                # Hidro1.4 explicitly names status0 BRANCO. It is not a
                # numeric-value sentinel: a finite value outside the month fails.
                if raw not in (None, "") or status not in (None, "", "0"):
                    raise SourceStructureError(f"ANA observation {index} has a nonempty invalid calendar slot {field}")
                continue
            entries.append(
                (
                    {
                        "station_id": station,
                        "product_id": product,
                        "time": datetime(header.year, header.month, day),
                        "value": None if raw == "" else _value(raw, index),
                        "time_zone": "unknown",
                    },
                    {
                        f"{coordinates.field_prefix}_Status": status,
                        method_field: method_value,
                    },
                )
            )
    # Source duplicates are observations, not authorization to choose a winner.
    entries.sort(key=lambda item: cast(datetime, item[0]["time"]))
    frame = pl.DataFrame(
        [row for row, _ in entries],
        schema={
            key: value
            for key, value in RowsSchema.polars_schema.items()
            if key not in {"series_id", "facts_id", "source_unit"}
        },
    )
    issues: tuple[Issue, ...] = ()
    if not entries:
        issues = (
            Issue(
                severity="warning",
                code=BrAnaObservationIssueCodes.MISSING_DATA,
                message="ANA response contains no daily observations for the requested source variant",
                details={"station_id": station, "product_id": product},
                provider_id=_PROVIDER,
            ),
        )
    return _DecodedObservations(frame, issues, tuple(annotation for _, annotation in entries))


def _observations(content: bytes) -> list[dict[str, object]]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceStructureError("ANA response must be valid JSON") from error
    if (
        not isinstance(document, dict)
        or document.get("status") != "OK"
        or type(document.get("code")) is not int
        or document["code"] != 200
    ):
        raise SourceStructureError("ANA response must be a successful source envelope")
    items = document.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise SourceStructureError("ANA successful response items must be a list of observation objects")
    return cast("list[dict[str, object]]", items)


def _time(value: object, index: int) -> datetime:
    if not isinstance(value, str) or _TIME.fullmatch(value) is None:
        raise SourceStructureError(f"ANA observation {index} requires a native naive measurement timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise SourceStructureError(f"ANA observation {index} has an invalid measurement timestamp") from error


def _value(value: object, index: int) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str) or _NUMBER.fullmatch(value) is None:
        raise SourceStructureError(f"ANA observation {index} value must be a decimal string or null")
    result = float(value)
    if not isfinite(result):
        raise SourceStructureError(f"ANA observation {index} value must be finite")
    # No documented sentinel rule: finite source numbers remain numbers, including negative values.
    return result


def _validated_product_coordinates(
    payload_coordinates: object,
    product: ProductId,
    config: ProviderConfig,
) -> BrAnaSourceCoordinates | BrAnaDailySourceCoordinates:
    product_config = config.products.get(product)
    if product_config is None:
        raise FatalContractError("ANA payload coordinates differ from the requested source product")
    coordinates = product_config.coordinates.value
    if not isinstance(coordinates, (BrAnaSourceCoordinates, BrAnaDailySourceCoordinates)):
        raise FatalContractError("ANA payload coordinates differ from the requested source product")
    if isinstance(payload_coordinates, BrAnaSharedEndpointCoordinates):
        expected_endpoint = (
            coordinates.endpoint
            if isinstance(coordinates, BrAnaDailySourceCoordinates)
            else "HidroinfoanaSerieTelemetricaAdotada"
        )
        if payload_coordinates.endpoint != expected_endpoint:
            raise FatalContractError("ANA payload coordinates differ from the requested source product")
    elif payload_coordinates != coordinates:
        raise FatalContractError("ANA payload coordinates differ from the requested source product")
    return coordinates


def _payload_meta(payload: Payload) -> tuple[SeriesWindow, datetime | None, tuple[str, ...]]:
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    calls = tuple(item.attempt_id for item in payload.attempt_traces) or (payload.acquisition_id,)
    return window, retrieved, calls


def _build_annotation_bundle(
    annotated_rows: pl.DataFrame,
    annotations: tuple[dict[str, str | None], ...],
    native: BrAnaSourceCoordinates | BrAnaDailySourceCoordinates,
) -> AnnotationBundle:
    if isinstance(native, BrAnaDailySourceCoordinates):
        schema = BR_ANA_DAILY_COTAS_SCHEMA if native.field_prefix == "Cota" else BR_ANA_DAILY_VAZAO_SCHEMA
    else:
        schema = BR_ANA_TELEMETRY_COTA_SCHEMA if native.field == "Cota_Adotada" else BR_ANA_TELEMETRY_VAZAO_SCHEMA
    if len(annotations) != annotated_rows.height:
        raise FatalContractError("ANA parsed rows and observation annotations count mismatch")
    ann_frame = annotated_rows.select(
        "series_id", "facts_id", "station_id", "product_id", "time", "time_zone"
    ).with_columns(
        pl.lit(True).cast(pl.Boolean()).alias("measured"),
        *(
            pl.Series(field.name, [item[field.name] for item in annotations], dtype=pl.String())
            for field in schema.fields
        ),
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=ann_frame,
        measurement_indices=list(range(annotated_rows.height)),
    )
    return AnnotationBundle(observation_tables={schema.schema_id: ann_table})


def parse_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    config: ProviderConfig,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    """Decode one ANA response once and project per-pair ``ParsedSeries`` results."""
    if not pair_payloads:
        raise FatalContractError("ANA group parse requires at least one pair payload")
    stations = {station for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("ANA payload must identify a single station")
    station = next(iter(stations))

    coords_by_pair: dict[tuple[str, ProductId], BrAnaSourceCoordinates | BrAnaDailySourceCoordinates] = {}
    meta_by_pair: dict[tuple[str, ProductId], tuple[Payload, SeriesWindow, datetime | None, tuple[str, ...]]] = {}
    for key, pair_payload in pair_payloads.items():
        pair_station, product = key
        if pair_payload.station_products != ((pair_station, product),):
            raise FatalContractError("Pair payload station_products does not match its group key")
        coords_by_pair[key] = _validated_product_coordinates(payload.source_coordinates.value, product, config)
        window, retrieved, calls = _payload_meta(pair_payload)
        meta_by_pair[key] = (pair_payload, window, retrieved, calls)

    content_hash = hashlib.sha256(payload.content).hexdigest()
    try:
        observations = _observations(payload.content)
    except SourceStructureError as error:
        reason = str(error)
        failed_results: dict[tuple[str, ProductId], ParsedSeries] = {}
        for key, (pair_payload, window, retrieved, calls) in meta_by_pair.items():
            pair_station, product = key
            window_outcome = RetrievalOutcome(
                outcome_id=stable_id(
                    pair_payload.acquisition_id,
                    content_hash,
                    str(retrieved),
                    pair_station,
                    product,
                    reason,
                ),
                series_id=None,
                station_id=pair_station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNSUPPORTED,
                reason=reason,
                retrieved_at=retrieved,
                calls=calls,
            )
            issue = Issue(
                severity="warning",
                code="source.unsupported_response",
                message=reason,
                details={"station_id": pair_station, "product_id": product},
                provider_id=_PROVIDER,
            )
            failed_results[key] = ParsedSeries(
                pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (window_outcome,), (issue,)
            )
        return failed_results

    first_coords = next(iter(coords_by_pair.values()))
    if isinstance(first_coords, BrAnaDailySourceCoordinates):
        return _parse_daily_group(
            payload, meta_by_pair, coords_by_pair, observations, content_hash, station, first_coords
        )
    return _parse_telemetry_group(meta_by_pair, coords_by_pair, observations, content_hash)


def _parse_daily_group(
    payload: Payload,
    meta_by_pair: Mapping[tuple[str, ProductId], tuple[Payload, SeriesWindow, datetime | None, tuple[str, ...]]],
    coords_by_pair: Mapping[tuple[str, ProductId], BrAnaSourceCoordinates | BrAnaDailySourceCoordinates],
    observations: list[dict[str, object]],
    content_hash: str,
    station: str,
    first_coords: BrAnaDailySourceCoordinates,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    consistency_field = "nivelconsistencia" if first_coords.field_prefix == "Cota" else "Nivel_Consistencia"
    # Only source-published identities are observations; an unobserved sibling stays unknown.
    present = {
        row.get(consistency_field)
        for row in observations
        if row.get("Mediadiaria") == "1" and isinstance(row.get(consistency_field), str)
    }
    invalid = [
        row
        for row in observations
        if row.get("Mediadiaria") not in ("0", "1") or row.get(consistency_field) not in ("1", "2")
    ]
    selected: list[tuple[ProductId, BrAnaDailySourceCoordinates]] = []
    for consistency in ("1", "2"):
        if consistency not in present:
            continue
        native = replace(first_coords, consistency=consistency)
        canonical_product = ProductId(
            ("stage" if native.field_prefix == "Cota" else "discharge")
            + "_daily_mean_"
            + ("bruto" if consistency == "1" else "consistido")
        )
        selected.append((canonical_product, native))

    payload_window, payload_retrieved, payload_calls = _payload_meta(payload)
    shared_definitions: list[SourceSeries] = []
    frames: list[pl.DataFrame] = []
    part_bundles: list[AnnotationBundle] = []
    row_offsets: list[int] = []
    running_rows = 0
    shared_outcomes: list[RetrievalOutcome] = []
    shared_issues: list[Issue] = []

    for emitted_product, native in selected:
        definition = describe_series(station, emitted_product, native, origin="response")
        shared_definitions.append(definition)
        facts = definition.facts[0]
        try:
            decoded = _daily_rows(
                [
                    row
                    for row in observations
                    if row.get(consistency_field) == native.consistency and row.get("Mediadiaria") in ("0", "1")
                ],
                station,
                emitted_product,
                native,
            )
        except SourceStructureError as error:
            reason = str(error)
            shared_outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        payload.acquisition_id,
                        content_hash,
                        str(payload_retrieved),
                        definition.series_id,
                        reason,
                    ),
                    series_id=definition.series_id,
                    station_id=station,
                    product_id=emitted_product,
                    window=payload_window,
                    status=OutcomeStatus.UNSUPPORTED,
                    facts_ids=(facts.facts_id,),
                    reason=reason,
                    retrieved_at=payload_retrieved,
                    calls=payload_calls,
                )
            )
            shared_issues.append(
                Issue(
                    severity="warning",
                    code="source.unsupported_series",
                    message=reason,
                    details={"station_id": station, "product_id": emitted_product, "series_id": definition.series_id},
                    provider_id=_PROVIDER,
                )
            )
            continue
        annotated_rows = decoded.rows.with_columns(
            pl.lit(definition.series_id).alias("series_id"),
            pl.lit(facts.facts_id).alias("facts_id"),
            pl.lit(facts.source_unit.value).alias("source_unit"),
        )
        frames.append(annotated_rows)
        if not annotated_rows.is_empty():
            part_bundles.append(_build_annotation_bundle(annotated_rows, decoded.annotations, native))
            row_offsets.append(running_rows)
            running_rows += annotated_rows.height
        shared_issues.extend(decoded.issues)
        shared_outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(
                    payload.acquisition_id,
                    content_hash,
                    str(payload.origin.retrieved_at),
                    definition.series_id,
                    str(payload_window),
                    "response",
                ),
                series_id=definition.series_id,
                station_id=station,
                product_id=emitted_product,
                window=payload_window,
                status=OutcomeStatus.EMPTY if decoded.rows.is_empty() else OutcomeStatus.SUCCESS,
                facts_ids=(facts.facts_id,),
                retrieved_at=payload_retrieved,
                calls=payload_calls,
            )
        )
    del observations

    observed_ids = tuple(item.series_id for item in shared_definitions)
    shared_rows = (
        pl.concat(frames).select(list(RowsSchema.polars_schema))
        if frames
        else pl.DataFrame(schema=RowsSchema.polars_schema)
    )
    shared_bundle = (
        AnnotationBundle.merge_sorted(
            part_bundles,
            row_offsets=row_offsets,
            old_to_new={index: index for index in range(shared_rows.height)},
        )
        if part_bundles
        else AnnotationBundle.empty()
    )

    results: dict[tuple[str, ProductId], ParsedSeries] = {}
    for key, (pair_payload, window, retrieved, calls) in meta_by_pair.items():
        pair_station, product = key
        pair_coords = cast("BrAnaDailySourceCoordinates", coords_by_pair[key])
        definitions = list(shared_definitions)
        outcomes: list[RetrievalOutcome] = []
        issues: list[Issue] = []
        if invalid:
            invalid_reason = "ANA response contains rows with unestablished mean/consistency identity"
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        pair_payload.acquisition_id, content_hash, str(retrieved), pair_station, product, invalid_reason
                    ),
                    series_id=None,
                    station_id=pair_station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNSUPPORTED,
                    reason=invalid_reason,
                    retrieved_at=retrieved,
                    calls=calls,
                )
            )
            issues.append(
                Issue(
                    severity="warning",
                    code="source.unsupported_series",
                    message=invalid_reason,
                    details={"station_id": pair_station, "product_id": product, "unrepresentable_rows": len(invalid)},
                    provider_id=_PROVIDER,
                )
            )
        outcomes.extend(shared_outcomes)
        issues.extend(shared_issues)
        if pair_coords.consistency not in present:
            default_candidate = describe_series(pair_station, product, pair_coords, origin="mapping")
            candidate = next(
                (item for item in pair_payload.known_series if item.series_id == default_candidate.series_id),
                default_candidate,
            )
            definitions.append(candidate)
            unresolved_reason = (
                f"Requested ANA consistency {pair_coords.consistency} is not published in this response; "
                "availability remains unresolved"
            )
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        pair_payload.acquisition_id,
                        content_hash,
                        str(retrieved),
                        candidate.series_id,
                        unresolved_reason,
                    ),
                    series_id=candidate.series_id,
                    station_id=pair_station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNRESOLVED,
                    reason=unresolved_reason,
                    retrieved_at=retrieved,
                    calls=calls,
                )
            )
            issues.append(
                Issue(
                    severity="warning",
                    code="source.unresolved_inventory",
                    message=unresolved_reason,
                    details={"station_id": pair_station, "product_id": product, "series_id": candidate.series_id},
                    provider_id=_PROVIDER,
                )
            )
        scope = pair_payload.scope or SeriesScope(
            provider_ids=("br_ana",), station_ids=(pair_station,), product_ids=(product,)
        )
        if not definitions and not outcomes:
            empty_reason = (
                "No daily mean source identity is published in this response; sibling availability remains unresolved"
            )
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        pair_payload.acquisition_id,
                        content_hash,
                        str(pair_payload.origin.retrieved_at),
                        pair_station,
                        product,
                        str(window),
                        empty_reason,
                    ),
                    series_id=None,
                    station_id=pair_station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNRESOLVED,
                    reason=empty_reason,
                    retrieved_at=retrieved,
                    calls=calls,
                )
            )
            issues.append(
                Issue(
                    severity="warning",
                    code="source.unresolved_inventory",
                    message=empty_reason,
                    details={"station_id": pair_station, "product_id": product},
                    provider_id=_PROVIDER,
                )
            )
        inventory = InventorySnapshot(
            snapshot_id=stable_id(
                pair_payload.acquisition_id,
                content_hash,
                str(pair_payload.origin.retrieved_at),
                "br_ana",
                pair_station,
                product,
                str(retrieved),
                str(window),
            ),
            scope=scope,
            members=observed_ids,
            completeness=InventoryCompleteness.INCOMPLETE,
            access=pair_coords.endpoint,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(_DAILY_EVIDENCE,),
            reason="Scoped daily response does not establish unobserved consistency availability",
        )
        results[key] = ParsedSeries(
            shared_rows,
            tuple(definitions),
            (inventory,),
            tuple(outcomes),
            tuple(issues),
            annotations=shared_bundle,
        )
    return results


def _parse_telemetry_group(
    meta_by_pair: Mapping[tuple[str, ProductId], tuple[Payload, SeriesWindow, datetime | None, tuple[str, ...]]],
    coords_by_pair: Mapping[tuple[str, ProductId], BrAnaSourceCoordinates | BrAnaDailySourceCoordinates],
    observations: list[dict[str, object]],
    content_hash: str,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    results: dict[tuple[str, ProductId], ParsedSeries] = {}
    for key, (pair_payload, window, retrieved, calls) in meta_by_pair.items():
        station, product = key
        coordinates = cast("BrAnaSourceCoordinates", coords_by_pair[key])
        definition = describe_series(station, product, coordinates, origin="response")
        facts = definition.facts[0]
        scope = pair_payload.scope or SeriesScope(
            provider_ids=("br_ana",), station_ids=(station,), product_ids=(product,)
        )
        inventory = InventorySnapshot(
            snapshot_id=stable_id(
                pair_payload.acquisition_id,
                content_hash,
                str(pair_payload.origin.retrieved_at),
                "br_ana",
                station,
                product,
                str(retrieved),
                str(window),
            ),
            scope=scope,
            members=(definition.series_id,),
            completeness=InventoryCompleteness.INCOMPLETE,
            access="HidroinfoanaSerieTelemetricaAdotada",
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(_TELEMETRY_EVIDENCE,),
            reason=(
                "Adopted telemetry is supported; detailed Cota_Sensor, Cota_Manual and Cota_Display identities "
                "have unestablished quantity/unit mappings; inventory is incomplete"
            ),
        )
        try:
            decoded = _telemetry_rows(observations, station, product, coordinates)
        except SourceStructureError as error:
            reason = str(error)
            outcome = RetrievalOutcome(
                outcome_id=stable_id(
                    pair_payload.acquisition_id,
                    content_hash,
                    str(retrieved),
                    definition.series_id,
                    reason,
                ),
                series_id=definition.series_id,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNSUPPORTED,
                facts_ids=(facts.facts_id,),
                reason=reason,
                retrieved_at=retrieved,
                calls=calls,
            )
            issue = Issue(
                severity="warning",
                code="source.unsupported_series",
                message=reason,
                details={"station_id": station, "product_id": product, "series_id": definition.series_id},
                provider_id=_PROVIDER,
            )
            results[key] = ParsedSeries(
                pl.DataFrame(schema=RowsSchema.polars_schema),
                (definition,),
                (inventory,),
                (outcome,),
                (issue,),
                annotations=AnnotationBundle.empty(),
            )
            continue
        annotated_rows = decoded.rows.with_columns(
            pl.lit(definition.series_id).alias("series_id"),
            pl.lit(facts.facts_id).alias("facts_id"),
            pl.lit(facts.source_unit.value).alias("source_unit"),
        )
        bundle = (
            _build_annotation_bundle(annotated_rows, decoded.annotations, coordinates)
            if not annotated_rows.is_empty()
            else AnnotationBundle.empty()
        )
        outcome = RetrievalOutcome(
            outcome_id=stable_id(
                pair_payload.acquisition_id,
                content_hash,
                str(pair_payload.origin.retrieved_at),
                definition.series_id,
                str(window),
                "response",
            ),
            series_id=definition.series_id,
            station_id=station,
            product_id=product,
            window=window,
            status=OutcomeStatus.EMPTY if decoded.rows.is_empty() else OutcomeStatus.SUCCESS,
            facts_ids=(facts.facts_id,),
            retrieved_at=retrieved,
            calls=calls,
        )
        results[key] = ParsedSeries(
            annotated_rows.select(list(RowsSchema.polars_schema)),
            (definition,),
            (inventory,),
            (outcome,),
            decoded.issues,
            annotations=bundle,
        )
    del observations
    return results


def parse(payload: Payload, config: ProviderConfig) -> ParsedSeries:
    if not payload.station_products:
        raise FatalContractError("ANA payload requires at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("ANA payload must identify a single station")
    for _, product in payload.station_products:
        _validated_product_coordinates(payload.source_coordinates.value, product, config)
    if len(payload.station_products) == 1:
        pair = payload.station_products[0]
        return parse_group(payload, {pair: payload}, config)[pair]

    pair_payloads = {
        (station, product): narrow_payload_for_pair(payload, station, product)
        for station, product in payload.station_products
    }
    grouped = parse_group(payload, pair_payloads, config)

    frames: list[pl.DataFrame] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []
    outcomes: dict[str, RetrievalOutcome] = {}
    issues: list[Issue] = []
    annotation_bundles: list[AnnotationBundle] = []
    annotation_offsets: list[int] = []
    offset = 0
    for pair in payload.station_products:
        _, product = pair
        part = grouped[pair]
        part_rows, part_ann = filter_native_with_annotations_by_expr(
            part.rows,
            part.annotations,
            pl.col("product_id") == str(product),
        )
        if not part_ann.is_empty:
            annotation_bundles.append(part_ann)
            annotation_offsets.append(offset)
        if not part_rows.is_empty():
            frames.append(part_rows)
            offset += part_rows.height
        for item in part.series:
            definitions.setdefault(item.series_id, item)
        inventories.extend(part.inventories)
        for outcome in part.outcomes:
            outcomes.setdefault(outcome.outcome_id, outcome)
        for issue in part.issues:
            if issue not in issues:
                issues.append(issue)
    rows = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
    bundle = (
        AnnotationBundle.merge_sorted(
            annotation_bundles,
            row_offsets=annotation_offsets,
            old_to_new={index: index for index in range(rows.height)},
        )
        if annotation_bundles
        else AnnotationBundle.empty()
    )
    return ParsedSeries(
        rows.select(list(RowsSchema.polars_schema)),
        tuple(definitions.values()),
        tuple(inventories),
        tuple(outcomes.values()),
        tuple(issues),
        annotations=bundle,
    )
