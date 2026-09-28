"""Decode Swiss publisher fields without selecting or merging alternatives.

Contributed by: Nicolas Lazaro
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from math import isfinite

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ch_foen.config import ChFoenSourceCoordinates
from rivretrieve._internal.providers.ch_foen.series import field_candidates, field_series
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


class SourceStructureError(ValueError):
    """A publisher field cannot be represented without guessing."""


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    for _, product in payload.station_products:
        if product not in provider_config.products or not isinstance(
            provider_config.products[product].coordinates.value, ChFoenSourceCoordinates
        ):
            raise FatalContractError("ch_foen payload has undeclared product coordinates")
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    rows: list[dict[str, object]] = []
    series: list[SourceSeries] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    source_time = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    try:
        fields = _decode(payload.content)
    except SourceStructureError as exc:
        fields = {}
        for station, product in payload.station_products:
            reason = str(exc)
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        hashlib.sha256(payload.content).hexdigest(),
                        str(payload.origin.retrieved_at),
                        station,
                        product,
                        reason,
                    ),
                    series_id=None,
                    station_id=station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNSUPPORTED,
                    reason=reason,
                    retrieved_at=source_time,
                )
            )
            issues.append(_issue(station, product, reason))
    for station, product in dict.fromkeys(payload.station_products):
        candidates = field_candidates((station,), (product,), provider_config)
        present = [item for item in candidates if (station, item.identity.published_id) in fields]
        for candidate in present:
            field = candidate.identity.published_id
            assert field is not None
            definition = field_series(station, field, origin="response")
            facts = definition.facts[0]
            series.append(definition)
            try:
                entries = fields[(station, field)]
                if isinstance(entries, SourceStructureError):
                    raise entries
                native_rows = []
                for label, raw_value in entries:
                    native_rows.append(
                        {
                            "station_id": station,
                            "product_id": product,
                            "time": label,
                            "value": _number_or_none(raw_value),
                            "time_zone": "+00:00",
                            "series_id": definition.series_id,
                            "facts_id": facts.facts_id,
                            "source_unit": facts.source_unit.value,
                        }
                    )
                rows.extend(native_rows)
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            hashlib.sha256(payload.content).hexdigest(),
                            str(payload.origin.retrieved_at),
                            definition.series_id,
                            str(window),
                            "success",
                        ),
                        series_id=definition.series_id,
                        station_id=station,
                        product_id=product,
                        window=window,
                        status=OutcomeStatus.SUCCESS if native_rows else OutcomeStatus.EMPTY,
                        facts_ids=(facts.facts_id,),
                        retrieved_at=source_time,
                    )
                )
            except SourceStructureError as exc:
                reason = str(exc)
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            hashlib.sha256(payload.content).hexdigest(),
                            str(payload.origin.retrieved_at),
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
                        retrieved_at=source_time,
                    )
                )
                issues.append(_issue(station, product, reason, definition.series_id))
        for candidate in candidates:
            if payload.scope is not None and not payload.scope.matches(candidate):
                continue
            if (station, candidate.identity.published_id) in fields:
                continue
            if any(o.station_id == station and o.product_id == product and o.series_id is None for o in outcomes):
                continue
            series.append(candidate)
            reason = f"Requested Swiss field {candidate.identity.published_id!r} is not published in this response; availability remains unresolved"
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        hashlib.sha256(payload.content).hexdigest(), str(source_time), candidate.series_id, reason
                    ),
                    series_id=candidate.series_id,
                    station_id=station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNRESOLVED,
                    reason=reason,
                    retrieved_at=source_time,
                )
            )
            issues.append(_issue(station, product, reason, candidate.series_id))
        if not present and not any(o.station_id == station and o.product_id == product for o in outcomes):
            reason = (
                "Response does not establish a matching field identity; omitted fields are not successful empty series"
            )
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        hashlib.sha256(payload.content).hexdigest(),
                        str(payload.origin.retrieved_at),
                        station,
                        product,
                        str(window),
                        reason,
                    ),
                    series_id=None,
                    station_id=station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.UNRESOLVED,
                    reason=reason,
                    retrieved_at=source_time,
                )
            )
            issues.append(_issue(station, product, reason))
    scope = payload.scope or SeriesScope(
        provider_ids=("ch_foen",),
        station_ids=tuple(dict.fromkeys(s for s, _ in payload.station_products)),
        product_ids=tuple(dict.fromkeys(p for _, p in payload.station_products)),
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(
            hashlib.sha256(payload.content).hexdigest(),
            str(payload.origin.retrieved_at),
            "ch_foen",
            str(window),
            str(source_time),
            *(s.series_id for s in series),
        ),
        scope=scope,
        members=tuple(s.series_id for s in series if s.identity.origin == "response"),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="Existenz supported hydro fields",
        origin="response",
        acquired_at=source_time,
        window=window,
        evidence=("Exact REST or Flux response fields",),
        reason="Response fields establish only this request window; omitted field identities and historical alternatives remain unresolved",
    )
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema), tuple(series), (inventory,), tuple(outcomes), tuple(issues)
    )


def _decode(content: bytes) -> dict[tuple[str, str], list[tuple[datetime, object]] | SourceStructureError]:
    result: dict[tuple[str, str], list[tuple[datetime, object]] | SourceStructureError] = {}
    if content.lstrip().startswith(b"{"):
        try:
            document = json.loads(content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceStructureError("Swiss REST response is not valid JSON") from exc
        if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
            raise SourceStructureError("Swiss REST response lacks payload object")
        body = document["payload"]
        timestamps = body.get("timestamp")
        if not isinstance(timestamps, list):
            raise SourceStructureError("Swiss REST response lacks timestamp array")
        labels = []
        for timestamp in timestamps:
            if type(timestamp) is not int:
                raise SourceStructureError("Swiss REST timestamp is not integer Unix seconds")
            try:
                labels.append(_wall_clock(datetime.fromtimestamp(timestamp, UTC)))
            except (OverflowError, ValueError, OSError) as exc:
                raise SourceStructureError("Swiss REST timestamp is unrepresentable") from exc
        for key, values in body.items():
            if "|" not in key:
                continue
            station, field = key.split("|", 1)
            if not isinstance(values, list) or len(values) != len(labels):
                result[(station, field)] = SourceStructureError("Swiss REST field values do not align with timestamps")
            else:
                result[(station, field)] = list(zip(labels, values, strict=True))
    else:
        try:
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
            records = list(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise SourceStructureError("Swiss Flux response is not valid CSV") from exc
        if reader.fieldnames is None or not {"_time", "_value", "_field", "_measurement", "loc"} <= set(
            reader.fieldnames
        ):
            raise SourceStructureError("Swiss Flux response lacks required columns")
        for row in records:
            try:
                instant = datetime.fromisoformat(row["_time"])
            except (TypeError, ValueError) as exc:
                raise SourceStructureError("Swiss Flux timestamp is not RFC3339") from exc
            if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
                raise SourceStructureError("Swiss Flux timestamp is not explicit UTC")
            if row["_measurement"] != "hydro":
                raise SourceStructureError("Swiss Flux measurement is not hydro")
            values = result.setdefault((row["loc"], row["_field"]), [])
            if isinstance(values, SourceStructureError):
                continue
            values.append((_wall_clock(instant), row["_value"]))
    return result


def _number_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise SourceStructureError("Swiss observation value is not numeric or null")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise SourceStructureError("Swiss observation value is not representable as a finite number") from exc
    if not isfinite(number):
        raise SourceStructureError("Swiss observation value is not finite")
    return number


def _issue(station: str, product: str, reason: str, series_id: str | None = None) -> Issue:
    return Issue(
        severity="warning",
        code="source.unsupported_series",
        message=reason,
        details={"station_id": station, "product_id": product, "series_id": series_id},
        provider_id=ProviderId("ch_foen"),
    )


def _wall_clock(value: datetime) -> datetime:
    """Retain an explicitly UTC source label without shifting its displayed fields."""
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second, value.microsecond)
