"""Source annotation schemas, validated tables, and projection helpers.

Source annotations preserve provider-specific qualifiers, quality codes, method
notes, unmeasured slots, and non-identity series attributes without altering the
ten canonical observation columns or interpreting publisher judgement.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from rivretrieve._internal.issues import FatalContractError

if TYPE_CHECKING:
    from rivretrieve._internal.observations import ObservationResult
    from rivretrieve._internal.source_series import SourceSeries

type AnnotationSelection = bool | str | Sequence[str]

CANONICAL_OBSERVATION_COLUMNS: tuple[str, ...] = (
    "time",
    "time_zone",
    "station_id",
    "product_id",
    "value",
    "unit",
    "series_id",
    "facts_id",
    "quantity",
    "source_unit",
)

OBSERVATION_STRUCTURAL_SCHEMA: dict[str, pl.DataType] = {
    "series_id": pl.String(),
    "facts_id": pl.String(),
    "station_id": pl.String(),
    "product_id": pl.String(),
    "time": pl.Datetime("us"),
    "time_zone": pl.String(),
    "measured": pl.Boolean(),
}

SERIES_STRUCTURAL_SCHEMA: dict[str, pl.DataType] = {
    "series_id": pl.String(),
}

CATALOG_SCHEMA: dict[str, pl.DataType] = {
    "scope": pl.String(),
    "schema": pl.String(),
    "name": pl.String(),
    "dtype": pl.String(),
    "row_count": pl.Int64(),
    "unmeasured_count": pl.Int64(),
    "description": pl.String(),
    "reference_url": pl.String(),
}

_SUPPORTED_SCALAR_DTYPES: dict[str, pl.DataType] = {
    "Boolean": pl.Boolean(),
    "Int8": pl.Int8(),
    "Int16": pl.Int16(),
    "Int32": pl.Int32(),
    "Int64": pl.Int64(),
    "UInt8": pl.UInt8(),
    "UInt16": pl.UInt16(),
    "UInt32": pl.UInt32(),
    "UInt64": pl.UInt64(),
    "Float32": pl.Float32(),
    "Float64": pl.Float64(),
    "String": pl.String(),
    "Date": pl.Date(),
    "Datetime": pl.Datetime("us"),
}

_DTYPE_ALIASES: dict[str, str] = {
    "Utf8": "String",
    "Datetime(time_unit='us', time_zone=None)": "Datetime",
}

_PLACEHOLDER_DESCRIPTIONS: frozenset[str] = frozenset({"unknown", "n/a", "na", "none", "null", "tbd", "todo", "?", "-"})

_RESERVED_OBSERVATION_FIELDS: frozenset[str] = frozenset((*CANONICAL_OBSERVATION_COLUMNS, "measured"))

_RESERVED_SERIES_FIELDS: frozenset[str] = frozenset(
    (
        *_RESERVED_OBSERVATION_FIELDS,
        "provider_id",
        "identity_namespace",
        "published_id",
        "description",
        "identity_origin",
        "variant",
        "requested_variants",
        "requested_series_ids",
        "requested_selector_kind",
        "requested_selector_value",
        "physical_match",
        "admission",
        "admission_reason",
        "source_unit_state",
        "source_unit_evidence",
        "normalized_unit",
        "identity_evidence",
        "frequency",
        "statistic",
        "temporal_support",
        "day_definition",
        "timestamp_anchor",
        "vertical_reference",
        "vertical_datum",
        "quantity_state",
        "frequency_state",
        "statistic_state",
        "temporal_support_state",
        "day_definition_state",
        "timestamp_anchor_state",
        "time_zone_state",
        "vertical_reference_state",
        "vertical_datum_state",
        "quantity_evidence",
        "frequency_evidence",
        "statistic_evidence",
        "temporal_support_evidence",
        "day_definition_evidence",
        "timestamp_anchor_evidence",
        "time_zone_evidence",
        "vertical_reference_evidence",
        "vertical_datum_evidence",
        "inventory_ids",
        "inventory_scope",
        "inventory_windows",
        "outcome_windows",
        "inventory_vintage",
        "inventory_status",
        "outcomes",
        "outcome_reasons",
    )
)

_SCHEMA_ID_FULLMATCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*").fullmatch


class AnnotationScope(StrEnum):
    """Grain of one provider-scoped annotation schema."""

    OBSERVATION = "observation"
    SERIES = "series"


def _parse_scalar_dtype(value: object) -> tuple[str, pl.DataType]:
    if isinstance(value, type) and issubclass(value, pl.DataType):
        value = value()
    if isinstance(value, str):
        canonical = _DTYPE_ALIASES.get(value.strip(), value.strip())
        if canonical in _SUPPORTED_SCALAR_DTYPES:
            return canonical, _SUPPORTED_SCALAR_DTYPES[canonical]
        raise ValueError(f"Unsupported annotation dtype: {value!r}")
    if isinstance(value, pl.Datetime):
        if value.time_zone is not None:
            raise ValueError("Timezone-aware Datetime annotations are not supported; use naive Datetime with time_zone")
        if value.time_unit != "us":
            raise ValueError(f"Annotation Datetime must use microsecond time_unit, got {value.time_unit!r}")
        return "Datetime", pl.Datetime("us")
    if isinstance(value, pl.DataType):
        if type(value) is pl.Utf8 or type(value) is pl.String:
            return "String", pl.String()
        name = str(value)
        if name in _SUPPORTED_SCALAR_DTYPES and type(value) is type(_SUPPORTED_SCALAR_DTYPES[name]):
            return name, _SUPPORTED_SCALAR_DTYPES[name]
    raise ValueError(f"Unsupported annotation dtype: {value!r}")


def parse_polars_dtype(value: object) -> tuple[str, pl.DataType]:
    """Validate and resolve a plain Polars scalar or single-level list dtype."""
    if isinstance(value, pl.List):
        inner_name, inner_dt = _parse_scalar_dtype(value.inner)
        return f"List({inner_name})", pl.List(inner_dt)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("List(") and text.endswith(")"):
            inner_text = text[5:-1].strip()
            inner_name, inner_dt = _parse_scalar_dtype(inner_text)
            return f"List({inner_name})", pl.List(inner_dt)
        return _parse_scalar_dtype(text)
    if isinstance(value, pl.DataType) or (isinstance(value, type) and issubclass(value, pl.DataType)):
        resolved = value() if isinstance(value, type) else value
        if isinstance(resolved, pl.List):
            inner_name, inner_dt = _parse_scalar_dtype(resolved.inner)
            return f"List({inner_name})", pl.List(inner_dt)
        return _parse_scalar_dtype(resolved)
    raise ValueError(f"Unsupported annotation dtype: {value!r}")


def _validate_reference_url(url: str) -> None:
    if not url or url.strip() != url or any(ch.isspace() for ch in url):
        raise ValueError(f"Invalid annotation reference URL: {url!r}")
    if url.startswith("https://"):
        rest = url[8:]
    elif url.startswith("http://"):
        rest = url[7:]
    else:
        raise ValueError(f"Annotation reference URL must use http or https with a host: {url!r}")
    host = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not host or "@" in host or host.endswith(":"):
        raise ValueError(f"Annotation reference URL must use http or https with a host: {url!r}")


class AnnotationField(BaseModel):
    """Metadata and Polars dtype definition for one source-annotation field.

    Attributes
    ----------
    name : str
        Column name exported when this field is requested.
    dtype : str
        Canonical plain Polars scalar or single-level list dtype name.
    description : str
        Human-readable summary of the source field meaning.
    reference_url : str or None
        Optional source documentation URL using HTTP or HTTPS.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    dtype: str
    description: str
    reference_url: str | None = None

    @field_validator("dtype", mode="before")
    @classmethod
    def _coerce_dtype(cls, value: object) -> str:
        canonical, _ = parse_polars_dtype(value)
        return canonical

    @model_validator(mode="after")
    def _validate_field(self) -> AnnotationField:
        stripped_name = self.name.strip()
        if (
            not stripped_name
            or stripped_name != self.name
            or stripped_name.startswith("_")
            or any(ch.isspace() for ch in stripped_name)
        ):
            raise ValueError(f"Invalid annotation field name: {self.name!r}")
        stripped_desc = self.description.strip()
        if not stripped_desc or stripped_desc.casefold() in _PLACEHOLDER_DESCRIPTIONS:
            raise ValueError(f"Annotation field {self.name!r} requires a non-placeholder description")
        if self.reference_url is not None:
            _validate_reference_url(self.reference_url)
        return self

    @property
    def polars_dtype(self) -> pl.DataType:
        """Resolved Polars DataType for this field."""
        _, dtype = parse_polars_dtype(self.dtype)
        return dtype


class AnnotationSchema(BaseModel):
    """Schema contract for one provider-scoped annotation table.

    Attributes
    ----------
    schema_id : str
        Stable schema identifier, also used as partition key on disk.
    provider_id : str
        Identifier of the provider defining this schema.
    scope : AnnotationScope
        Whether rows attach to observations/unmeasured slots or source series.
    fields : tuple[AnnotationField, ...]
        Ordered non-empty field definitions carried by this table.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: str
    provider_id: str
    scope: AnnotationScope
    fields: tuple[AnnotationField, ...]

    @model_validator(mode="after")
    def _validate_schema(self) -> AnnotationSchema:
        if not self.schema_id or ".." in self.schema_id or _SCHEMA_ID_FULLMATCH(self.schema_id) is None:
            raise ValueError(f"Invalid annotation schema_id: {self.schema_id!r}")
        if not self.provider_id or not self.provider_id.strip():
            raise ValueError("AnnotationSchema requires a nonempty provider_id")
        if not self.fields:
            raise ValueError(f"AnnotationSchema {self.schema_id!r} requires at least one field")
        reserved = (
            _RESERVED_OBSERVATION_FIELDS if self.scope is AnnotationScope.OBSERVATION else _RESERVED_SERIES_FIELDS
        )
        seen: set[str] = set()
        for item in self.fields:
            if item.name in seen:
                raise ValueError(f"Duplicate annotation field {item.name!r} in schema {self.schema_id!r}")
            if item.name in reserved:
                raise ValueError(f"Annotation field {item.name!r} collides with reserved {self.scope} column")
            seen.add(item.name)
        return self

    def polars_schema(self) -> dict[str, pl.DataType]:
        """Mapping from field name to Polars DataType."""
        return {item.name: item.polars_dtype for item in self.fields}

    def field_names(self) -> tuple[str, ...]:
        """Ordered tuple of field names in this schema."""
        return tuple(item.name for item in self.fields)


@dataclass(frozen=True, slots=True)
class ObservationAnnotationTable:
    """Annotation rows at observation grain, including optional unmeasured slots."""

    schema: AnnotationSchema
    rows: pl.DataFrame
    measurement_indices: tuple[int | None, ...]

    @classmethod
    def from_rows(
        cls,
        *,
        schema: AnnotationSchema,
        rows: pl.DataFrame,
        measurement_indices: Sequence[int | None],
    ) -> ObservationAnnotationTable:
        if schema.scope is not AnnotationScope.OBSERVATION:
            raise FatalContractError(f"Schema {schema.schema_id!r} is not an observation annotation schema")
        expected_schema = {**OBSERVATION_STRUCTURAL_SCHEMA, **schema.polars_schema()}
        if list(rows.columns) != list(expected_schema):
            raise FatalContractError(
                f"Observation annotation columns mismatch for {schema.schema_id!r}: "
                f"expected {list(expected_schema)}, got {rows.columns}"
            )
        for name, expected_dtype in expected_schema.items():
            if rows.schema[name] != expected_dtype:
                raise FatalContractError(
                    f"Observation annotation column {name!r} dtype mismatch in {schema.schema_id!r}: "
                    f"expected {expected_dtype}, got {rows.schema[name]}"
                )
        for name in OBSERVATION_STRUCTURAL_SCHEMA:
            if rows[name].null_count() > 0:
                raise FatalContractError(
                    f"Observation annotation structural column {name!r} cannot contain null values"
                )
        indices = tuple(measurement_indices)
        if len(indices) != rows.height:
            raise FatalContractError("Annotation measurement_indices length must match row count")
        if rows.height == 0:
            return cls(schema=schema, rows=rows, measurement_indices=())
        idx_series = pl.Series("_mi", indices, dtype=pl.Int64)
        disagree = rows["measured"].ne_missing(idx_series.is_not_null())
        if disagree.any():
            row_idx = int(disagree.arg_true()[0])
            raise FatalContractError(
                f"Annotation row {row_idx} in {schema.schema_id!r} disagrees between measured and measurement index"
            )
        if (idx_series < 0).any():
            raise FatalContractError("Observation annotation measurement index cannot be negative")
        non_null = idx_series.drop_nulls()
        if non_null.n_unique() != non_null.len():
            seen_indices: set[int] = set()
            for meas_idx in non_null.to_list():
                if meas_idx in seen_indices:
                    raise FatalContractError(
                        f"Duplicate annotation row for measurement index {meas_idx} in {schema.schema_id!r}"
                    )
                seen_indices.add(meas_idx)
        return cls(
            schema=schema,
            rows=rows,
            measurement_indices=indices,
        )

    @classmethod
    def empty(cls, schema: AnnotationSchema) -> ObservationAnnotationTable:
        expected_schema = {**OBSERVATION_STRUCTURAL_SCHEMA, **schema.polars_schema()}
        return cls.from_rows(
            schema=schema,
            rows=pl.DataFrame(schema=expected_schema),
            measurement_indices=(),
        )

    @property
    def row_count(self) -> int:
        return self.rows.height

    @property
    def unmeasured_count(self) -> int:
        if self.rows.height == 0:
            return 0
        return int((~self.rows["measured"]).sum())

    def with_utc_timestamps(
        self, utc_times: pl.Series | Sequence[datetime], naive_dtype: pl.DataType
    ) -> ObservationAnnotationTable:
        time_col = (
            (utc_times.cast(naive_dtype) if utc_times.dtype != naive_dtype else utc_times).alias("time")
            if isinstance(utc_times, pl.Series)
            else pl.Series("time", list(utc_times), dtype=naive_dtype)
        )
        updated_rows = self.rows.with_columns(
            time_col,
            pl.lit("+00:00", dtype=pl.String()).alias("time_zone"),
        )
        return ObservationAnnotationTable(
            schema=self.schema,
            rows=updated_rows,
            measurement_indices=self.measurement_indices,
        )

    def is_canonically_ordered(self) -> bool:
        """Return whether rows already follow ``AnnotationBundle.merge_sorted`` order."""
        if self.rows.height <= 1:
            return True
        return self.rows.select(
            pl.struct(
                "station_id",
                "product_id",
                "series_id",
                "facts_id",
                "time",
                "time_zone",
                (~pl.col("measured")).alias("_unmeasured"),
                pl.Series("_measurement_index", self.measurement_indices, dtype=pl.Int64).fill_null(-1),
            ).alias("_sort_key")
        )["_sort_key"].is_sorted()

    def narrow(
        self,
        *,
        old_to_new: Mapping[int, int],
        allowed_series_facts: set[tuple[str, str]],
    ) -> ObservationAnnotationTable:
        keep_positions: list[int] = []
        new_indices: list[int | None] = []
        series_col: list[str] | None = None
        facts_col: list[str] | None = None
        for pos, meas_idx in enumerate(self.measurement_indices):
            if meas_idx is not None:
                new_idx = old_to_new.get(meas_idx)
                if new_idx is not None:
                    keep_positions.append(pos)
                    new_indices.append(new_idx)
            else:
                if series_col is None or facts_col is None:
                    series_col = self.rows["series_id"].to_list()
                    facts_col = self.rows["facts_id"].to_list()
                if (series_col[pos], facts_col[pos]) in allowed_series_facts:
                    keep_positions.append(pos)
                    new_indices.append(None)
        if not keep_positions:
            return ObservationAnnotationTable.empty(self.schema)
        narrowed_rows = self.rows if len(keep_positions) == self.rows.height else self.rows[keep_positions]
        return ObservationAnnotationTable.from_rows(
            schema=self.schema,
            rows=narrowed_rows,
            measurement_indices=new_indices,
        )


@dataclass(frozen=True, slots=True)
class SeriesAnnotationTable:
    """Non-identity source attribute rows keyed by ``series_id``."""

    schema: AnnotationSchema
    rows: pl.DataFrame

    @classmethod
    def from_rows(cls, *, schema: AnnotationSchema, rows: pl.DataFrame) -> SeriesAnnotationTable:
        if schema.scope is not AnnotationScope.SERIES:
            raise FatalContractError(f"Schema {schema.schema_id!r} is not a series annotation schema")
        expected_schema = {**SERIES_STRUCTURAL_SCHEMA, **schema.polars_schema()}
        if list(rows.columns) != list(expected_schema):
            raise FatalContractError(
                f"Series annotation columns mismatch for {schema.schema_id!r}: "
                f"expected {list(expected_schema)}, got {rows.columns}"
            )
        for name, expected_dtype in expected_schema.items():
            if rows.schema[name] != expected_dtype:
                raise FatalContractError(
                    f"Series annotation column {name!r} dtype mismatch in {schema.schema_id!r}: "
                    f"expected {expected_dtype}, got {rows.schema[name]}"
                )
        if rows["series_id"].null_count() > 0 or rows["series_id"].n_unique() != rows.height:
            raise FatalContractError(f"Series annotation table {schema.schema_id!r} requires unique non-null series_id")
        return cls(schema=schema, rows=rows)

    @classmethod
    def empty(cls, schema: AnnotationSchema) -> SeriesAnnotationTable:
        expected_schema = {**SERIES_STRUCTURAL_SCHEMA, **schema.polars_schema()}
        return cls.from_rows(schema=schema, rows=pl.DataFrame(schema=expected_schema))

    @property
    def row_count(self) -> int:
        return self.rows.height

    def narrow(self, allowed_series_ids: set[str]) -> SeriesAnnotationTable:
        if not allowed_series_ids or self.rows.height == 0:
            return SeriesAnnotationTable.empty(self.schema)
        filtered = self.rows.filter(pl.col("series_id").is_in(list(allowed_series_ids)))
        return SeriesAnnotationTable.from_rows(schema=self.schema, rows=filtered)


def _normalize_selection(selection: AnnotationSelection) -> tuple[bool, tuple[str, ...] | None]:
    if isinstance(selection, bool):
        return selection, None
    if isinstance(selection, str):
        return True, (selection,)
    if isinstance(selection, Sequence):
        names: list[str] = []
        seen: set[str] = set()
        for item in selection:
            if not isinstance(item, str):
                raise TypeError("Annotation selection sequence must contain only field-name strings")
            if item not in seen:
                seen.add(item)
                names.append(item)
        return bool(names), tuple(names)
    raise TypeError("annotations must be a bool, str, or sequence of str field names")


def _sort_observation_annotation_rows(
    schema: AnnotationSchema,
    combined_rows: pl.DataFrame,
    combined_indices: Sequence[int | None],
) -> ObservationAnnotationTable:
    if combined_rows.height <= 1:
        return ObservationAnnotationTable.from_rows(
            schema=schema,
            rows=combined_rows,
            measurement_indices=combined_indices,
        )
    mi_series = pl.Series("_rr_mi", combined_indices, dtype=pl.Int64)
    is_sorted = combined_rows.select(
        pl.struct(
            "station_id",
            "product_id",
            "series_id",
            "facts_id",
            "time",
            "time_zone",
            (~pl.col("measured")).alias("_rr_unmeasured"),
            mi_series.fill_null(-1).alias("_rr_mi_key"),
        ).alias("_rr_key")
    )["_rr_key"].is_sorted()
    if is_sorted:
        return ObservationAnnotationTable.from_rows(
            schema=schema,
            rows=combined_rows,
            measurement_indices=combined_indices,
        )
    order = (
        combined_rows.select(
            "station_id",
            "product_id",
            "series_id",
            "facts_id",
            "time",
            "time_zone",
            (~pl.col("measured")).alias("_rr_unmeasured"),
        )
        .with_columns(mi_series.fill_null(-1).alias("_rr_mi_key"))
        .with_row_index("_rr_pos")
        .sort(
            [
                "station_id",
                "product_id",
                "series_id",
                "facts_id",
                "time",
                "time_zone",
                "_rr_unmeasured",
                "_rr_mi_key",
            ],
            maintain_order=True,
        )["_rr_pos"]
    )
    return ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=combined_rows.select(pl.all().gather(order)),
        measurement_indices=mi_series.gather(order).to_list(),
    )


@dataclass(frozen=True, slots=True)
class AnnotationBundle:
    """Collection of observation- and series-grain annotation tables attached to a result."""

    observation_tables: dict[str, ObservationAnnotationTable] = field(default_factory=dict)
    series_tables: dict[str, SeriesAnnotationTable] = field(default_factory=dict)

    def __post_init__(self) -> None:
        obs = dict(self.observation_tables)
        ser = dict(self.series_tables)
        for key, table in obs.items():
            if key != table.schema.schema_id:
                raise FatalContractError(
                    f"Observation annotation table key mismatch: {key!r} != {table.schema.schema_id!r}"
                )
        for key, table in ser.items():
            if key != table.schema.schema_id:
                raise FatalContractError(f"Series annotation table key mismatch: {key!r} != {table.schema.schema_id!r}")
        overlap = set(obs) & set(ser)
        if overlap:
            raise FatalContractError(f"Annotation schema IDs cannot span both scopes: {sorted(overlap)}")
        object.__setattr__(self, "observation_tables", obs)
        object.__setattr__(self, "series_tables", ser)

    @classmethod
    def empty(cls) -> AnnotationBundle:
        return cls()

    @property
    def is_empty(self) -> bool:
        return not self.observation_tables and not self.series_tables

    def all_schemas(self) -> tuple[AnnotationSchema, ...]:
        """Return all registered annotation schemas across observation and series tables."""
        return tuple(table.schema for table in (*self.observation_tables.values(), *self.series_tables.values()))

    def catalog_frame(self) -> pl.DataFrame:
        """Build the eight-column inspection catalog covering all attached annotation schemas."""
        records: list[dict[str, object]] = []
        for table in self.observation_tables.values():
            count = table.row_count
            unmeasured = table.unmeasured_count
            for item in table.schema.fields:
                records.append(
                    {
                        "scope": table.schema.scope.value,
                        "schema": table.schema.schema_id,
                        "name": item.name,
                        "dtype": item.dtype,
                        "row_count": count,
                        "unmeasured_count": unmeasured,
                        "description": item.description,
                        "reference_url": item.reference_url,
                    }
                )
        for table in self.series_tables.values():
            count = table.row_count
            for item in table.schema.fields:
                records.append(
                    {
                        "scope": table.schema.scope.value,
                        "schema": table.schema.schema_id,
                        "name": item.name,
                        "dtype": item.dtype,
                        "row_count": count,
                        "unmeasured_count": 0,
                        "description": item.description,
                        "reference_url": item.reference_url,
                    }
                )
        return pl.DataFrame(records, schema=CATALOG_SCHEMA)

    def schema_table(self, schema_id: str) -> pl.DataFrame:
        """Return a clone of the direct table for one schema identifier."""
        if schema_id in self.observation_tables:
            return self.observation_tables[schema_id].rows.clone()
        if schema_id in self.series_tables:
            return self.series_tables[schema_id].rows.clone()
        raise ValueError(f"Unknown annotation schema: {schema_id!r}")

    def _resolve_requested_fields(
        self,
        schemas: Iterable[AnnotationSchema],
        selection: AnnotationSelection,
        *,
        scope_label: str,
    ) -> tuple[tuple[str, ...], dict[str, pl.DataType]]:
        include, requested = _normalize_selection(selection)
        if not include:
            return (), {}
        fields_by_name: dict[str, AnnotationField] = {}
        ordered_all: list[str] = []
        requested_set = set(requested) if requested is not None else None
        for schema in schemas:
            for item in schema.fields:
                if requested_set is not None and item.name not in requested_set:
                    continue
                existing = fields_by_name.get(item.name)
                if existing is not None and existing != item:
                    raise ValueError(
                        f"Incompatible annotation field {item.name!r}: conflicting definitions across schemas"
                    )
                if item.name not in fields_by_name:
                    fields_by_name[item.name] = item
                    ordered_all.append(item.name)
        field_dtypes = {name: field.polars_dtype for name, field in fields_by_name.items()}
        if requested is not None:
            missing = [name for name in requested if name not in fields_by_name]
            if missing:
                raise ValueError(f"Unknown {scope_label} annotation field: {missing[0]!r}")
            return requested, field_dtypes
        return tuple(ordered_all), field_dtypes

    def project_observation_columns(self, row_count: int, selection: AnnotationSelection) -> list[pl.Series]:
        """Project requested observation-scope annotation fields aligned 1:1 with observation rows."""
        ordered_names, field_dtypes = self._resolve_requested_fields(
            (table.schema for table in self.observation_tables.values()),
            selection,
            scope_label="observation",
        )
        if not ordered_names:
            return []
        if row_count == 0:
            for table in self.observation_tables.values():
                if table.row_count > 0 and table.unmeasured_count < table.row_count:
                    raise FatalContractError("Observation annotation measurement index exceeds observation row count")
            return [pl.Series(name, [], dtype=field_dtypes[name]) for name in ordered_names]

        tables = tuple(self.observation_tables.values())
        if len(tables) == 1:
            table = tables[0]
            if table.row_count == 0 or table.unmeasured_count == table.row_count:
                return [
                    pl.repeat(None, row_count, dtype=field_dtypes[name], eager=True).alias(name)
                    for name in ordered_names
                ]
            idx_series = pl.Series("_mi", table.measurement_indices, dtype=pl.Int64)
            if table.unmeasured_count == 0:
                if (idx_series >= row_count).any():
                    raise FatalContractError("Observation annotation measurement index exceeds observation row count")
                if table.row_count == row_count and idx_series.is_sorted() and int(idx_series[-1]) == row_count - 1:
                    return [table.rows[name] for name in ordered_names]
                meas_rows = table.rows.select(*ordered_names).with_columns(idx_series.alias("_mi"))
            else:
                meas_mask = table.rows["measured"]
                meas_idx = idx_series.filter(meas_mask)
                if (meas_idx >= row_count).any():
                    raise FatalContractError("Observation annotation measurement index exceeds observation row count")
                meas_rows = table.rows.filter(meas_mask).select(*ordered_names).with_columns(meas_idx.alias("_mi"))
            base = pl.DataFrame({"_mi": pl.arange(0, row_count, eager=True, dtype=pl.Int64)})
            projected = base.join(meas_rows, on="_mi", how="left", maintain_order="left")
            return [projected[name] for name in ordered_names]

        ordered_set = set(ordered_names)
        base = pl.DataFrame({"_mi": pl.arange(0, row_count, eager=True, dtype=pl.Int64)})
        projected_cols: dict[str, pl.Series] = {}
        presence_masks: dict[str, pl.Series] = {}
        for table in tables:
            active_fields = [name for name in table.schema.field_names() if name in ordered_set]
            if not active_fields or table.row_count == 0 or table.unmeasured_count == table.row_count:
                continue
            idx_series = pl.Series("_mi", table.measurement_indices, dtype=pl.Int64)
            if table.unmeasured_count == 0:
                meas_idx = idx_series
                meas_rows = table.rows.select(*active_fields)
            else:
                meas_mask = table.rows["measured"]
                meas_idx = idx_series.filter(meas_mask)
                meas_rows = table.rows.filter(meas_mask).select(*active_fields)
            if (meas_idx >= row_count).any():
                raise FatalContractError("Observation annotation measurement index exceeds observation row count")
            if (
                table.unmeasured_count == 0
                and table.row_count == row_count
                and idx_series.is_sorted()
                and int(idx_series[-1]) == row_count - 1
            ):
                table_presence = pl.repeat(True, row_count, dtype=pl.Boolean, eager=True)
                joined = meas_rows
            else:
                joined = base.join(
                    meas_rows.with_columns(meas_idx.alias("_mi"), pl.lit(True, dtype=pl.Boolean).alias("_present")),
                    on="_mi",
                    how="left",
                    maintain_order="left",
                )
                table_presence = joined["_present"].fill_null(False)
            for field_name in active_fields:
                col_series = joined[field_name]
                if field_name not in projected_cols:
                    projected_cols[field_name] = col_series
                    presence_masks[field_name] = table_presence
                    continue
                conflict = presence_masks[field_name] & table_presence
                if conflict.any():
                    conflict_idx = int(conflict.arg_true()[0])
                    raise ValueError(
                        f"Conflicting annotation rows for field {field_name!r} at observation row {conflict_idx}"
                    )
                projected_cols[field_name] = pl.DataFrame(
                    {"_cur": col_series, "_prev": projected_cols[field_name], "_p": table_presence}
                ).select(pl.when(pl.col("_p")).then(pl.col("_cur")).otherwise(pl.col("_prev")).alias(field_name))[
                    field_name
                ]
                presence_masks[field_name] = presence_masks[field_name] | table_presence

        return [
            projected_cols[name]
            if name in projected_cols
            else pl.repeat(None, row_count, dtype=field_dtypes[name], eager=True).alias(name)
            for name in ordered_names
        ]

    def join_series_columns(self, frame: pl.DataFrame, selection: AnnotationSelection) -> pl.DataFrame:
        """Left-join requested series-scope annotation fields onto a ``series()`` frame."""
        ordered_names, field_dtypes = self._resolve_requested_fields(
            (table.schema for table in self.series_tables.values()),
            selection,
            scope_label="series",
        )
        if not ordered_names:
            return frame
        if "series_id" not in frame.columns or frame.height == 0:
            return frame.with_columns(
                [pl.Series(name, [None] * frame.height, dtype=field_dtypes[name]) for name in ordered_names]
            )
        by_series: dict[str, dict[str, object]] = {}
        for table in self.series_tables.values():
            table_fields = set(table.schema.field_names())
            active_fields = [name for name in ordered_names if name in table_fields]
            if not active_fields:
                continue
            for row in table.rows.select("series_id", *active_fields).iter_rows(named=True):
                sid = cast("str", row["series_id"])
                entry = by_series.setdefault(sid, {})
                for field_name in active_fields:
                    if field_name in entry:
                        raise ValueError(
                            f"Conflicting series annotation rows for field {field_name!r} and series_id {sid!r}"
                        )
                    entry[field_name] = row[field_name]
        series_ids = frame["series_id"].to_list()
        return frame.with_columns(
            [
                pl.Series(
                    name,
                    [by_series[sid].get(name) if sid is not None and sid in by_series else None for sid in series_ids],
                    dtype=field_dtypes[name],
                )
                for name in ordered_names
            ]
        )

    def narrow(
        self,
        *,
        old_to_new: Mapping[int, int],
        allowed_series_facts: set[tuple[str, str]],
        allowed_series_ids: set[str],
    ) -> AnnotationBundle:
        """Restrict observation and series tables after ``pick()`` filtering."""
        obs: dict[str, ObservationAnnotationTable] = {}
        for schema_id, table in self.observation_tables.items():
            narrowed = table.narrow(old_to_new=old_to_new, allowed_series_facts=allowed_series_facts)
            if narrowed.row_count > 0:
                obs[schema_id] = narrowed
        ser: dict[str, SeriesAnnotationTable] = {}
        for schema_id, table in self.series_tables.items():
            narrowed = table.narrow(allowed_series_ids)
            if narrowed.row_count > 0:
                ser[schema_id] = narrowed
        return AnnotationBundle(observation_tables=obs, series_tables=ser)

    def canonicalize_for_sorted_rows(self) -> AnnotationBundle:
        """Canonicalize annotation tables when observation rows already match canonical order."""
        if self.is_empty:
            return self
        obs: dict[str, ObservationAnnotationTable] = {}
        changed = False
        for schema_id, table in self.observation_tables.items():
            if table.row_count == 0:
                changed = True
                continue
            if table.is_canonically_ordered():
                obs[schema_id] = table
            else:
                obs[schema_id] = _sort_observation_annotation_rows(table.schema, table.rows, table.measurement_indices)
                changed = True
        ser: dict[str, SeriesAnnotationTable] = {}
        for schema_id, table in self.series_tables.items():
            if table.row_count == 0:
                changed = True
                continue
            if table.row_count <= 1 or table.rows["series_id"].is_sorted():
                ser[schema_id] = table
            else:
                ser[schema_id] = SeriesAnnotationTable.from_rows(
                    schema=table.schema,
                    rows=table.rows.sort("series_id"),
                )
                changed = True
        if not changed:
            return self
        return AnnotationBundle(observation_tables=obs, series_tables=ser)

    @classmethod
    def merge_sorted(
        cls,
        bundles: Sequence[AnnotationBundle],
        *,
        row_offsets: Sequence[int],
        old_to_new: Mapping[int, int],
    ) -> AnnotationBundle:
        """Merge annotations across result partitions after canonical row reordering."""
        obs_by_schema: dict[str, list[tuple[ObservationAnnotationTable, list[int | None]]]] = {}
        ser_by_schema: dict[str, list[SeriesAnnotationTable]] = {}
        for bundle, offset in zip(bundles, row_offsets, strict=True):
            for schema_id, table in bundle.observation_tables.items():
                if table.row_count == 0:
                    continue
                remapped_indices = [
                    None if idx is None else old_to_new[offset + idx] for idx in table.measurement_indices
                ]
                obs_by_schema.setdefault(schema_id, []).append((table, remapped_indices))
            for schema_id, table in bundle.series_tables.items():
                if table.row_count > 0:
                    ser_by_schema.setdefault(schema_id, []).append(table)

        merged_obs: dict[str, ObservationAnnotationTable] = {}
        for schema_id, items in obs_by_schema.items():
            schema = items[0][0].schema
            for other, _ in items[1:]:
                if other.schema != schema:
                    raise FatalContractError(f"Conflicting annotation schema definitions for {schema_id!r}")
            combined_rows = items[0][0].rows if len(items) == 1 else pl.concat([t.rows for t, _ in items])
            combined_indices = items[0][1] if len(items) == 1 else [idx for _, indices in items for idx in indices]
            merged_obs[schema_id] = _sort_observation_annotation_rows(schema, combined_rows, combined_indices)

        merged_ser: dict[str, SeriesAnnotationTable] = {}
        for schema_id, tables in ser_by_schema.items():
            schema = tables[0].schema
            for other in tables[1:]:
                if other.schema != schema:
                    raise FatalContractError(f"Conflicting series annotation schema definitions for {schema_id!r}")
            rows_by_id: dict[str, dict[str, object]] = {}
            for table in tables:
                for row in table.rows.iter_rows(named=True):
                    sid = cast("str", row["series_id"])
                    existing = rows_by_id.get(sid)
                    if existing is not None and existing != row:
                        raise FatalContractError(
                            f"Series annotations changed while merging partitions for {schema_id!r} ({sid!r})"
                        )
                    rows_by_id[sid] = row
            sorted_records = [rows_by_id[sid] for sid in sorted(rows_by_id)]
            expected_schema = {**SERIES_STRUCTURAL_SCHEMA, **schema.polars_schema()}
            merged_ser[schema_id] = SeriesAnnotationTable.from_rows(
                schema=schema,
                rows=pl.DataFrame(sorted_records, schema=expected_schema),
            )

        return cls(observation_tables=merged_obs, series_tables=merged_ser)


def validate_bundle_for_result(
    bundle: AnnotationBundle,
    data: pl.DataFrame,
    source_series: tuple[SourceSeries, ...],
) -> None:
    """Validate annotation table alignment against observation rows and series definitions."""
    if not bundle.observation_tables:
        return
    coord_cols = ("series_id", "facts_id", "station_id", "product_id", "time", "time_zone")
    known_series_facts: dict[tuple[str, str], tuple[str, str]] | None = None
    obs_coords = data.select(coord_cols)
    row_count = obs_coords.height
    for table in bundle.observation_tables.values():
        if table.row_count == 0:
            continue
        meas_mask = table.rows["measured"]
        if table.unmeasured_count < table.row_count:
            meas_positions = meas_mask.arg_true()
            idx_series = pl.Series("_mi", table.measurement_indices, dtype=pl.Int64)
            meas_indices = idx_series.filter(meas_mask)
            oob_mask = meas_indices >= row_count
            tz_mismatch = getattr(obs_coords.schema["time"], "time_zone", None) != getattr(
                table.rows.schema["time"], "time_zone", None
            )
            if oob_mask.any():
                bad_oob_i = int(oob_mask.arg_true()[0])
                oob_pos = int(meas_positions[bad_oob_i])
                oob_idx = int(meas_indices[bad_oob_i])
                if bad_oob_i > 0 and tz_mismatch:
                    first_pos = int(meas_positions[0])
                    raise FatalContractError(
                        f"Annotation row {first_pos} in {table.schema.schema_id!r} disagrees with observation row coordinates"
                    )
                if bad_oob_i > 0 and not tz_mismatch:
                    sub_ann = table.rows.filter(meas_mask).head(bad_oob_i).select(coord_cols)
                    sub_obs = obs_coords.select(pl.all().gather(meas_indices.head(bad_oob_i)))
                    diffs = [sub_ann[c].ne_missing(sub_obs[c]) for c in coord_cols]
                    any_diff = diffs[0]
                    for d in diffs[1:]:
                        any_diff = any_diff | d
                    if any_diff.any():
                        bad_pos = int(meas_positions[int(any_diff.arg_true()[0])])
                        raise FatalContractError(
                            f"Annotation row {bad_pos} in {table.schema.schema_id!r} disagrees with observation row coordinates"
                        )
                raise FatalContractError(
                    f"Annotation row {oob_pos} in {table.schema.schema_id!r} references missing observation row {oob_idx}"
                )
            if tz_mismatch:
                first_pos = int(meas_positions[0])
                raise FatalContractError(
                    f"Annotation row {first_pos} in {table.schema.schema_id!r} disagrees with observation row coordinates"
                )
            ann_meas = table.rows.filter(meas_mask).select(coord_cols)
            obs_aligned = obs_coords.select(pl.all().gather(meas_indices))
            diffs = [ann_meas[c].ne_missing(obs_aligned[c]) for c in coord_cols]
            any_diff = diffs[0]
            for d in diffs[1:]:
                any_diff = any_diff | d
            if any_diff.any():
                bad_pos = int(meas_positions[int(any_diff.arg_true()[0])])
                raise FatalContractError(
                    f"Annotation row {bad_pos} in {table.schema.schema_id!r} disagrees with observation row coordinates"
                )
        if source_series and table.unmeasured_count > 0:
            if known_series_facts is None:
                known_series_facts = {
                    (item.series_id, facts.facts_id): (item.station_id, item.product_id)
                    for item in source_series
                    for facts in item.facts
                }
            unmeasured_pairs = (
                table.rows.filter(~meas_mask).select("series_id", "facts_id", "station_id", "product_id").unique()
            )
            for sid, fid, st, prod in unmeasured_pairs.iter_rows():
                if known_series_facts.get((sid, fid)) != (st, prod):
                    raise FatalContractError(
                        f"Unmeasured annotation slot in {table.schema.schema_id!r} references unknown series or facts"
                    )


def with_annotations(result: ObservationResult, bundle: AnnotationBundle) -> ObservationResult:
    """Return a copy of ``result`` carrying ``bundle`` after validating row linkage."""
    validate_bundle_for_result(bundle, result.data, result.source_series)
    copied = result.model_copy()
    object.__setattr__(copied, "_annotations", bundle)
    return copied


def filter_native_with_annotations_by_mask(
    rows: pl.DataFrame,
    bundle: AnnotationBundle,
    keep_mask: pl.Series,
    *,
    unmeasured_mask_fn: Callable[[pl.DataFrame], pl.Series] | None = None,
    unmeasured_predicate: Callable[[dict[str, object]], bool] | None = None,
    unmeasured_expr: pl.Expr | None = None,
    allowed_series_ids: set[str] | None = None,
) -> tuple[pl.DataFrame, AnnotationBundle]:
    """Filter native observation rows by a boolean mask while keeping annotations aligned."""
    if keep_mask.len() != rows.height:
        raise FatalContractError("Annotation filter mask length must match observation row count")
    mask = (
        keep_mask
        if keep_mask.dtype == pl.Boolean and keep_mask.null_count() == 0
        else keep_mask.cast(pl.Boolean).fill_null(False)
    )
    all_rows_kept = rows.is_empty() or bool(mask.all())
    filtered_rows = rows if all_rows_kept else rows.filter(mask)
    if bundle.is_empty:
        return filtered_rows, bundle
    needs_unmeasured_filter = (
        unmeasured_mask_fn is not None
        or unmeasured_predicate is not None
        or unmeasured_expr is not None
        or allowed_series_ids is not None
    )
    cum = mask.cast(pl.Int64).cum_sum() - 1 if not all_rows_kept and not rows.is_empty() else None
    obs_tables: dict[str, ObservationAnnotationTable] = {}
    for schema_id, table in bundle.observation_tables.items():
        if table.row_count == 0:
            continue
        if all_rows_kept and not rows.is_empty() and (table.unmeasured_count == 0 or not needs_unmeasured_filter):
            obs_tables[schema_id] = table
            continue
        measured_mask = table.rows["measured"]
        if table.unmeasured_count == table.row_count or rows.is_empty():
            meas_keep = pl.repeat(False, table.row_count, dtype=pl.Boolean, eager=True)
            new_mi_series = pl.repeat(None, table.row_count, dtype=pl.Int64, eager=True)
        else:
            idx_series = pl.Series("_mi", table.measurement_indices, dtype=pl.Int64)
            in_bounds = measured_mask & (idx_series >= 0) & (idx_series < rows.height)
            if cum is None:
                meas_keep = in_bounds
                new_mi_series = idx_series
            else:
                safe_idx = idx_series.fill_null(0).clip(0, rows.height - 1)
                meas_keep = in_bounds & mask.gather(safe_idx)
                new_mi_series = pl.DataFrame({"_m": meas_keep, "_n": cum.gather(safe_idx)}).select(
                    pl.when(pl.col("_m")).then(pl.col("_n")).otherwise(None).alias("_mi")
                )["_mi"]

        if table.unmeasured_count == 0:
            unm_keep = pl.repeat(False, table.row_count, dtype=pl.Boolean, eager=True)
        elif not needs_unmeasured_filter:
            unm_keep = ~measured_mask
        else:
            unmeasured_all = ~measured_mask
            cand_pos = unmeasured_all.arg_true()
            candidate_rows = table.rows.filter(unmeasured_all)
            if allowed_series_ids is not None:
                if not allowed_series_ids:
                    cand_pos = cand_pos.head(0)
                    candidate_rows = candidate_rows.head(0)
                else:
                    sid_keep = candidate_rows["series_id"].is_in(list(allowed_series_ids))
                    cand_pos = cand_pos.filter(sid_keep)
                    candidate_rows = candidate_rows.filter(sid_keep)
            if unmeasured_expr is not None and not candidate_rows.is_empty():
                expr_keep = candidate_rows.select(unmeasured_expr.fill_null(False).alias("_k"))["_k"]
                cand_pos = cand_pos.filter(expr_keep)
                candidate_rows = candidate_rows.filter(expr_keep)
            if unmeasured_mask_fn is not None and not candidate_rows.is_empty():
                fn_raw = unmeasured_mask_fn(candidate_rows)
                fn_keep = (
                    fn_raw
                    if fn_raw.dtype == pl.Boolean and fn_raw.null_count() == 0
                    else fn_raw.cast(pl.Boolean).fill_null(False)
                )
                cand_pos = cand_pos.filter(fn_keep)
                candidate_rows = candidate_rows.filter(fn_keep)
            if unmeasured_predicate is not None and not candidate_rows.is_empty():
                pred_keep = pl.Series(
                    "_p", [bool(unmeasured_predicate(d)) for d in candidate_rows.to_dicts()], dtype=pl.Boolean
                )
                cand_pos = cand_pos.filter(pred_keep)
            if cand_pos.is_empty():
                unm_keep = pl.repeat(False, table.row_count, dtype=pl.Boolean, eager=True)
            elif cand_pos.len() == table.unmeasured_count:
                unm_keep = unmeasured_all
            else:
                pos_df = pl.DataFrame(
                    {
                        "_pos": cand_pos.cast(pl.Int64),
                        "_keep": pl.repeat(True, cand_pos.len(), dtype=pl.Boolean, eager=True),
                    }
                )
                unm_keep = (
                    pl.DataFrame({"_pos": pl.arange(0, table.row_count, eager=True, dtype=pl.Int64)})
                    .join(pos_df, on="_pos", how="left", maintain_order="left")["_keep"]
                    .fill_null(False)
                )

        keep_pos_mask = meas_keep | unm_keep
        if bool(keep_pos_mask.all()):
            if all_rows_kept:
                obs_tables[schema_id] = table
            else:
                obs_tables[schema_id] = ObservationAnnotationTable.from_rows(
                    schema=table.schema,
                    rows=table.rows,
                    measurement_indices=new_mi_series.to_list(),
                )
        elif bool(keep_pos_mask.any()):
            obs_tables[schema_id] = ObservationAnnotationTable.from_rows(
                schema=table.schema,
                rows=table.rows.filter(keep_pos_mask),
                measurement_indices=new_mi_series.filter(keep_pos_mask).to_list(),
            )

    ser_tables: dict[str, SeriesAnnotationTable] = {}
    for schema_id, table in bundle.series_tables.items():
        narrowed = table if allowed_series_ids is None else table.narrow(allowed_series_ids)
        if narrowed.row_count > 0:
            ser_tables[schema_id] = narrowed
    return filtered_rows, AnnotationBundle(observation_tables=obs_tables, series_tables=ser_tables)


def filter_native_with_annotations(
    rows: pl.DataFrame,
    bundle: AnnotationBundle,
    kept_indices: Sequence[int],
    *,
    unmeasured_predicate: Callable[[dict[str, object]], bool] | None = None,
    unmeasured_expr: pl.Expr | None = None,
    allowed_series_ids: set[str] | None = None,
) -> tuple[pl.DataFrame, AnnotationBundle]:
    """Filter native observation rows by ``kept_indices`` while keeping annotations aligned."""
    kept_list = list(kept_indices)
    if not kept_list:
        return filter_native_with_annotations_by_mask(
            rows,
            bundle,
            pl.repeat(False, rows.height, dtype=pl.Boolean, eager=True),
            unmeasured_predicate=unmeasured_predicate,
            unmeasured_expr=unmeasured_expr,
            allowed_series_ids=allowed_series_ids,
        )
    is_strictly_ascending = (
        kept_list[0] >= 0
        and kept_list[-1] < rows.height
        and all(kept_list[i] < kept_list[i + 1] for i in range(len(kept_list) - 1))
    )
    if is_strictly_ascending:
        if len(kept_list) == rows.height:
            keep_mask = pl.repeat(True, rows.height, dtype=pl.Boolean, eager=True)
        else:
            pos_df = pl.DataFrame(
                {
                    "_pos": pl.Series("_pos", kept_list, dtype=pl.Int64),
                    "_keep": pl.repeat(True, len(kept_list), dtype=pl.Boolean, eager=True),
                }
            )
            keep_mask = (
                pl.DataFrame({"_pos": pl.arange(0, rows.height, eager=True, dtype=pl.Int64)})
                .join(pos_df, on="_pos", how="left", maintain_order="left")["_keep"]
                .fill_null(False)
            )
        return filter_native_with_annotations_by_mask(
            rows,
            bundle,
            keep_mask,
            unmeasured_predicate=unmeasured_predicate,
            unmeasured_expr=unmeasured_expr,
            allowed_series_ids=allowed_series_ids,
        )

    filtered_rows = rows[kept_list]
    if bundle.is_empty:
        return filtered_rows, bundle
    old_to_new = {old: new for new, old in enumerate(kept_list)}
    needs_unmeasured_filter = (
        unmeasured_predicate is not None or unmeasured_expr is not None or allowed_series_ids is not None
    )
    obs_tables: dict[str, ObservationAnnotationTable] = {}
    for schema_id, table in bundle.observation_tables.items():
        if table.row_count == 0:
            continue
        kept_unmeasured: set[int] = set()
        if needs_unmeasured_filter and table.unmeasured_count > 0:
            candidate_positions = [pos for pos, meas_idx in enumerate(table.measurement_indices) if meas_idx is None]
            candidate_rows = table.rows[candidate_positions]
            if allowed_series_ids is not None:
                if not allowed_series_ids:
                    candidate_positions = []
                else:
                    series_mask = [sid in allowed_series_ids for sid in candidate_rows["series_id"].to_list()]
                    candidate_positions = [
                        pos for pos, flag in zip(candidate_positions, series_mask, strict=True) if flag
                    ]
                    if candidate_positions and len(candidate_positions) < candidate_rows.height:
                        candidate_rows = candidate_rows.filter(pl.Series(series_mask, dtype=pl.Boolean))
            if unmeasured_expr is not None and candidate_positions:
                expr_mask = candidate_rows.select(unmeasured_expr.alias("_k"))["_k"].to_list()
                candidate_positions = [pos for pos, flag in zip(candidate_positions, expr_mask, strict=True) if flag]
                if candidate_positions and len(candidate_positions) < candidate_rows.height:
                    candidate_rows = candidate_rows.filter(pl.Series(expr_mask, dtype=pl.Boolean))
            if unmeasured_predicate is not None and candidate_positions:
                dict_rows = candidate_rows.to_dicts()
                candidate_positions = [
                    pos
                    for pos, row_dict in zip(candidate_positions, dict_rows, strict=True)
                    if unmeasured_predicate(row_dict)
                ]
            kept_unmeasured = set(candidate_positions)
        keep_positions: list[int] = []
        new_indices: list[int | None] = []
        for pos, meas_idx in enumerate(table.measurement_indices):
            if meas_idx is not None:
                new_idx = old_to_new.get(meas_idx)
                if new_idx is not None:
                    keep_positions.append(pos)
                    new_indices.append(new_idx)
            elif not needs_unmeasured_filter or pos in kept_unmeasured:
                keep_positions.append(pos)
                new_indices.append(None)
        if keep_positions:
            kept_ann_rows = table.rows if len(keep_positions) == table.row_count else table.rows[keep_positions]
            obs_tables[schema_id] = ObservationAnnotationTable.from_rows(
                schema=table.schema,
                rows=kept_ann_rows,
                measurement_indices=new_indices,
            )
    ser_tables: dict[str, SeriesAnnotationTable] = {}
    for schema_id, table in bundle.series_tables.items():
        narrowed = table if allowed_series_ids is None else table.narrow(allowed_series_ids)
        if narrowed.row_count > 0:
            ser_tables[schema_id] = narrowed
    return filtered_rows, AnnotationBundle(observation_tables=obs_tables, series_tables=ser_tables)


def filter_native_with_annotations_by_expr(
    rows: pl.DataFrame,
    bundle: AnnotationBundle,
    predicate: pl.Expr,
    *,
    allowed_series_ids: set[str] | None = None,
) -> tuple[pl.DataFrame, AnnotationBundle]:
    """Filter native rows and aligned annotations (including unmeasured slots) using one Polars expression."""
    if rows.is_empty() and bundle.is_empty:
        return rows, bundle
    keep_mask = (
        rows.select(predicate.fill_null(False).alias("_k"))["_k"]
        if not rows.is_empty()
        else pl.Series("_k", [], dtype=pl.Boolean)
    )
    return filter_native_with_annotations_by_mask(
        rows,
        bundle,
        keep_mask,
        unmeasured_expr=predicate,
        allowed_series_ids=allowed_series_ids,
    )


def anti_join_native_with_annotations(
    rows: pl.DataFrame,
    bundle: AnnotationBundle,
    exclude_rows: pl.DataFrame,
) -> tuple[pl.DataFrame, AnnotationBundle]:
    """Remove native rows and annotations matching keys present in ``exclude_rows``."""
    if exclude_rows.is_empty() or (rows.is_empty() and bundle.is_empty):
        return rows, bundle
    key_cols = ["series_id", "facts_id", "time", "time_zone"]
    marker_frame = (
        exclude_rows.select(key_cols).unique().with_columns(pl.lit(False, dtype=pl.Boolean).alias("_rr_keep"))
    )

    def _keep_mask_for(frame: pl.DataFrame) -> pl.Series:
        if frame.is_empty():
            return pl.Series("_rr_keep", [], dtype=pl.Boolean)
        joined = frame.select(key_cols).join(
            marker_frame,
            on=key_cols,
            how="left",
            maintain_order="left",
            nulls_equal=True,
        )
        return joined["_rr_keep"].fill_null(True)

    return filter_native_with_annotations_by_mask(
        rows,
        bundle,
        _keep_mask_for(rows),
        unmeasured_mask_fn=_keep_mask_for,
    )


def merge_series_tables(
    tables: Sequence[SeriesAnnotationTable],
    *,
    conflict: Literal["raise", "prefer_last"] = "raise",
    allowed_series_ids: set[str] | None = None,
) -> dict[str, SeriesAnnotationTable]:
    """Combine series-grain annotation tables per ``schema_id``."""
    by_schema: dict[str, list[SeriesAnnotationTable]] = {}
    for table in tables:
        if table.row_count > 0:
            by_schema.setdefault(table.schema.schema_id, []).append(table)
    merged: dict[str, SeriesAnnotationTable] = {}
    for schema_id, group in by_schema.items():
        schema = group[0].schema
        for other in group[1:]:
            if other.schema != schema:
                raise FatalContractError(f"Conflicting series annotation schema definitions for {schema_id!r}")
        rows_by_id: dict[str, dict[str, object]] = {}
        for table in group:
            for row in table.rows.iter_rows(named=True):
                sid = cast("str", row["series_id"])
                if allowed_series_ids is not None and sid not in allowed_series_ids:
                    continue
                existing = rows_by_id.get(sid)
                if existing is not None and existing != row and conflict == "raise":
                    raise FatalContractError(f"Conflicting series annotations for {schema_id!r} and series_id {sid!r}")
                rows_by_id[sid] = row
        if rows_by_id:
            sorted_records = [rows_by_id[sid] for sid in sorted(rows_by_id)]
            expected_schema = {**SERIES_STRUCTURAL_SCHEMA, **schema.polars_schema()}
            merged[schema_id] = SeriesAnnotationTable.from_rows(
                schema=schema,
                rows=pl.DataFrame(sorted_records, schema=expected_schema),
            )
    return merged


def concat_native_with_annotations(
    parts: Sequence[tuple[pl.DataFrame, AnnotationBundle]],
    *,
    empty_schema: Mapping[str, pl.DataType] | pl.Schema,
    series_conflict: Literal["raise", "prefer_last"] = "raise",
) -> tuple[pl.DataFrame, AnnotationBundle]:
    """Concatenate ``(rows, bundle)`` parts in order without deduplicating observation rows."""
    if not parts:
        return pl.DataFrame(schema=empty_schema), AnnotationBundle.empty()
    if len(parts) == 1:
        return parts[0]
    row_frames = [part_rows for part_rows, _ in parts]
    combined_rows = pl.concat(row_frames)
    offsets: list[int] = []
    running = 0
    for part_rows in row_frames:
        offsets.append(running)
        running += part_rows.height

    obs_by_schema: dict[str, list[tuple[ObservationAnnotationTable, int]]] = {}
    ser_tables: list[SeriesAnnotationTable] = []
    for (_, bundle), offset in zip(parts, offsets, strict=True):
        for schema_id, table in bundle.observation_tables.items():
            if table.row_count > 0:
                obs_by_schema.setdefault(schema_id, []).append((table, offset))
        for table in bundle.series_tables.values():
            if table.row_count > 0:
                ser_tables.append(table)

    merged_obs: dict[str, ObservationAnnotationTable] = {}
    for schema_id, items in obs_by_schema.items():
        schema = items[0][0].schema
        for other, _ in items[1:]:
            if other.schema != schema:
                raise FatalContractError(f"Conflicting annotation schema definitions for {schema_id!r}")
        combined_ann_rows = pl.concat([t.rows for t, _ in items])
        combined_indices = [
            None if idx is None else offset + idx for t, offset in items for idx in t.measurement_indices
        ]
        merged_obs[schema_id] = ObservationAnnotationTable.from_rows(
            schema=schema,
            rows=combined_ann_rows,
            measurement_indices=combined_indices,
        )
    merged_ser = merge_series_tables(ser_tables, conflict=series_conflict)
    return combined_rows, AnnotationBundle(observation_tables=merged_obs, series_tables=merged_ser)


def sort_native_by_station_with_annotations(
    rows: pl.DataFrame,
    bundle: AnnotationBundle,
) -> tuple[pl.DataFrame, AnnotationBundle]:
    """Stably sort partition rows by ``station_id`` and preserve aligned annotations."""
    if rows.height <= 1 and bundle.is_empty:
        return rows, bundle
    rows_sorted = rows.height <= 1 or rows["station_id"].is_sorted()
    if rows_sorted and all(
        table.row_count <= 1 or table.rows["station_id"].is_sorted() for table in bundle.observation_tables.values()
    ):
        return rows, bundle
    if rows_sorted:
        sorted_rows = rows
        old_to_new_series: pl.Series | None = None
    else:
        sorted_with_idx = rows.with_row_index("_rr_old_idx").sort("station_id", maintain_order=True)
        old_to_new_series = sorted_with_idx["_rr_old_idx"].arg_sort().cast(pl.Int64)
        sorted_rows = sorted_with_idx.drop("_rr_old_idx")
    obs_tables: dict[str, ObservationAnnotationTable] = {}
    for schema_id, table in bundle.observation_tables.items():
        if table.row_count == 0:
            continue
        ann_sorted = table.row_count <= 1 or table.rows["station_id"].is_sorted()
        if rows_sorted and ann_sorted:
            obs_tables[schema_id] = table
            continue
        mi_series = pl.Series("_mi", table.measurement_indices, dtype=pl.Int64)
        if old_to_new_series is None or rows.height == 0:
            mapped_mi = mi_series
        else:
            mapped_mi = pl.DataFrame(
                {
                    "_mi": mi_series,
                    "_mapped": old_to_new_series.gather(mi_series.fill_null(0).clip(0, rows.height - 1)),
                }
            ).select(pl.when(pl.col("_mi").is_not_null()).then(pl.col("_mapped")).otherwise(None).alias("_mi"))["_mi"]
        if ann_sorted:
            sorted_ann_rows = table.rows
            new_indices = mapped_mi.to_list()
        else:
            sorted_tbl = table.rows.with_columns(mapped_mi.alias("_rr_new_mi")).sort("station_id", maintain_order=True)
            sorted_ann_rows = sorted_tbl.drop("_rr_new_mi")
            new_indices = sorted_tbl["_rr_new_mi"].to_list()
        obs_tables[schema_id] = ObservationAnnotationTable.from_rows(
            schema=table.schema,
            rows=sorted_ann_rows,
            measurement_indices=new_indices,
        )
    return sorted_rows, AnnotationBundle(observation_tables=obs_tables, series_tables=bundle.series_tables)


def advance_partition_key_ordinals(
    partition_rows: pl.DataFrame,
    key_counts: dict[tuple[str, str, datetime, str], int] | None = None,
) -> list[int]:
    """Compute and advance per-key ``_occurrence_ordinal`` indices for ``partition_rows``."""
    if partition_rows.is_empty():
        return []
    key_cols = ("series_id", "facts_id", "time", "time_zone")
    within_ord = partition_rows.select(pl.int_range(pl.len(), dtype=pl.Int64).over(*key_cols).alias("_ord"))["_ord"]
    if key_counts is None:
        return within_ord.to_list()
    counts_df = partition_rows.group_by(*key_cols, maintain_order=False).len()
    non_zero_rows: list[tuple[str, str, datetime, str, int]] = []
    for sid, fid, ts, tz, count in counts_df.iter_rows():
        key = cast("tuple[str, str, datetime, str]", (sid, fid, ts, tz))
        prior = key_counts.get(key, 0)
        key_counts[key] = prior + int(count)
        if prior > 0:
            non_zero_rows.append((sid, fid, ts, tz, prior))
    if not non_zero_rows:
        return within_ord.to_list()
    offset_schema = {**{c: partition_rows.schema[c] for c in key_cols}, "_offset": pl.Int64()}
    offset_frame = pl.DataFrame(non_zero_rows, schema=offset_schema, orient="row")
    offsets = (
        partition_rows.select(key_cols)
        .join(offset_frame, on=list(key_cols), how="left", maintain_order="left")["_offset"]
        .fill_null(0)
    )
    return (within_ord + offsets).to_list()


def encode_observation_table_for_parquet(
    table: ObservationAnnotationTable,
    partition_rows: pl.DataFrame,
    *,
    row_ordinals: Sequence[int] | None = None,
) -> pl.DataFrame:
    """Encode an ``ObservationAnnotationTable`` with ``_occurrence_ordinal`` aligned to ``partition_rows``."""
    ordinals = advance_partition_key_ordinals(partition_rows) if row_ordinals is None else row_ordinals
    occ_ordinals = [-1 if meas_idx is None else ordinals[meas_idx] for meas_idx in table.measurement_indices]
    with_ordinal = table.rows.with_columns(pl.Series("_occurrence_ordinal", occ_ordinals, dtype=pl.Int64()))
    columns = [*OBSERVATION_STRUCTURAL_SCHEMA, "_occurrence_ordinal", *table.schema.field_names()]
    return with_ordinal.select(columns)


def decode_observation_table_from_parquet(
    parquet_rows: pl.DataFrame,
    schema: AnnotationSchema,
    engine_rows: pl.DataFrame,
) -> ObservationAnnotationTable:
    """Decode an observation annotation Parquet frame against ``engine_rows`` order."""
    expected_cols = [*OBSERVATION_STRUCTURAL_SCHEMA, "_occurrence_ordinal", *schema.field_names()]
    if parquet_rows.columns != expected_cols:
        raise FatalContractError(
            f"Stored annotation columns mismatch for {schema.schema_id!r}: "
            f"expected {expected_cols}, got {parquet_rows.columns}"
        )
    if parquet_rows.is_empty():
        return ObservationAnnotationTable.empty(schema)
    expected_schema = {**OBSERVATION_STRUCTURAL_SCHEMA, **schema.polars_schema()}
    for name, expected_dtype in expected_schema.items():
        if parquet_rows.schema[name] != expected_dtype:
            raise FatalContractError(
                f"Observation annotation column {name!r} dtype mismatch in {schema.schema_id!r}: "
                f"expected {expected_dtype}, got {parquet_rows.schema[name]}"
            )
    for name in OBSERVATION_STRUCTURAL_SCHEMA:
        if parquet_rows[name].null_count() > 0:
            raise FatalContractError(f"Observation annotation structural column {name!r} cannot contain null values")
    occ_col = parquet_rows["_occurrence_ordinal"]
    if not occ_col.dtype.is_integer() or occ_col.null_count() > 0:
        raise FatalContractError(
            f"Stored annotation _occurrence_ordinal column in {schema.schema_id!r} must be non-null integer"
        )
    occ_i64 = occ_col.cast(pl.Int64) if occ_col.dtype != pl.Int64() else occ_col
    if ((~parquet_rows["measured"]) & (occ_i64 != -1)).any():
        raise FatalContractError(
            f"Unmeasured stored annotation row in {schema.schema_id!r} must use _occurrence_ordinal == -1"
        )

    measured_mask = parquet_rows["measured"]
    if not measured_mask.any():
        measurement_indices: list[int | None] = [None] * parquet_rows.height
    else:
        if engine_rows.is_empty():
            raise FatalContractError(
                f"Stored measured annotation row in {schema.schema_id!r} has no matching observation row"
            )
        key_cols = ["series_id", "facts_id", "time", "time_zone"]
        engine_indexed = engine_rows.select(
            *key_cols,
            pl.col("station_id").alias("_eng_station_id"),
            pl.col("product_id").alias("_eng_product_id"),
            pl.int_range(pl.len(), dtype=pl.Int64).alias("_eng_idx"),
            pl.int_range(pl.len(), dtype=pl.Int64).over(*key_cols).alias("_occurrence_ordinal"),
        )
        lookup_left = parquet_rows.select(
            *key_cols,
            "station_id",
            "product_id",
            "measured",
            occ_i64.alias("_occurrence_ordinal"),
        )
        joined = lookup_left.join(
            engine_indexed,
            on=[*key_cols, "_occurrence_ordinal"],
            how="left",
            maintain_order="left",
        )
        bad_measured = joined.select(
            (
                pl.col("measured")
                & (
                    pl.col("_eng_idx").is_null()
                    | (pl.col("_eng_station_id") != pl.col("station_id"))
                    | (pl.col("_eng_product_id") != pl.col("product_id"))
                )
            ).alias("_bad")
        )["_bad"]
        if bad_measured.any():
            raise FatalContractError(
                f"Stored measured annotation row in {schema.schema_id!r} has no matching observation row"
            )
        measurement_indices = joined.select(
            pl.when(pl.col("measured")).then(pl.col("_eng_idx")).otherwise(None).alias("_mi")
        )["_mi"].to_list()

    clean_rows = parquet_rows.drop("_occurrence_ordinal")
    return ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=clean_rows,
        measurement_indices=measurement_indices,
    )


def dump_annotation_schema(schema: AnnotationSchema) -> dict[str, object]:
    """Serialize an ``AnnotationSchema`` to a deterministic JSON-compatible dict."""
    return schema.model_dump(mode="json", exclude_none=True)


def load_annotation_schema(raw: Mapping[str, object]) -> AnnotationSchema:
    """Validate and deserialize an ``AnnotationSchema`` from manifest JSON."""
    return AnnotationSchema.model_validate(raw)


def _encode_json_scalar(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list):
        return [_encode_json_scalar(item) for item in value]
    return value


def _decode_json_field(value: object, dtype: str) -> object:
    if value is None:
        return None
    if dtype.startswith("List(") and dtype.endswith(")") and isinstance(value, list):
        inner = dtype[5:-1].strip()
        return [_decode_json_field(item, inner) for item in value]
    if dtype == "Date" and isinstance(value, str):
        return date.fromisoformat(value)
    if dtype.startswith("Datetime") and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def dump_series_annotations(
    tables: Mapping[str, SeriesAnnotationTable] | Sequence[SeriesAnnotationTable],
) -> dict[str, list[dict[str, object]]]:
    """Serialize non-empty series annotation tables to manifest JSON."""
    sequence: list[SeriesAnnotationTable] = (
        list(cast("Mapping[str, SeriesAnnotationTable]", tables).values())
        if isinstance(tables, Mapping)
        else list(tables)
    )
    result: dict[str, list[dict[str, object]]] = {}
    for table in sorted(sequence, key=lambda item: item.schema.schema_id):
        if table.row_count == 0:
            continue
        result[table.schema.schema_id] = [
            {key: _encode_json_scalar(val) for key, val in row.items()}
            for row in table.rows.sort("series_id").to_dicts()
        ]
    return result


def load_series_annotations(
    raw: Mapping[str, object],
    schemas_by_id: Mapping[str, AnnotationSchema],
) -> tuple[SeriesAnnotationTable, ...]:
    """Deserialize series annotation tables from manifest JSON using ``schemas_by_id``."""
    tables: list[SeriesAnnotationTable] = []
    for schema_id in sorted(raw):
        schema = schemas_by_id.get(schema_id)
        if schema is None:
            raise ValueError(f"Unknown series annotation schema {schema_id!r}")
        if schema.scope is not AnnotationScope.SERIES:
            raise ValueError(f"Schema {schema_id!r} in series_annotations is not series-scoped")
        entries = raw[schema_id]
        if not isinstance(entries, list):
            raise ValueError(f"series_annotations[{schema_id!r}] must be a list")
        field_dtypes = {item.name: item.dtype for item in schema.fields}
        decoded_rows: list[dict[str, object]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid row in series_annotations[{schema_id!r}]")
            entry_map = cast("dict[str, object]", entry)
            decoded_row: dict[str, object] = {"series_id": entry_map.get("series_id")}
            for field_name, field_dtype in field_dtypes.items():
                if field_name not in entry_map:
                    raise ValueError(f"Missing field {field_name!r} in series_annotations[{schema_id!r}]")
                decoded_row[field_name] = _decode_json_field(entry_map[field_name], field_dtype)
            decoded_rows.append(decoded_row)
        expected_schema = {**SERIES_STRUCTURAL_SCHEMA, **schema.polars_schema()}
        frame = pl.DataFrame(decoded_rows, schema=expected_schema)
        tables.append(SeriesAnnotationTable.from_rows(schema=schema, rows=frame))
    return tuple(tables)
