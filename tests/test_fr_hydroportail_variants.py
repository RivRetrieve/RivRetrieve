"""Public HydroPortail selector contracts; authored protocol controls are synthetic."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import SourceCoordinates
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.providers.fr_hydroportail.config import config
from rivretrieve._internal.providers.fr_hydroportail.parse import parse
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from tests._recorded_payload import recorded_payload

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

VARIANTS = {"raw", "validated", "pre_validated_and_validated", "most_valid"}


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
def test_public_discovery_exposes_all_source_variants(quantity):
    selection = rr.find(provider="fr_hydroportail", station="Y251002001", quantity=quantity, statistic="instantaneous")
    assert set(rr.series(selection)["variant"].to_list()) == VARIANTS
    for variant in VARIANTS:
        assert rr.series(rr.pick(selection, variant=variant))["variant"].to_list() == [variant]


class SyntheticVariantTransport:
    """Authored protocol edge cases, not recordings or historical availability evidence."""

    def __init__(self, retained_evidence_root, *, empty=(), failed=(), mutation=None):
        self.retained_evidence_root = retained_evidence_root
        self.calls = []
        self.contents = {}
        self.empty = empty
        self.failed = failed
        self.mutation = mutation

    def send(self, request):
        params = dict(request.params)
        variant = params["hydro_series[statusData]"]
        metric = params["hydro_series[simpleAndInterpolatedAndHourlyVariable]"]
        assert variant in VARIANTS
        assert params["hydro_series[startAt]"] == "30/12/2019"
        assert params["hydro_series[endAt]"] == "04/01/2020"
        assert params["hydro_series[variableType]"] == "simple_and_interpolated_and_hourly_variable"
        assert request.url == "https://hydro.eaufrance.fr/stationhydro/ajax/Y251002001/series"
        self.calls.append(variant)
        if variant in self.failed:
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
        body = json.loads(
            (self.retained_evidence_root / "tests/test_data/fr_hydroportail_J783301020_empty.body").read_bytes()
        )
        body["series"].update(
            code="Y251002001",
            metric=metric,
            statuses=variant,
            unit="l" if metric == "Q" else "mm",
            title="Débit instantané - synthetic" if metric == "Q" else "Hauteur instantanée - synthetic",
            data=[]
            if variant in self.empty
            else [
                {"t": "2020-01-01T00:00:00Z", "v": 1000, "s": 4, "q": 0, "m": 0, "c": 0},
                {"t": "2020-01-01T00:10:00Z", "v": None, "s": 4, "q": 0, "m": 0, "c": 0},
            ],
        )
        if self.mutation:
            self.mutation(body)
        content = json.dumps(body).encode()
        self.contents[variant] = content
        return TransportResponse(
            content, 200, datetime(2026, 9, 21, tzinfo=UTC), "application/json", request.url, params
        )


def public_selection(quantity):
    return rr.find(provider="fr_hydroportail", station="Y251002001", quantity=quantity, statistic="instantaneous")


def install(monkeypatch, tmp_path, transport):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)


def retrieve(selection, **kwargs):
    return rr.fetch(selection, start="2020-01-01", end="2020-01-02", receipts=True, on_issue="ignore", **kwargs)


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.recorded("tests/test_data/fr_hydroportail_J783301020_empty.body")
def test_explicit_variant_requests_only_its_identity(retained_evidence_root, monkeypatch, tmp_path, quantity, variant):
    transport = SyntheticVariantTransport(retained_evidence_root)
    install(monkeypatch, tmp_path, transport)
    selection = rr.pick(public_selection(quantity), variant=variant)
    result = retrieve(selection)
    assert transport.calls == [variant]
    assert rr.series(result)["variant"].to_list() == [variant]
    assert result.data.height == 2
    assert result.data["value"].to_list() == [1.0, None]
    assert result.data["series_id"].n_unique() == 1
    assert result.receipts.entries[0].content == transport.contents[variant]
    assert result.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    restored = rr.from_bundle(rr.to_bundle(result))
    assert_frame_equal(restored.data, result.data)
    assert_frame_equal(rr.series(restored), rr.series(result))
    assert restored.outcomes == result.outcomes
    assert restored.inventories == result.inventories
    assert restored.receipts.entries[0].content == transport.contents[variant]


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
@pytest.mark.recorded("tests/test_data/fr_hydroportail_J783301020_empty.body")
def test_subset_cache_cannot_satisfy_all_variants_and_identical_rows_stay_distinct(
    retained_evidence_root, monkeypatch, tmp_path, quantity
):
    transport = SyntheticVariantTransport(retained_evidence_root)
    install(monkeypatch, tmp_path, transport)
    selection = public_selection(quantity)
    retrieve(rr.pick(selection, variant="raw"), cache="reuse")
    assert transport.calls == ["raw"]
    result = retrieve(selection, cache="reuse")
    assert set(transport.calls[1:]) == VARIANTS
    assert len(transport.calls) == 5
    assert result.data.height == 8
    assert result.data["series_id"].n_unique() == 4
    assert set(rr.series(result)["variant"]) == VARIANTS
    cached = retrieve(rr.pick(selection, variant="raw"), cache="reuse")
    assert len(transport.calls) == 5
    expected_raw = rr.pick(result, variant="raw", on_issue="ignore")
    assert_frame_equal(cached.data.sort(["series_id", "time"]), expected_raw.data.sort(["series_id", "time"]))
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in cached.receipts.entries)
    restored = rr.from_bundle(rr.to_bundle(result))
    assert_frame_equal(restored.data, result.data)
    assert restored.source_series == result.source_series
    assert restored.inventories == result.inventories


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
@pytest.mark.recorded("tests/test_data/fr_hydroportail_J783301020_empty.body")
def test_null_absent_empty_and_failed_variants_remain_distinct(retained_evidence_root, monkeypatch, tmp_path, quantity):
    transport = SyntheticVariantTransport(
        retained_evidence_root, empty={"validated"}, failed={"pre_validated_and_validated"}
    )
    install(monkeypatch, tmp_path, transport)
    result = retrieve(public_selection(quantity))
    assert set(transport.calls) == VARIANTS
    assert result.data.height == 4
    assert result.data["value"].null_count() == 2
    assert {time.minute for time in result.data["time"]} == {0, 10}  # No fabricated 00:05 row.
    assert rr.pick(result, variant="validated", on_issue="ignore").data.is_empty()
    assert rr.pick(result, variant="pre_validated_and_validated", on_issue="ignore").data.is_empty()
    ids = dict(rr.series(result).select("series_id", "variant").iter_rows())
    states = {ids[outcome.series_id]: outcome.status for outcome in result.outcomes if outcome.series_id in ids}
    assert states["validated"] == "empty"
    assert states["pre_validated_and_validated"] == "failed"
    assert states["raw"] == states["most_valid"] == "success"
    assert result.issues
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.outcomes == result.outcomes
    assert restored.issues == result.issues


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.parametrize("field", ["code", "metric", "unit", "statuses", "timezone", "title"])
@pytest.mark.recorded("tests/test_data/fr_hydroportail_variants")
def test_empty_variant_parser_checks_envelope_identity(retained_evidence_root, quantity, variant, field):
    metric = "Q" if quantity == "discharge" else "H"
    recording = read_recording(
        retained_evidence_root
        / "tests/test_data/fr_hydroportail_variants"
        / f"Y251002001_{metric}_padded_{variant}.recording.json"
    )
    payload = recorded_payload(
        recording, "Y251002001", f"{quantity}_instantaneous", config(), "2019-12-30", "2020-01-04"
    )
    payload = replace(
        payload,
        source_coordinates=SourceCoordinates(replace(payload.source_coordinates.value, variant=variant)),
    )
    document = json.loads(payload.content)
    document["series"]["data"] = []
    if field == "timezone":
        document[field] = "Europe/Paris"
    else:
        document["series"][field] = "unexpected"
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert result.rows.is_empty()
    assert result.issues
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.status == "unsupported" and outcome.reason
    assert outcome.station_id == "Y251002001"
    assert outcome.product_id == f"{quantity}_instantaneous"
    assert outcome.series_id == result.series[0].series_id
    assert result.series[0].variant == variant


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
@pytest.mark.recorded("tests/test_data/fr_hydroportail_J783301020_empty.body")
def test_public_empty_variant_failure_keeps_identity_receipt_and_no_coverage(
    retained_evidence_root, monkeypatch, tmp_path, quantity
):
    def mutate(document):
        document["series"]["statuses"] = "unexpected"

    transport = SyntheticVariantTransport(retained_evidence_root, empty=VARIANTS, mutation=mutate)
    install(monkeypatch, tmp_path, transport)
    selection = rr.pick(public_selection(quantity), variant="validated")
    result = retrieve(selection, cache="reuse")
    assert transport.calls == ["validated"]
    assert result.data.is_empty()
    assert result.issues
    assert any(outcome.status == "unsupported" and outcome.reason for outcome in result.outcomes)
    assert not any(outcome.status in {"empty", "success"} for outcome in result.outcomes)
    assert result.outcomes[0].series_id == selection.series[0].series_id
    assert result.receipts.entries[0].content == transport.contents["validated"]
    assert rr.cache_status("fr_hydroportail").coverage == ()
    retrieve(selection, cache="reuse")
    assert transport.calls == ["validated", "validated"]


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_legacy_raw",
    "tests/test_data/fr_hydroportail_station_Q_padded.recording.json",
)
def test_pre_variant_cache_and_exports_do_not_settle_expanded_scope(retained_evidence_root, monkeypatch, tmp_path):
    import shutil

    from rivretrieve._internal.recordings import read_recording

    artifact = retained_evidence_root / "tests/test_data/fr_hydroportail_legacy_raw"
    shutil.copytree(artifact / "cache", tmp_path / "cache")
    before = {p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()}
    # Historical v2 carriers remain unchanged and are explicitly unsupported.
    for name in ("result.zip", "selection.zip"):
        with pytest.raises(ValueError, match="Unsupported source-series bundle format version"):
            rr.from_bundle((artifact / name).read_bytes())
    recording = read_recording(
        retained_evidence_root / "tests/test_data/fr_hydroportail_station_Q_padded.recording.json"
    )

    class LegacyWindowTransport:
        def __init__(self):
            self.calls = []

        def send(self, request):
            variant = request.params["hydro_series[statusData]"]
            self.calls.append(variant)
            # Synthetic selector variants of genuine raw bytes; no source witness claim.
            body = json.loads(recording.content)
            body["series"]["statuses"] = variant
            return TransportResponse(
                json.dumps(body).encode(),
                200,
                recording.retrieved_at,
                recording.content_type,
                request.url,
                request.params,
            )

    transport = LegacyWindowTransport()
    install(monkeypatch, tmp_path, transport)
    selection = rr.find(
        provider="fr_hydroportail", station="1232000101", quantity="discharge", statistic="instantaneous"
    )
    from rivretrieve._internal.store import ObservationStoreRefusedError

    held_files = {p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / "cache").rglob("*") if p.is_file()}
    with pytest.raises(ObservationStoreRefusedError, match="unsupported format revision 7"):
        rr.fetch(selection, start="2026-06-01", end="2026-06-02", cache="reuse", on_issue="ignore")
    assert transport.calls == []
    assert {
        p.relative_to(tmp_path): p.read_bytes() for p in (tmp_path / "cache").rglob("*") if p.is_file()
    } == held_files
    # Remove only the copied obsolete store before testing current variant acquisition.
    shutil.rmtree(tmp_path / "cache")
    result = rr.fetch(selection, start="2026-06-01", end="2026-06-02", cache="reuse", on_issue="ignore")
    assert set(transport.calls) == VARIANTS
    assert set(rr.series(result)["variant"].drop_nulls()) == VARIANTS
    assert result.data["series_id"].n_unique() == 4
    transport.calls.clear()
    # An authored current-format selection retains unspecified variant intent.
    # This is not a migration of the historical carrier or a source witness.
    unspecified = replace(
        selection,
        known_series=(
            selection.series[0].model_copy(update={"variant": None, "series_id": "synthetic-unspecified-variant"}),
        ),
        inventories=(),
    )
    unspecified = rr.from_bundle(rr.to_bundle(unspecified))
    assert not unspecified.scope.variants
    assert rr.series(unspecified)["variant"].to_list() == [None]
    expanded_export = rr.fetch(unspecified, start="2026-06-01", end="2026-06-02", cache="reuse", on_issue="ignore")
    assert set(transport.calls) == VARIANTS
    assert set(rr.series(expanded_export)["variant"].drop_nulls()) == VARIANTS
    assert expanded_export.data["series_id"].n_unique() == 4
    assert rr.series(unspecified)["variant"].to_list() == [None]
    assert {p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize(
    "station,start,end", [("Y251002001", "2020-01-01", "2020-01-02"), ("1232000101", "2026-06-01", "2026-06-02")]
)
@pytest.mark.parametrize("metric,quantity", [("Q", "discharge"), ("H", "stage")])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
@pytest.mark.recorded("tests/test_data/fr_hydroportail_variants")
def test_recorded_source_variant_public_path(
    retained_evidence_root, monkeypatch, tmp_path, station, start, end, metric, quantity, variant
):
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    recording = read_recording(
        retained_evidence_root
        / "tests/test_data/fr_hydroportail_variants"
        / f"{station}_{metric}_padded_{variant}.recording.json"
    )
    install(monkeypatch, tmp_path, ReplayTransport((recording,)))
    selection = rr.pick(
        rr.find(provider="fr_hydroportail", station=station, quantity=quantity, statistic="instantaneous"),
        variant=variant,
    )
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="raise")
    expected_count = (
        (576 if variant == "raw" else 50)
        if station == "Y251002001"
        else (282 if variant in {"raw", "most_valid"} else 0)
    )
    assert result.data.height == expected_count
    assert rr.series(result)["variant"].to_list() == [variant]
    assert result.receipts.entries[0].content == recording.content
    body = json.loads(result.receipts.entries[0].content)
    assert body["series"]["statuses"] == variant
    if expected_count:
        expected_first = start + ("T00:01:00" if station == "Y251002001" and variant != "raw" else "T00:00:00")
        assert result.data["time"].min() == datetime.fromisoformat(expected_first)
        assert result.data["time_zone"].unique().to_list() == ["+00:00"]
    else:
        assert any(outcome.status == "empty" for outcome in result.outcomes)
    assert {issue.code for issue in result.issues} <= {
        "provenance.license_not_established",
        "provenance.citation_not_established",
    }


@pytest.mark.parametrize("metric,quantity", [("Q", "discharge"), ("H", "stage")])
@pytest.mark.recorded("tests/test_data/fr_hydroportail_variants")
def test_recorded_unrestricted_overlaps_keep_source_identities(
    retained_evidence_root, monkeypatch, tmp_path, metric, quantity
):
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    folder = retained_evidence_root / "tests/test_data/fr_hydroportail_variants"
    recordings = tuple(
        read_recording(folder / f"Y251002001_{metric}_padded_{variant}.recording.json") for variant in sorted(VARIANTS)
    )
    install(monkeypatch, tmp_path, ReplayTransport(recordings))
    result = retrieve(public_selection(quantity))
    assert result.data.height == 576 + 3 * 50
    assert result.data["series_id"].n_unique() == 4
    assert len(result.receipts.entries) == 4
    assert {entry.content for entry in result.receipts.entries} == {recording.content for recording in recordings}
    validated = rr.pick(result, variant="validated", on_issue="ignore").data
    most_valid = rr.pick(result, variant="most_valid", on_issue="ignore").data
    assert_frame_equal(validated.select("time", "value"), most_valid.select("time", "value"))
    assert validated["series_id"][0] != most_valid["series_id"][0]
    assert {issue.code for issue in result.issues} <= {
        "provenance.license_not_established",
        "provenance.citation_not_established",
    }
