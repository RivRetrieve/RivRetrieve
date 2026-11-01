"""Offline transformations of Austria eHYD station registries and product witnesses."""

import io
import json
import math
import zipfile
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

STANDING_WATER_BODIES = frozenset({"Hinterer Gosausee", "Alte Donau"})

IN_SCOPE_OWF_FTYPES = {
    "owf_abfl_tagesmittel": ("Q-Tagesmittel", "m³/s"),
    "owf_abfl_monatsminima": ("Q-Monatsminima", "m³/s"),
    "owf_abfl_monatsmaxima": ("Q-Monatsmaxima", "m³/s"),
    "owf_wasserst_tagesmittel": ("W-Tagesmittel", "cm"),
    "owf_wasserst_monatsminima": ("W-Monatsminima", "cm"),
    "owf_wasserst_monatsmaxima": ("W-Monatsmaxima", "cm"),
    "owf_wassertemp_monatsmittel": ("WT-Monatsmittel", "°C"),
}

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "hzbnr": pl.String,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "owf_latitude": pl.Float64,
        "owf_longitude": pl.Float64,
        "pegel_aktuell_latitude": pl.Float64,
        "pegel_aktuell_longitude": pl.Float64,
        "in_owf": pl.Boolean,
        "in_pegel_aktuell": pl.Boolean,
        "name": pl.String,
        "gewaesser": pl.String,
        "messstellenart": pl.String,
        "dienststelle": pl.String,
        "errichtet": pl.Int64,
        "aufgelassen": pl.Int64,
        "orogr.Einzugsgebiet [km²]": pl.String,
        "messstelle": pl.String,
        "gewasser": pl.String,
        "hd": pl.String,
    }
)

ASSOCIATION_SCHEMA = pl.Schema(dict.fromkeys(("station_id", "subsystem", "variable", "unit"), pl.String))


def _mapping(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise FatalContractError(message)
    return cast("dict[str, object]", value)


def _features(payload: Mapping[str, object], label: str) -> list[dict[str, object]]:
    features = payload.get("features")
    if not isinstance(features, list) or not features or any(not isinstance(item, dict) for item in features):
        raise FatalContractError(f"eHYD {label} payload must contain a non-empty GeoJSON features list")
    return cast("list[dict[str, object]]", features)


def _point_lon_lat(feature: Mapping[str, object], label: str) -> tuple[float, float]:
    geom = _mapping(feature.get("geometry"), f"eHYD {label} feature must carry a GeoJSON Point geometry")
    if geom.get("type") != "Point":
        raise FatalContractError(f"eHYD {label} feature must carry a GeoJSON Point geometry")
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        raise FatalContractError(f"eHYD {label} Point geometry requires longitude and latitude")
    lon, lat = coords[0], coords[1]
    if (
        isinstance(lon, bool)
        or isinstance(lat, bool)
        or not isinstance(lon, int | float)
        or not isinstance(lat, int | float)
        or not math.isfinite(float(lon))
        or not math.isfinite(float(lat))
    ):
        raise FatalContractError(f"eHYD {label} Point coordinates must be finite numbers")
    return float(lon), float(lat)


def _parse_stammdaten(raw: bytes, expected_hzb: str) -> tuple[str, bool]:
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError as error:
        raise FatalContractError("eHYD Stammdaten CSV is not valid Windows-1252 text") from error
    hzb: str | None = None
    ezg: str | None = None
    has_seeflaeche = False
    for line in text.splitlines():
        if "Seefläche" in line:
            has_seeflaeche = True
        parts = [part.strip() for part in line.split(";")]
        if line.startswith("HZB-Nummer:") and len(parts) > 1:
            hzb = parts[1]
        elif line.startswith("orogr.Einzugsgebiet") and len(parts) > 1:
            ezg = parts[1]
    if hzb != expected_hzb or not ezg:
        raise FatalContractError("eHYD Stammdaten CSV lacks matching HZB-Nummer or orogr.Einzugsgebiet")
    return ezg, has_seeflaeche


def _parse_owf_unit(raw: bytes) -> str | None:
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError as error:
        raise FatalContractError("eHYD owf series CSV is not valid Windows-1252 text") from error
    for line in text.splitlines()[:40]:
        if line.startswith("Einheit:"):
            value = line.split(";", 1)[1].strip() if ";" in line else line.split(":", 1)[1].strip()
            while value.startswith("[") and value.endswith("]"):
                value = value[1:-1].strip()
            return value or None
    raise FatalContractError("eHYD owf series CSV lacks an Einheit header line")


def _validate_row_types(values: dict[str, object]) -> None:
    for name, dtype in STATION_SOURCE_SCHEMA.items():
        value = values[name]
        if value is None:
            continue
        if (
            (dtype == pl.String and not isinstance(value, str))
            or (dtype == pl.Boolean and not isinstance(value, bool))
            or (dtype == pl.Int64 and type(value) is not int)
            or (dtype == pl.Float64 and (isinstance(value, bool) or not isinstance(value, int | float)))
        ):
            raise FatalContractError(f"eHYD native station field {name!r} has an invalid scalar type")


def station_native_table(
    lfrz_owf: Mapping[str, object],
    ehyd_owf: Mapping[str, object],
    ehyd_pa: Mapping[str, object],
    zip_bytes: bytes,
    *,
    lfrz_pa: Mapping[str, object],
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Reconcile river gauges across owf and Pegel Aktuell while excluding standing-water lakes.

    Authoritative CRS84 coordinates from ``i000501:messstellen_owf`` take precedence
    for ``owf`` gauges; ``i000501:pegel_aktuell`` supplies coordinates for telemetry-only
    river gauges absent from ``owf``. Both source coordinate pairs are retained
    separately, with nulls where a station is absent from an endpoint. Telemetry station names
    and water-body names remain sourced from eHYD. Standing-water lakes (gauges
    without discharge carrying ``Seefläche``, ``(Seepegel)``, or impounded lake bodies) are excluded.
    Decommissioned ``owf`` river gauges remain in scope.
    """
    fjson_by_hzb: dict[str, list[dict[str, object]]] = {}
    for feature in _features(ehyd_owf, "ehyd_messstellen_owf"):
        props = _mapping(feature.get("properties"), "eHYD Messstellen owf feature requires properties")
        hzb = props.get("hzbnr01")
        raw_fjson = props.get("fjson")
        if not isinstance(hzb, str) or not hzb.strip() or hzb in fjson_by_hzb or not isinstance(raw_fjson, str):
            raise FatalContractError("eHYD Messstellen owf requires unique string hzbnr01 and fjson")
        entries = json.loads(raw_fjson)
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            raise FatalContractError("eHYD Messstellen fjson must be a JSON array of objects")
        fjson_by_hzb[hzb] = cast("list[dict[str, object]]", entries)

    lfrz_by_hzb: dict[str, tuple[float, float, dict[str, object]]] = {}
    for feature in _features(lfrz_owf, "lfrz_messstellen_owf"):
        props = _mapping(feature.get("properties"), "LFRZ messstellen_owf feature requires properties")
        hzb = props.get("hzbnr")
        if not isinstance(hzb, str) or not hzb.strip() or hzb in lfrz_by_hzb:
            raise FatalContractError("LFRZ messstellen_owf requires unique nonblank string hzbnr")
        lon, lat = _point_lon_lat(feature, "lfrz_messstellen_owf")
        lfrz_by_hzb[hzb] = (lon, lat, props)

    if set(lfrz_by_hzb) != set(fjson_by_hzb):
        raise FatalContractError("LFRZ messstellen_owf and eHYD Messstellen owf disagree on station identities")

    lake_owf: set[str] = set()
    selected: dict[str, dict[str, object]] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as error:
        raise FatalContractError("eHYD national owf archive is not a valid ZIP file") from error

    with archive:
        members = set(archive.namelist())
        for hzb, (lon, lat, props) in lfrz_by_hzb.items():
            stamm_member = f"Stammdaten/Stammdaten-{hzb}.csv"
            if stamm_member not in members:
                raise FatalContractError(f"eHYD national owf archive lacks {stamm_member}")
            ezg, has_seeflaeche = _parse_stammdaten(archive.read(stamm_member), hzb)
            entries = fjson_by_hzb[hzb]
            has_q = any(
                isinstance(entry.get("ftyp"), str) and str(entry["ftyp"]).startswith("owf_abfl_") for entry in entries
            )
            name = props.get("name")
            gewaesser = props.get("gewaesser")
            if not isinstance(name, str) or not name.strip() or not isinstance(gewaesser, str) or not gewaesser.strip():
                raise FatalContractError("LFRZ messstellen_owf requires nonblank name and gewaesser strings")
            is_lake = (not has_q) and (has_seeflaeche or "(Seepegel)" in name or gewaesser in STANDING_WATER_BODIES)
            if is_lake:
                lake_owf.add(hzb)
                continue
            row: dict[str, object] = {
                "hzbnr": hzb,
                "latitude": lat,
                "longitude": lon,
                "owf_latitude": lat,
                "owf_longitude": lon,
                "pegel_aktuell_latitude": None,
                "pegel_aktuell_longitude": None,
                "in_owf": True,
                "in_pegel_aktuell": False,
                "name": name,
                "gewaesser": gewaesser,
                "messstellenart": props.get("messstellenart"),
                "dienststelle": props.get("dienststelle"),
                "errichtet": props.get("errichtet"),
                "aufgelassen": props.get("aufgelassen"),
                "orogr.Einzugsgebiet [km²]": ezg,
                "messstelle": None,
                "gewasser": None,
                "hd": None,
            }
            _validate_row_types(row)
            selected[hzb] = row

    pa_coordinates: dict[str, tuple[float, float]] = {}
    for feature in _features(lfrz_pa, "lfrz_pegel_aktuell"):
        props = _mapping(feature.get("properties"), "LFRZ pegel_aktuell feature requires properties")
        raw_hzb = props.get("hzbnr")
        if type(raw_hzb) is not int and (not isinstance(raw_hzb, str) or not raw_hzb.strip()):
            raise FatalContractError("LFRZ pegel_aktuell requires integer or nonblank string hzbnr")
        hzb = str(raw_hzb).strip()
        if hzb in pa_coordinates:
            raise FatalContractError("LFRZ pegel_aktuell contains duplicate station identities")
        pa_coordinates[hzb] = _point_lon_lat(feature, "lfrz_pegel_aktuell")

    seen_pa: set[str] = set()
    for feature in _features(ehyd_pa, "ehyd_pegel_aktuell"):
        props = _mapping(feature.get("properties"), "eHYD PegelAktuell feature requires properties")
        raw_hzb = props.get("hzbnr")
        if type(raw_hzb) is not int and (not isinstance(raw_hzb, str) or not raw_hzb.strip()):
            raise FatalContractError("eHYD PegelAktuell requires integer or nonblank string hzbnr")
        hzb = str(raw_hzb).strip()
        if hzb in seen_pa:
            raise FatalContractError("eHYD PegelAktuell contains duplicate station identities")
        seen_pa.add(hzb)
        if hzb not in pa_coordinates:
            raise FatalContractError("LFRZ and eHYD Pegel Aktuell disagree on station identities")
        lon, lat = pa_coordinates[hzb]
        messstelle = props.get("messstelle")
        gewasser = props.get("gewasser")
        hd = props.get("hd")
        if (
            not isinstance(messstelle, str)
            or not messstelle.strip()
            or not isinstance(gewasser, str)
            or not gewasser.strip()
            or (hd is not None and not isinstance(hd, str))
        ):
            raise FatalContractError("eHYD PegelAktuell requires nonblank messstelle and gewasser strings")
        if hzb in lake_owf:
            continue
        if hzb in selected:
            selected[hzb]["pegel_aktuell_latitude"] = lat
            selected[hzb]["pegel_aktuell_longitude"] = lon
            selected[hzb]["in_pegel_aktuell"] = True
            selected[hzb]["messstelle"] = messstelle
            selected[hzb]["gewasser"] = gewasser
            selected[hzb]["hd"] = hd
            _validate_row_types(selected[hzb])
        else:
            if "(Seepegel)" in messstelle or gewasser in STANDING_WATER_BODIES:
                raise FatalContractError("Unclassified standing-water telemetry gauge outside owf")
            row = {
                "hzbnr": hzb,
                "latitude": lat,
                "longitude": lon,
                "owf_latitude": None,
                "owf_longitude": None,
                "pegel_aktuell_latitude": lat,
                "pegel_aktuell_longitude": lon,
                "in_owf": False,
                "in_pegel_aktuell": True,
                "name": None,
                "gewaesser": None,
                "messstellenart": None,
                "dienststelle": None,
                "errichtet": None,
                "aufgelassen": None,
                "orogr.Einzugsgebiet [km²]": None,
                "messstelle": messstelle,
                "gewasser": gewasser,
                "hd": hd,
            }
            _validate_row_types(row)
            selected[hzb] = row

    if seen_pa != set(pa_coordinates):
        raise FatalContractError("LFRZ and eHYD Pegel Aktuell disagree on station identities")

    frame = pl.DataFrame(list(selected.values()), schema=STATION_SOURCE_SCHEMA).sort("hzbnr")
    return stamp_native_table(frame, retrieved_at)


def owf_associations(
    ehyd_owf: Mapping[str, object],
    zip_bytes: bytes,
    *,
    station_ids: set[str],
) -> pl.DataFrame:
    """Witness in-scope owf discharge, water-level, and water-temperature series from ZIP headers.

    Out-of-scope sediment products and malformed series with empty ``Einheit: []``
    headers establish no canonical product association. Observation timestamps and
    values are never copied into the catalogue.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as error:
        raise FatalContractError("eHYD national owf archive is not a valid ZIP file") from error

    rows: list[tuple[str, str, str, str]] = []
    with archive:
        members = set(archive.namelist())
        for feature in _features(ehyd_owf, "ehyd_messstellen_owf"):
            props = _mapping(feature.get("properties"), "eHYD Messstellen owf feature requires properties")
            hzb = props.get("hzbnr01")
            raw_fjson = props.get("fjson")
            if not isinstance(hzb, str) or not isinstance(raw_fjson, str):
                raise FatalContractError("eHYD Messstellen owf requires string hzbnr01 and fjson")
            if hzb not in station_ids:
                continue
            entries = json.loads(raw_fjson)
            if not isinstance(entries, list):
                raise FatalContractError("eHYD Messstellen fjson must be a JSON array")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise FatalContractError("eHYD Messstellen fjson entry must be an object")
                ftyp = entry.get("ftyp")
                if ftyp not in IN_SCOPE_OWF_FTYPES:
                    continue
                filename = entry.get("file")
                if entry.get("hzbnr") != hzb or not isinstance(filename, str) or not filename:
                    raise FatalContractError("eHYD Messstellen fjson entry disagrees with station identity")
                folder, expected_unit = IN_SCOPE_OWF_FTYPES[str(ftyp)]
                member_name = f"{folder}/{filename}"
                if member_name not in members:
                    raise FatalContractError(f"eHYD national owf archive lacks {member_name}")
                unit = _parse_owf_unit(archive.read(member_name))
                if unit is None:
                    continue
                if unit != expected_unit:
                    raise FatalContractError(f"Unsupported eHYD owf unit {unit!r} for {ftyp}")
                rows.append((hzb, "owf", str(ftyp), unit))
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA, orient="row").unique().sort(ASSOCIATION_SCHEMA.names())


def pegel_aktuell_associations(
    raw_bytes: bytes,
    *,
    kind: str,
    station: str,
    station_ids: set[str],
) -> pl.DataFrame:
    """Witness Pegel Aktuell Diagram series without turning empty 0-byte outages into unavailability.

    Excluded lake gauges (including ``m ü.A`` lake levels) are structurally checked
    and omitted from canonical river associations; river gauges require ``m³/s`` or ``cm``.
    """
    if kind not in {"pegel_bgis", "pegel_longterm"}:
        raise FatalContractError(f"Unsupported Pegel Aktuell Diagram capture kind: {kind!r}")
    if not raw_bytes:
        if kind == "pegel_bgis":
            return pl.DataFrame(schema=ASSOCIATION_SCHEMA)
        raise FatalContractError("pegelLongterm capture cannot be empty")
    try:
        doc = json.loads(raw_bytes)
    except ValueError as error:
        raise FatalContractError("Pegel Aktuell Diagram body is not valid JSON") from error
    if not isinstance(doc, dict):
        raise FatalContractError("Pegel Aktuell Diagram body must be a JSON object")
    if (
        kind == "pegel_longterm"
        and set(doc)
        == {
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
        and all(value == [] for value in doc.values())
    ):
        return pl.DataFrame(schema=ASSOCIATION_SCHEMA)
    if kind == "pegel_bgis" and str(doc.get("hzbnr")) != station:
        raise FatalContractError("pegelBgis response station identity differs from requested station")
    parameter = doc.get("parameter")
    unit = doc.get("einheit")
    if parameter not in {"Abfluss", "Wasserstand"} or not isinstance(unit, str) or not unit.strip():
        raise FatalContractError("Pegel Aktuell Diagram has an unsupported parameter or unit")
    if station not in station_ids:
        if (parameter == "Abfluss" and unit != "m³/s") or (parameter == "Wasserstand" and unit not in {"cm", "m ü.A"}):
            raise FatalContractError("Excluded Pegel Aktuell lake capture has an unrecognized unit")
        return pl.DataFrame(schema=ASSOCIATION_SCHEMA)
    if (parameter == "Abfluss" and unit != "m³/s") or (parameter == "Wasserstand" and unit != "cm"):
        raise FatalContractError(f"In-scope Pegel Aktuell river gauge {station} has unsupported unit {unit!r}")
    return pl.DataFrame([(station, kind, str(parameter), unit)], schema=ASSOCIATION_SCHEMA, orient="row")


def association_product(subsystem: str, variable: str) -> str:
    if subsystem == "owf":
        return variable
    return f"{subsystem}_{variable.lower()}"


def _quantity_and_canonical_unit(unit: str) -> tuple[str, str, str]:
    if unit == "m³/s":
        return "discharge", "m3/s", "m3/s"
    if unit == "cm":
        return "stage", "m", "cm"
    if unit == "°C":
        return "temperature", "degC", "degC"
    raise FatalContractError(f"Unsupported eHYD source unit: {unit!r}")


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build witnessed eHYD product candidates and leave unestablished pairs unknown."""
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("at_ehyd").alias("provider_id"),
        pl.col("hzbnr").alias("station_id"),
        pl.col("latitude").cast(pl.Float64),
        pl.col("longitude").cast(pl.Float64),
        pl.lit("EPSG:4326").alias("crs"),
    ).sort("station_id")
    if not set(associations["station_id"]) <= set(stations["station_id"]):
        raise FatalContractError("eHYD association references a station absent from canonical river scope")
    product_rows = []
    for subsystem, variable, unit in (
        associations.select("subsystem", "variable", "unit").unique().sort("subsystem", "variable", "unit").iter_rows()
    ):
        observed_property, canonical_unit, _ = _quantity_and_canonical_unit(unit)
        product_rows.append(
            {
                "provider_id": "at_ehyd",
                "product_id": association_product(subsystem, variable),
                "observed_property": observed_property,
                "frequency": "unknown",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": canonical_unit,
                "native_id": f"{subsystem}:{variable}:{unit}",
            }
        )
    products = pl.DataFrame(product_rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")
    observed = {
        (station, association_product(subsystem, variable))
        for station, subsystem, variable, _ in associations.iter_rows()
    }
    pairs = pl.DataFrame(
        [
            {
                "provider_id": "at_ehyd",
                "station_id": station,
                "product_id": product,
                "availability": "available" if (station, product) in observed else "unknown",
                "availability_reason": (
                    "Witnessed in retained official eHYD source; temporal coverage bounds remain unestablished"
                    if (station, product) in observed
                    else "No in-scope series witnessed in retained official eHYD snapshot"
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


def describe_associations(associations: pl.DataFrame) -> SourceDescriptions:
    """Describe witnessed eHYD source identities with established physical units and gauge-zero reference."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
    from rivretrieve._internal.source_series import EvidenceFact, PhysicalFacts, SourceIdentity, known, stable_id

    grouped: dict[tuple[str, str, str], list[str]] = {}
    for station, subsystem, variable, unit in associations.unique().sort(ASSOCIATION_SCHEMA.names()).iter_rows():
        grouped.setdefault((subsystem, variable, unit), []).append(station)

    descriptions = []
    for (subsystem, variable, unit), station_list in sorted(grouped.items()):
        evidence = (
            "catalogue:at_ehyd:source.station_product.owf_associations"
            if subsystem == "owf"
            else "catalogue:at_ehyd:source.station_product.pegel_aktuell_associations"
        )
        quantity, _, normalized_unit = _quantity_and_canonical_unit(unit)
        vertical_ref = (
            known("gauge_zero", "catalogue:at_ehyd:source.station.pegelnullpunkt_definition")
            if unit == "cm"
            else EvidenceFact()
        )
        facts = PhysicalFacts(
            facts_id="pending",
            quantity=known(quantity, evidence),
            source_unit=known(unit, evidence),
            normalized_unit=normalized_unit,
            vertical_reference=vertical_ref,
        )
        facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
        descriptions.append(
            SourceDescription(
                product_id=association_product(subsystem, variable),
                station_ids=tuple(sorted(station_list)),
                identity_key=(subsystem, variable, unit),
                native_coordinate=variable,
                identity=SourceIdentity(
                    namespace=f"ehyd.{subsystem}",
                    published_id=variable,
                    origin="catalogue",
                    evidence=(evidence,),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="at_ehyd", descriptions=tuple(descriptions))


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("eHYD original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("eHYD original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("eHYD selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("eHYD selection requires explicit captures")
    return selection


def _selected_native(evidence_root: Path, selection: dict, input_receipt: RetainedInputReceipt) -> NativeTable:
    required_kinds = {
        "lfrz_messstellen_owf",
        "ehyd_messstellen_owf",
        "lfrz_pegel_aktuell",
        "ehyd_pegel_aktuell",
        "owf_national_archive",
    }
    raw_by_kind: dict[str, bytes] = {}
    registry_times = []
    for capture in selection["captures"]:
        kind = capture["kind"]
        if kind not in required_kinds:
            continue
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("eHYD selected body disagrees with recording identity")
        if kind in raw_by_kind:
            raise FatalContractError(f"eHYD selection requires exactly one {kind} snapshot")
        raw_by_kind[kind] = read_original(evidence_root, reference, input_receipt=input_receipt)
        registry_times.append(reference.retrieved_at)
    if set(raw_by_kind) != required_kinds:
        raise FatalContractError("eHYD selection lacks required registry or archive snapshots")
    lfrz_owf = json.loads(raw_by_kind["lfrz_messstellen_owf"])
    ehyd_owf = json.loads(raw_by_kind["ehyd_messstellen_owf"])
    lfrz_pa = json.loads(raw_by_kind["lfrz_pegel_aktuell"])
    ehyd_pa = json.loads(raw_by_kind["ehyd_pegel_aktuell"])
    if not all(isinstance(doc, dict) for doc in (lfrz_owf, ehyd_owf, lfrz_pa, ehyd_pa)):
        raise FatalContractError("eHYD registry JSON captures must be GeoJSON objects")
    return station_native_table(
        lfrz_owf,
        ehyd_owf,
        ehyd_pa,
        raw_by_kind["owf_national_archive"],
        lfrz_pa=lfrz_pa,
        retrieved_at=RetrievedAt(max(registry_times)),
    )


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive native eHYD river station rows from verified selected originals."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    return _selected_native(evidence_root, selection, input_receipt)


@dataclass(frozen=True)
class GeneratedEhydCatalogue:
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
) -> GeneratedEhydCatalogue:
    """Assemble the official Austria eHYD offline station and product catalogue."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("at_ehyd"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "at_ehyd":
        raise FatalContractError("Official eHYD catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "at_ehyd",
        "name": "Electronic Hydrographic Data Austria (eHYD)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedEhydCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_associations(associations),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedEhydCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.at_ehyd.origins import (
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
            "src/rivretrieve/_internal/providers/at_ehyd/station_metadata.py",
            "project_station_metadata",
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
    """Recompute native rows and product witnesses from verified selected originals."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.at_ehyd.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.at_ehyd.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if not isinstance(native_path, str) or native_path not in selected:
        raise FatalContractError("eHYD native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    reconstructed = _selected_native(evidence_root, selection, input_receipt)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("eHYD retained native differs from selected original reconstruction")

    identities = set(native.data["hzbnr"])
    recordings: list[RecordingReference] = []
    associations: list[pl.DataFrame] = []
    ehyd_owf_doc: dict[str, object] | None = None
    owf_zip_bytes: bytes | None = None

    for capture in selection["captures"]:
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("eHYD selected body disagrees with recording identity")
        content = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        kind = capture["kind"]
        if kind == "ehyd_messstellen_owf":
            ehyd_owf_doc = json.loads(content)
        elif kind == "owf_national_archive":
            owf_zip_bytes = content
        elif kind in {"pegel_bgis", "pegel_longterm"}:
            associations.append(
                pegel_aktuell_associations(
                    content,
                    kind=kind,
                    station=capture["station"],
                    station_ids=identities,
                )
            )
        elif kind == "lfrz_collections":
            collections = {c["id"]: c for c in json.loads(content).get("collections", ())}
            for cid in ("i000501:messstellen_owf", "i000501:pegel_aktuell"):
                if collections.get(cid, {}).get("storageCrs") != "http://www.opengis.net/def/crs/OGC/1.3/CRS84":
                    raise FatalContractError("LFRZ collection storageCrs does not establish CRS84")

    if ehyd_owf_doc is None or owf_zip_bytes is None:
        raise FatalContractError("eHYD selection lacks owf registry or national archive")
    associations.append(owf_associations(ehyd_owf_doc, owf_zip_bytes, station_ids=identities))

    observed = (
        pl.concat(associations).unique().sort(ASSOCIATION_SCHEMA.names())
        if associations
        else pl.DataFrame(schema=ASSOCIATION_SCHEMA)
    )
    provenance = build_acquisition_provenance(
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
    checked_on = date.fromisoformat(selection["checked_on"])
    _, stations, _ = catalogue_tables(native, observed, checked_on=checked_on)
    return CatalogueSources(native, observed, provenance, project_station_metadata(native, stations), checked_on)


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected acquisition receipts with the facts of their original bodies."""
    captures = selection["captures"]
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
    result: dict[str, tuple[str, ...]] = {}
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
    """Compose a derived native candidate or runtime catalogue outside source checkouts."""
    import argparse

    from rivretrieve._internal.catalogues.native import write_native_table

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("eHYD output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("eHYD output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.at_ehyd.origins import (
            STATION_CATALOGUE_ORIGINS,
            STATION_METADATA_FIELDS,
        )

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
