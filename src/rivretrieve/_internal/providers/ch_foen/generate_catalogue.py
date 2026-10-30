"""Offline catalogue transformations for the official Swiss hydrological API."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.official_series import (
    ARCHIVE_ROUTES,
    PARAMETERS,
    product_id,
    source_series,
)

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        **dict.fromkeys(
            (
                "no",
                "name",
                "siteName",
                "riverName",
                "catchmentName",
                "status",
                "adminName",
                "adminLevel",
                "coverageFrom",
                "coverageTo",
            ),
            pl.String,
        ),
        **dict.fromkeys(("localX", "localY", "latitude", "longitude", "elevation"), pl.Float64),
    }
)


def _response_rows(payload: Mapping[str, object], route: str) -> list[dict[str, object]]:
    if payload.get("errors"):
        raise FatalContractError("Swiss API catalogue response contains GraphQL errors")
    value: object = payload
    for key in ("data", "water", "observations", route):
        if not isinstance(value, dict) or key not in value:
            raise FatalContractError("Swiss API catalogue response lacks the selected route")
        value = cast("dict[str, object]", value)[key]
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise FatalContractError("Swiss API catalogue route must contain source objects")
    return cast("list[dict[str, object]]", value)


def station_native_table(payload: Mapping[str, object], *, retrieved_at: RetrievedAt) -> NativeTable:
    """Preserve station numbers, optional metadata and missing source coordinates.

    Station status and station-level coverage dates do not filter the snapshot
    or establish product availability. Numbers must already be source strings.
    """
    rows = _response_rows(payload, "stations")
    numbers = [row.get("no") for row in rows]
    if any(not isinstance(number, str) or not number.strip() for number in numbers) or len(set(numbers)) != len(
        numbers
    ):
        raise FatalContractError("Swiss station number must be a distinct nonblank source string")
    for row in rows:
        for name, dtype in STATION_SOURCE_SCHEMA.items():
            value = row.get(name)
            if value is not None and (
                (dtype == pl.String and not isinstance(value, str))
                or (dtype == pl.Float64 and (isinstance(value, bool) or not isinstance(value, int | float)))
            ):
                raise FatalContractError("Swiss station metadata has invalid scalar types")
    try:
        frame = pl.DataFrame(rows, schema=STATION_SOURCE_SCHEMA, strict=True).sort("no")
    except (TypeError, ValueError, pl.exceptions.PolarsError) as error:
        raise FatalContractError("Swiss station metadata has invalid scalar types") from error
    return stamp_native_table(frame, retrieved_at)


ASSOCIATION_SCHEMA = pl.Schema(
    dict.fromkeys(("station_no", "station_id", "route", "parameterName", "tsName", "unitName", "unitSymbol"), pl.String)
)


def archive_associations(payload: Mapping[str, object], *, route: str, station_numbers: set[str]) -> pl.DataFrame:
    """Select witnessed archive identities, including observations with null values.

    Embedded station IDs remain source facts distinct from station numbers.
    Empty responses establish no negative availability claim. This operation does
    not interpret raw series names, units or sampled timestamps as physical facts
    or record boundaries. Acquisition completeness is checked separately.
    """
    associations = []
    for row in _response_rows(payload, route):
        station = row.get("station")
        if not isinstance(station, dict):
            raise FatalContractError("Archive association requires a source station object")
        station = cast("dict[str, object]", station)
        number = station.get("no")
        if not isinstance(number, str):
            raise FatalContractError("Archive association requires a source string station number")
        if number not in station_numbers:
            raise FatalContractError("Archive association station is absent from the station snapshot")
        values = {name: row.get(name) for name in ("parameterName", "tsName", "unitName", "unitSymbol")}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise FatalContractError("Archive association requires source parameter, raw name and units")
        embedded = station.get("id")
        if embedded is not None and not isinstance(embedded, str):
            raise FatalContractError("Archive embedded station identity must remain a source string")
        associations.append({"station_no": number, "station_id": embedded, "route": route, **values})
    return pl.DataFrame(associations, schema=ASSOCIATION_SCHEMA).unique().sort(ASSOCIATION_SCHEMA.names())


def describe_associations(associations: pl.DataFrame, *, evidence: str) -> SourceDescriptions:
    """Describe witnessed identities using the same definitions as response parsing.

    Distinct native units remain fact segments. Sample times do not establish
    record boundaries, and archive station IDs do not replace source coordinates.
    """
    from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions

    descriptions = []
    groups = associations.sort(ASSOCIATION_SCHEMA.names()).partition_by(
        ["station_no", "route", "parameterName", "tsName"], as_dict=True
    )
    for (station, route, parameter, name), rows in groups.items():
        series = source_series(
            station,
            route,
            parameter,
            name,
            units=tuple(rows["unitSymbol"].to_list()),
            evidence=evidence,
            temporal_evidence="catalogue:ch_foen:source.product.temporal_meaning",
            origin="catalogue",
        )
        descriptions.append(
            SourceDescription(
                product_id=series.product_id,
                station_id=station,
                identity_key=(route, parameter, name),
                native_coordinate=parameter,
                identity=series.identity,
                variant=series.variant,
                facts=series.facts,
            )
        )
    return SourceDescriptions(provider_id="ch_foen", descriptions=tuple(descriptions))


def catalogue_tables(
    native: NativeTable, associations: pl.DataFrame, *, checked_on: date
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build offline tables without expanding station lists into known series.

    Product rows describe access routes. Series descriptions carry physical intervals
    because exceptions prevent a route-wide temporal classification.
    Station-product rows distinguish positive witnesses from unresolved pairs.
    Unknown pairs carry incomplete inventory, never fabricated source series.
    Sample timestamps never populate published record boundaries.
    """
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("ch_foen").alias("provider_id"),
        pl.col("no").alias("station_id"),
        "latitude",
        "longitude",
        pl.lit("EPSG:4326").alias("crs"),
    ).sort("station_id")
    products = pl.DataFrame(
        [
            {
                "provider_id": "ch_foen",
                "product_id": product_id(route, parameter),
                "observed_property": quantity,
                "frequency": "unknown",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": {"Q": "m3/s", "W": "m", "WT": "degC"}[parameter],
                "native_id": f"{route}:{parameter}",
            }
            for route in (*ARCHIVE_ROUTES, "data_live")
            for parameter, (quantity, _) in PARAMETERS.items()
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("product_id")
    if not set(associations["station_no"]) <= set(stations["station_id"]):
        raise FatalContractError("Observed association is absent from the station snapshot")
    observed = {
        (station, product_id(route, parameter))
        for station, route, parameter in associations.select("station_no", "route", "parameterName")
        .unique()
        .iter_rows()
    }
    pairs = pl.DataFrame(
        [
            {
                "provider_id": "ch_foen",
                "station_id": station,
                "product_id": product,
                "availability": "available" if (station, product) in observed else "unknown",
                "availability_reason": (
                    "Observed source association; sampled inventory is incomplete"
                    if (station, product) in observed
                    else "No association established in selected samples; availability remains unknown"
                ),
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": checked_on,
            }
            for station in stations["station_id"]
            for product in products["product_id"]
        ],
        schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema,
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


LIVE_PARAMETER_LABELS = {"Q": "Discharge", "W": "Water level", "WT": "Temperature"}


def recent_associations(
    payload: Mapping[str, object], *, station_numbers: set[str], station_units: Mapping[str, Mapping[str, str]]
) -> pl.DataFrame:
    """Bind recent witnesses to independently selected station-page unit labels.

    Missing page labels remain unknown, never borrowed from archive observations.
    The recent feed publishes no raw series name; its parameter is the identity.
    """
    rows = []
    for row in _response_rows(payload, "data_live"):
        station, parameter = row.get("stationNo"), row.get("parameterName")
        if not isinstance(station, str) or station not in station_numbers:
            raise FatalContractError("Recent association station is absent from the station snapshot")
        if not isinstance(parameter, str) or parameter not in LIVE_PARAMETER_LABELS:
            raise FatalContractError("Recent association has an unsupported source parameter")
        label = LIVE_PARAMETER_LABELS[parameter]
        unit = station_units.get(station, {}).get(label)
        rows.append(
            {
                "station_no": station,
                "station_id": None,
                "route": "data_live",
                "parameterName": parameter,
                "tsName": None,
                "unitName": None,
                "unitSymbol": unit,
            }
        )
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA).unique().sort(ASSOCIATION_SCHEMA.names())


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it.

    The private source verifier owns original receipt interpretation, including
    final page URL checks. This boundary checks the selected member bytes and
    declared recording identity; it does not discover files or make requests.
    """
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("Swiss original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("Swiss original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


@dataclass(frozen=True)
class GeneratedChFoenCatalogue:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance
    source_descriptions: SourceDescriptions
    station_metadata: pl.DataFrame | None = None


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
    station_metadata: pl.DataFrame | None = None,
) -> GeneratedChFoenCatalogue:
    """Assemble an official catalogue from selected source-backed associations.

    No observation service is contacted. Source descriptions remain scoped to
    witnessed station identities, while unknown station-product inventory stays
    open. Metadata must be separately verified and approved before publication.
    """
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("ch_foen"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "ch_foen":
        raise FatalContractError("Official catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "ch_foen",
        "name": "Swiss Federal Office for the Environment FOEN / BAFU",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedChFoenCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_associations(associations, evidence="catalogue:ch_foen:source.station_product.source_associations"),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedChFoenCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate tables through the shared evidence-aware publication path.

    Inputs must already be explicitly selected and verified. This writes public
    candidate products, never source bodies or restricted acquisition receipts.
    It does not authorize disclosure or replace genuine-input verification.
    """
    import json
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.ch_foen.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_NOTICE,
    )

    files = {
        "provider.json": (json.dumps(catalogue.provider_info, sort_keys=True, separators=(",", ":")) + "\n").encode()
    }
    for name, frame in (
        ("products", catalogue.products),
        ("stations", catalogue.stations),
        ("station_products", catalogue.station_products),
    ):
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[f"{name}.parquet"] = buffer.getvalue()
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        files,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=metadata_fields,
        station_metadata=catalogue.station_metadata,
        metadata_implementation=(
            "src/rivretrieve/_internal/providers/ch_foen/station_metadata.py",
            "project_official_station_metadata",
        )
        if catalogue.station_metadata is not None
        else None,
        station_metadata_notice=STATION_METADATA_NOTICE,
        source_descriptions=catalogue.source_descriptions,
    )
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {**files, **metadata}.items():
        (output / name).write_bytes(content)


@dataclass(frozen=True)
class CatalogueSources:
    native_table: NativeTable
    associations: pl.DataFrame
    provenance: AcquisitionProvenance
    station_metadata: pl.DataFrame
    checked_on: date


def read_catalogue_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> CatalogueSources:
    """Read an explicitly selected offline build after exact member verification.

    The reviewed declaration selects successful association samples and valid
    station pages. Failed, overflowing and redirected captures stay retained
    evidence, never negative availability or substitute station identities.
    """
    import json

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.ch_foen import origins
    from rivretrieve._internal.providers.ch_foen.station_metadata import (
        parse_live_sensor_units,
        project_official_station_metadata,
        project_station_metadata,
        read_station_metadata_sources,
    )

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("Swiss selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if native_path not in selected:
        raise FatalContractError("Swiss native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    station_captures = [item for item in selection["captures"] if item["kind"] == "stations"]
    if len(station_captures) != 1:
        raise FatalContractError("Swiss selection requires one station snapshot")
    recordings = []

    def body(capture):
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("Swiss selected body disagrees with recording identity")
        recordings.append(reference)
        return read_original(evidence_root, reference, input_receipt=input_receipt)

    station_capture = station_captures[0]
    snapshot = station_native_table(
        json.loads(body(station_capture)), retrieved_at=RetrievedAt(recordings[-1].retrieved_at)
    )
    if not native.data.equals(snapshot.data):
        raise FatalContractError("Swiss selected native table differs from original station snapshot")
    numbers = set(native.data["no"])
    units = {}
    for capture in selection["captures"]:
        if capture["kind"] == "page" and capture["outcome"] == "station_page":
            content = body(capture)
            url = recordings[-1].source_url
            prefix = "https://www.hydrodaten.admin.ch/en/seen-und-fluesse/stations/"
            if not url.startswith(prefix) or url.removeprefix(prefix) not in numbers:
                raise FatalContractError("Swiss selected page URL has no matching station identity")
            station = url.removeprefix(prefix)
            units[station] = parse_live_sensor_units(content, station)
    associations = []
    for capture in selection["captures"]:
        if capture["kind"] == "archive" and capture["outcome"] in {"rows", "empty"}:
            payload = json.loads(body(capture))
            for route in capture["routes"]:
                associations.append(archive_associations(payload, route=route, station_numbers=numbers))
    associations.append(
        recent_associations(json.loads(body(selection["prior_live"])), station_numbers=numbers, station_units=units)
    )
    for capture in selection["prior_support"]:
        body(capture)
    observed = pl.concat(associations).unique().sort(ASSOCIATION_SCHEMA.names())
    provenance = origins.build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=selection["native_revision"],
            sha256=member.sha256,
            byte_size=member.byte_size,
        ),
        tuple(recordings),
        acquisitions=tuple(AcquisitionRecord.model_validate(item) for item in selection["publication_acquisitions"]),
        source_bindings=tuple(FactBinding.model_validate(item) for item in selection["source_bindings"]),
        statements=tuple(SourceStatement.model_validate(item) for item in selection["statements"]),
    )
    baseline = read_station_metadata_sources(
        evidence_root,
        directory_reference=origins.STATION_DIRECTORY_REFERENCE,
        input_receipt=input_receipt,
        page_root=origins.STATION_PAGE_ROOT,
        manifest_sha256=origins.STATION_PAGE_MANIFEST_SHA256,
    )
    provenance = origins.with_station_metadata_sources(provenance, baseline.page_recordings)
    checked_on = date.fromisoformat(selection["checked_on"])
    _, stations, _ = catalogue_tables(native, observed, checked_on=checked_on)
    supplementary = project_station_metadata(
        stations,
        baseline.directory_body,
        {station: content for station, content in baseline.station_pages.items() if station in numbers},
        origins.STATION_REFERENCE_METADATA_FIELDS,
    )
    metadata = project_official_station_metadata(native, stations, supplementary)
    return CatalogueSources(native, observed, provenance, metadata, checked_on)


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected acquisition receipts with the facts of their original bodies.

    ``selection`` must be the digest-verified authored declaration used for the
    build. Only receipts of recordings adopted in provenance enter build support.
    """
    captures = [*selection["captures"], selection["prior_live"], *selection["prior_support"]]
    receipt_by_body = {capture["body"]: capture["receipt"] for capture in captures}
    facts_by_acquisition = {
        (source.source_id, acquisition.acquisition_id): tuple(
            fact
            for binding in provenance.fact_bindings
            if binding.source_id == source.source_id and binding.acquisition_id == acquisition.acquisition_id
            for fact in binding.facts
        )
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    result = {}
    for source in provenance.source_records:
        paths = {item.recording.recording_id: item.recording.repository_path for item in source.evidence}
        for acquisition in source.acquisitions:
            facts = facts_by_acquisition[(source.source_id, acquisition.acquisition_id)]
            for recording_id in acquisition.recording_ids:
                path = paths[recording_id]
                if path in receipt_by_body and facts:
                    result[receipt_by_body[path]] = facts
    return result


def main(argv: list[str] | None = None) -> int:
    """Compose a selected, offline official catalogue candidate outside source checkouts."""
    import argparse

    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", default="maintenance/catalogue/ch_foen/official/selection.json")
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--build-inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("Swiss catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("Swiss catalogue output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    sources = read_catalogue_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
    catalogue = build_catalogue(
        sources.native_table,
        STATION_CATALOGUE_ORIGINS,
        associations=sources.associations,
        checked_on=sources.checked_on,
        provenance=sources.provenance,
        station_metadata=sources.station_metadata,
    )
    write_catalogue(
        catalogue,
        output,
        build_inputs=CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes()),
        native_table=sources.native_table,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
