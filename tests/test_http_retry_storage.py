"""Real HTTP interruptions preserve acquisition and compiled-store boundaries."""

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from zipfile import ZipFile

import pytest

from rivretrieve._internal import bulk
from rivretrieve._internal.providers.pl_imgw.bulk import (
    ANNUAL_URL_TEMPLATE,
    PROVIDER_ID,
    ImgwCompileRequest,
    compile_imgw,
    download_imgw_history,
)
from rivretrieve._internal.providers.pl_imgw.config import config
from rivretrieve._internal.providers.registration import BulkStore, DownloadedBulkArtifact
from rivretrieve._internal.store import StoreRoot, validate_store
from rivretrieve._internal.transport import (
    HttpClient,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
)


class AcquisitionClock:
    def __init__(self, check_artifacts: Callable[[], None]) -> None:
        self.elapsed = 0.0
        self.check_artifacts = check_artifacts

    def monotonic(self) -> float:
        return self.elapsed

    def utcnow(self) -> datetime:
        return datetime(2026, 9, 25, tzinfo=UTC) + timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.check_artifacts()
        self.elapsed += seconds


def _archive(year: int) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"codz_{year}.csv",
            f"149180020;Station;River;{year};3;1;113;12.500;4.0;1\n".encode("cp1250"),
        )
    return buffer.getvalue()


@contextmanager
def _publisher(framing: str, *, recover: bool) -> Iterator[tuple[str, Counter[str], dict[str, bytes]]]:
    bodies = {f"codz_{year}.zip": _archive(year) for year in (2023, 2024)}
    calls: Counter[str] = Counter()

    class ArchiveEndpoint(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            name = self.path.rsplit("/", 1)[-1]
            calls[name] += 1
            body = bodies[name]
            interrupted = name == "codz_2024.zip" and (not recover or calls[name] == 1)
            self.send_response(200)
            self.send_header("Connection", "close")
            if interrupted and framing == "chunked":
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"100\r\npartial-attempt")
            else:
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(b"partial-attempt" if interrupted else body)
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ArchiveEndpoint)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, bodies
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize("framing", ["fixed", "chunked"])
def test_recovered_archive_keeps_earlier_success_and_writes_only_complete_bytes(tmp_path: Path, framing: str) -> None:
    destination = tmp_path / "publisher-artifact.download"
    first = destination.with_name(destination.name + "-codz_2023.zip")
    second = destination.with_name(destination.name + "-codz_2024.zip")
    checks = []
    with _publisher(framing, recover=True) as (origin, calls, bodies):

        def check_artifacts() -> None:
            if calls["codz_2024.zip"]:
                assert first.read_bytes() == bodies["codz_2023.zip"]
                assert not second.exists()
                checks.append(True)

        clock = AcquisitionClock(check_artifacts)
        client = HttpClient(clock=clock, sleeper=clock.sleep)
        downloaded = download_imgw_history(
            destination,
            today=date(2025, 1, 1),
            first_year=2023,
            transfer=lambda url, target: bulk._transfer(client, f"{origin}/{url.rsplit('/', 1)[-1]}", target),
        )

    assert checks
    assert calls == {"codz_2023.zip": 1, "codz_2024.zip": 2}
    assert [item.path for item in downloaded] == [first, second]
    assert first.read_bytes() == bodies["codz_2023.zip"]
    assert second.read_bytes() == bodies["codz_2024.zip"]
    assert set(tmp_path.iterdir()) == {first, second}


@pytest.mark.parametrize("framing", ["fixed", "chunked"])
def test_exhausted_acquisition_rolls_back_artifacts_without_replacing_valid_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, framing: str
) -> None:
    root = StoreRoot(tmp_path / "store")
    previous_artifact = tmp_path / "codz_2023.zip"
    previous_artifact.write_bytes(_archive(2023))
    previous = compile_imgw(
        ImgwCompileRequest(
            previous_artifact,
            root,
            ANNUAL_URL_TEMPLATE.format(year=2023),
            date(2023, 10, 31),
            datetime(2026, 9, 24, tzinfo=UTC),
            "0.1.49",
        )
    )
    before = {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}
    assert before
    assert not previous_artifact.exists()
    unrelated = tmp_path / "unrelated.zip"
    unrelated.write_bytes(b"unrelated publisher input")
    destination = tmp_path / "publisher-artifact.download"
    first = destination.with_name(destination.name + "-codz_2023.zip")
    second = destination.with_name(destination.name + "-codz_2024.zip")
    checks = []

    with _publisher(framing, recover=False) as (origin, calls, bodies):

        def check_artifacts() -> None:
            if calls["codz_2024.zip"]:
                assert first.read_bytes() == bodies["codz_2023.zip"]
                assert not second.exists()
                checks.append(True)

        def acquire(request):
            downloaded = download_imgw_history(
                request.destination,
                today=request.today,
                first_year=2023,
                transfer=lambda url, target: request.transfer(f"{origin}/{url.rsplit('/', 1)[-1]}", target),
            )
            return tuple(DownloadedBulkArtifact(item.path, item.url, item.source_vintage) for item in downloaded)

        def refuse_compilation(request):
            pytest.fail("Exhausted acquisition must not begin compilation")

        operations = BulkStore(config=config, download=acquire, compile=refuse_compilation)
        assert config.cache is not None and config.cache.store is not None
        monkeypatch.setattr(
            bulk, "_bulk_registration", lambda provider: (PROVIDER_ID, config.cache.store, root, operations)
        )
        clock = AcquisitionClock(check_artifacts)
        with pytest.raises(TransportFailure) as caught:
            bulk._download(
                "pl_imgw",
                free_space_probe=lambda path: 10**15,
                client_factory=lambda: HttpClient(clock=clock, sleeper=clock.sleep),
                today=date(2025, 1, 1),
            )

    assert checks
    assert caught.value.reason is TransportFailureReason.RETRY_EXHAUSTED
    assert caught.value.attempts == 3
    assert caught.value.category is TransportFailureCategory.INCOMPLETE_RESPONSE
    assert caught.value.status_code is None
    assert caught.value.request.url == f"{origin}/codz_2024.zip"
    assert calls == {"codz_2023.zip": 1, "codz_2024.zip": 3}
    assert not list(tmp_path.glob("publisher-artifact.download*"))
    assert set(tmp_path.iterdir()) == {Path(root), unrelated}
    assert unrelated.read_bytes() == b"unrelated publisher input"
    assert {p.relative_to(root): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()} == before
    assert validate_store(root, PROVIDER_ID).manifest == previous.manifest
