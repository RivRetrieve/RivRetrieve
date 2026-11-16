"""Replay exact retained requests; private source checks establish coverage claims."""

import json
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.pe_senamhi.fetch import SenamhiSourceCoordinates, fetch, window_declaration
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from rivretrieve._internal.window_planning import plan_windows


@pytest.mark.recorded("maintenance/observations/pe_senamhi/retrieval")
@pytest.mark.parametrize(
    ("member", "station", "subsystem", "resolution", "variable", "unit", "date", "status"),
    [
        ("anchors/daily-ramis-05", "47251282", "phisis", "DAILY", "FLOW", "m3/s", "2024-08-31", 200),
        ("boundaries/hourly-end-second-0", "47251282", "phisis", "HOURLY", "FLOW", "m3/s", "2024-08-31", 200),
        (
            "anchors/readings-47E0D438-202610",
            "47E0D438",
            "monthly_archive",
            None,
            "N_NIVELAGUA",
            "m",
            "2026-10-01",
            200,
        ),
        (
            "anchors/readings-200322-202610",
            "200322",
            "monthly_archive",
            None,
            "NIVEL_DEL_RIO_PROMEDIO",
            "m",
            "2026-10-01",
            200,
        ),
        (
            "boundaries/readings-472BC082-202609",
            "472BC082",
            "monthly_archive",
            None,
            "N_NIVELAGUA",
            "m",
            "2026-09-01",
            422,
        ),
    ],
)
def test_retained_acquisition_preserves_exact_request_and_response(
    retained_evidence_root, member, station, subsystem, resolution, variable, unit, date, status
):
    root = retained_evidence_root / "maintenance/observations/pe_senamhi/retrieval"
    content = (root / (member + ".body")).read_bytes()
    receipt = json.loads((root / (member + ".receipt.json")).read_text())
    source_url = urlsplit(receipt["url"])
    source_parameters = dict(parse_qsl(source_url.query))
    coordinate = SenamhiSourceCoordinates(subsystem, resolution, variable, unit)
    endpoint = WindowEndpoint.from_datetime(datetime.fromisoformat(date))
    planned = plan_windows(_make_fetch_window(endpoint, endpoint), window_declaration(coordinate))
    calls = []

    class Replay:
        def send(self, request):
            requested_url = urlsplit(request.url)
            matching = (requested_url.scheme, requested_url.netloc, requested_url.path) == (
                source_url.scheme,
                source_url.netloc,
                source_url.path,
            ) and dict(request.params) == source_parameters
            assert matching, "Request does not match retained selector"
            calls.append(request)
            response = TransportResponse(
                content=content,
                status_code=receipt["http_status"],
                retrieved_at=datetime.fromisoformat(receipt["finished_at"]),
                content_type=next(
                    (value for name, value in receipt["headers"] if name.lower() == "content-type"), None
                ),
                url=receipt["url"],
                request_parameters=source_parameters,
            )
            if response.status_code >= 400:
                raise TransportFailure(
                    request, TransportFailureReason.HTTP_STATUS, 1, status_code=response.status_code, response=response
                )
            return response

    result = fetch((station,), {"selected": coordinate}, {"selected": planned}, Replay())
    assert len(calls) == 1
    assert receipt["http_status"] == status
    if status == 200:
        assert not result.failed_requests and not result.outcomes and not result.issues
        assert len(result.value) == 1
        unchanged = result.value[0].content == content
        assert unchanged, "Original bytes changed"
        assert result.value[0].fetch_window == planned[0].bounds
        same_origin = result.value[0].origin.url == receipt["url"]
        assert same_origin, "Response origin changed"
    else:
        assert not result.value
        assert len(result.failed_requests) == 1
        failure = result.failed_requests[0]
        assert failure.failure.status_code == status
        unchanged = failure.failure.response.content == content
        assert unchanged, "Failed response bytes changed"
        assert failure.meaning.value == "unspecified"
