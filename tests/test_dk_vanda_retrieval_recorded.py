"""Replay exact retained requests; private source checks establish coverage claims."""

import json
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.dk_vanda.config import DkVandaSourceCoordinates, config
from rivretrieve._internal.providers.dk_vanda.fetch import fetch
from rivretrieve._internal.providers.dk_vanda.parse import parse
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from rivretrieve._internal.window_planning import plan_windows

_SCOPE = "maintenance/catalogue/dk_vanda/official/retrieval/web"


def _plan(coordinates: DkVandaSourceCoordinates, start: str, stop: str):
    from rivretrieve._internal.providers.dk_vanda.config import window_declarations

    endpoint_start = WindowEndpoint.from_datetime(datetime.fromisoformat(start))
    endpoint_stop = WindowEndpoint.from_datetime(datetime.fromisoformat(stop))
    decls = window_declarations()
    product = next(
        product for product, declared in config().products.items() if declared.coordinates.value == coordinates
    )
    return plan_windows(_make_fetch_window(endpoint_start, endpoint_stop), decls.products[product]), product


@pytest.mark.recorded(_SCOPE)
@pytest.mark.parametrize(
    ("member", "station", "examination_type_sc", "endpoint", "start", "stop", "status"),
    [
        ("stage-retention-52000092-1968", "52000092", 25, "water-levels", "1968-01-01", "1968-01-03", 200),
        ("empty-window-52000092-2031", "52000092", 25, "water-levels", "2031-01-01", "2031-01-02", 200),
        (
            "invalid-station-measurements-current",
            "00000000",
            29,
            "measurements-results-current",
            "2020-01-01",
            "2020-01-02",
            400,
        ),
        (
            "temperature-current-70000277-2014",
            "70000277",
            29,
            "measurements-results-current",
            "2014-01-01",
            "2014-01-02",
            200,
        ),
    ],
)
def test_retained_acquisition_preserves_exact_request_and_response(
    retained_evidence_root, member, station, examination_type_sc, endpoint, start, stop, status
):
    root = retained_evidence_root / _SCOPE
    content = (root / (member + ".body")).read_bytes()
    receipt = json.loads((root / (member + ".receipt.json")).read_text())
    source_url = urlsplit(receipt["url"])
    source_parameters = dict(parse_qsl(source_url.query))

    coordinates = DkVandaSourceCoordinates(examination_type_sc, endpoint)
    windows, product = _plan(coordinates, start, stop)
    calls = []

    class Replay:
        def send(self, request):
            requested_url = urlsplit(request.url)
            matching = (requested_url.scheme, requested_url.netloc, requested_url.path) == (
                source_url.scheme,
                source_url.netloc,
                source_url.path,
            ) and {str(k): str(v) for k, v in request.params.items()} == source_parameters
            assert matching, "Request does not match retained selector"
            calls.append(request)
            response = TransportResponse(
                content=content,
                status_code=receipt["http_status"],
                retrieved_at=datetime.fromisoformat(receipt["retrieved_at"]),
                content_type=receipt.get("media_type"),
                url=receipt["url"],
                request_parameters=source_parameters,
            )
            if response.status_code >= 400:
                raise TransportFailure(
                    request, TransportFailureReason.HTTP_STATUS, 1, status_code=response.status_code, response=response
                )
            return response

    cfg = config()
    fw = windows[0].bounds
    result = fetch((station,), (product,), {product: windows}, fw, cfg, Replay())
    assert len(calls) == 1
    assert receipt["http_status"] == status

    if status == 200:
        assert not result.failed_requests
        assert len(result.value) == 1
        payload = result.value[0]
        assert payload.content == content
        assert payload.origin.url == receipt["url"]
        # Parsing the retained bytes must not raise, whatever shape they carry
        # (a real empty-but-valid "[]" window, or genuine historical rows).
        parsed = parse(payload, cfg)
        assert parsed.rows is not None
    else:
        assert not result.value
        assert len(result.failed_requests) == 1
        failure = result.failed_requests[0]
        assert failure.failure.status_code == status
        assert failure.failure.response.content == content
        # A 400 for an unresolved station identity is never folded into
        # "no observations"; see fetch.py's module docstring.
        assert failure.meaning.value == "unspecified"


@pytest.mark.recorded(_SCOPE)
def test_temperature_current_and_all_retained_bytes_are_byte_identical(retained_evidence_root):
    """Fourth multi-version-results recheck (station/product not tried before):
    `/measurements/results/current` and `/measurements/results/all` returned
    byte-identical bodies for the same station, product and window -- still no
    doubling or disagreement, consistent with steps 1 and 3's negative results."""
    root = retained_evidence_root / _SCOPE
    current = (root / "temperature-current-70000277-2014.body").read_bytes()
    all_results = (root / "temperature-all-70000277-2014.body").read_bytes()
    assert current == all_results
    document = json.loads(current)
    assert len(document) == 1
    rows = document[0]["results"]
    assert len(rows) == 25
    assert len({row["measurementDateTime"] for row in rows}) == 25
