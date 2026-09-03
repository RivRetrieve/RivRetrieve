"""capture : NveApiKey × CaptureJob* → RecordingEnvelope* written under tests/test_data.

Maintainer tool. This module is a composition root: it is the only place that reads
``NVE_API_KEY`` from the environment or from a local ``.env`` file, builds the engine
transport, and hands the credential to ``AuthenticatedTransport``. Provider code reads
neither. Run it from the repository root:

    uv run python scripts/capture_no_nve_recordings.py [ENV_FILE]

``ENV_FILE`` defaults to ``.env`` beside this repository and is consulted only when the
environment does not already carry the key. The credential value never reaches a written recording: the transport applies it below
the recorded request, and only the header name is kept as evidence.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from rivretrieve._internal.driver import _FETCH_WINDOW_PADDING  # noqa: E402
from rivretrieve._internal.engine import (  # noqa: E402
    RenderedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId  # noqa: E402
from rivretrieve._internal.providers.no_nve.config import config, window_declarations  # noqa: E402
from rivretrieve._internal.providers.no_nve.fetch import fetch  # noqa: E402
from rivretrieve._internal.recordings import RecordingEnvelope, write_recording  # noqa: E402
from rivretrieve._internal.transport import (  # noqa: E402
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    TransportRequest,
    TransportResponse,
)
from rivretrieve._internal.window_planning import plan_windows  # noqa: E402

CREDENTIAL_HEADER_NAME = "X-API-Key"
CREDENTIAL_ORIGIN = "https://hydapi.nve.no"
ENVIRONMENT_VARIABLE = "NVE_API_KEY"
RECORDING_DIRECTORY = REPOSITORY_ROOT / "tests" / "test_data"


@dataclass(frozen=True, slots=True)
class CaptureJob:
    """One station, one product, and the closed request window to capture."""

    station_id: str
    product_id: ProductId
    requested_start: str
    requested_end: str


CAPTURE_JOBS = (
    *(
        CaptureJob("1.200.0", ProductId(product_id), "2025-07-10T00:00:00", "2025-07-12T00:00:00")
        for product_id in sorted(config().products)
    ),
    # A station whose series does not exist answers HTTP 404 with an RFC 7807 body.
    CaptureJob("12.210.0", ProductId("water_temperature_daily_mean"), "2025-07-10T00:00:00", "2025-07-12T00:00:00"),
    # An existing series with no observation in the window answers 200 with an empty series.
    CaptureJob("1.200.0", ProductId("stage_daily_mean"), "1900-01-03T00:00:00", "1900-01-05T00:00:00"),
)


class _CaptureTransport:
    """Record every exact interaction the provider issues through the engine transport."""

    def __init__(self, transport: AuthenticatedTransport) -> None:
        self._transport = transport
        self.recordings: list[RecordingEnvelope] = []

    def can_authenticate(self, url: str) -> bool:
        return self._transport.can_authenticate(url)

    def send(self, request: TransportRequest) -> TransportResponse:
        response = self._transport.send(request)
        self.recordings.append(RecordingEnvelope.from_transport(request, response))
        return response


def api_key(environment: dict[str, str], dotenv_path: Path) -> str:
    """Resolve the API key from the environment, then from a local .env file."""
    value = environment.get(ENVIRONMENT_VARIABLE)
    if value:
        return value
    if dotenv_path.is_file():
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            name, separator, raw = line.partition("=")
            if separator and name.strip() == ENVIRONMENT_VARIABLE:
                return raw.strip().strip("'\"")
    raise SystemExit(f"{ENVIRONMENT_VARIABLE} is not set and {dotenv_path} does not define it")


def recording_name(job: CaptureJob, start: str, stop: str) -> str:
    coordinates = config().products[job.product_id].coordinates.value
    parameter = getattr(coordinates, "parameter")
    resolution_time = getattr(coordinates, "resolution_time")
    return (
        f"no_nve_{job.station_id}_{parameter}_{resolution_time}_"
        f"{start[:10]}_{stop[:10]}.recording.json".replace("/", "_")
    )


def capture(job: CaptureJob, transport: _CaptureTransport) -> Path:
    """Issue the exact provider request for one job and write its recording."""
    provider_config = config()
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(job.requested_start) - _FETCH_WINDOW_PADDING),
        WindowEndpoint.from_datetime(datetime.fromisoformat(job.requested_end) + _FETCH_WINDOW_PADDING),
    )
    windows = plan_windows(fetch_window, window_declarations().products[job.product_id])
    rendered: dict[ProductId, tuple[RenderedWindow, ...]] = {job.product_id: windows}
    before = len(transport.recordings)
    fetch(
        (job.station_id,),
        (job.product_id,),
        MappingProxyType(rendered),
        fetch_window,
        provider_config,
        transport,
    )
    captured = transport.recordings[before:]
    if len(captured) != 1:
        raise SystemExit(f"expected exactly one interaction for {job.product_id}, captured {len(captured)}")
    (window,) = windows
    assert window.stop is not None
    destination = RECORDING_DIRECTORY / recording_name(job, window.start, window.stop)
    write_recording(captured[0], destination)
    return destination


def main(argv: Sequence[str]) -> int:
    if len(argv) > 1:
        raise SystemExit("usage: capture_no_nve_recordings.py [ENV_FILE]")
    dotenv_path = Path(argv[0]).expanduser() if argv else REPOSITORY_ROOT / ".env"
    key = api_key(dict(os.environ), dotenv_path)
    transport = _CaptureTransport(
        AuthenticatedTransport(
            HttpClient(),
            (CredentialHeader(CREDENTIAL_HEADER_NAME, key, (CREDENTIAL_ORIGIN,)),),
        )
    )
    for job in CAPTURE_JOBS:
        destination = capture(job, transport)
        print(f"wrote {destination.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
