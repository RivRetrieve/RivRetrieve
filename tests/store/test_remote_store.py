"""Remote S3-compatible observation-store configuration, lifecycle, integrity and retrieval."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
)
from rivretrieve._internal.store import (
    ObservationStoreRefusedError,
    StorePresence,
    StoreQuery,
    StoreReader,
)
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
from rivretrieve._internal.store.lifecycle import StoreLifecycleError
from rivretrieve._internal.store.remote import RemoteStoreRoot

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


@dataclass
class S3TestServer:
    endpoint_url: str
    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)
    requests: list[tuple[str, str, str]] = field(default_factory=list)
    fail_on_put_key: Callable[[str], bool] | None = None

    def configure_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        bucket: str = "test-bucket",
        prefix: str = "rivretrieve",
    ) -> str:
        uri = f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"
        monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", uri)
        monkeypatch.setenv("RIVRETRIEVE_S3_ENDPOINT_URL", self.endpoint_url)
        monkeypatch.setenv("RIVRETRIEVE_S3_REGION", "fsn1")
        monkeypatch.setenv("RIVRETRIEVE_S3_ACCESS_KEY_ID", "test-access-key")
        monkeypatch.setenv("RIVRETRIEVE_S3_SECRET_ACCESS_KEY", "test-secret-key")
        return uri

    def get_keys(self, bucket: str = "test-bucket") -> set[str]:
        return {key for (b, key) in self.objects if b == bucket and not key.endswith("/")}

    def get_requests_for(self, method: str, key_substring: str = "") -> list[str]:
        return [key for m, _, key in self.requests if m == method and key_substring in key]


@pytest.fixture
def s3_server():
    state = S3TestServer(endpoint_url="")
    uploads: dict[tuple[str, str, str], dict[int, bytes]] = {}
    upload_counter = 0
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _parse(self) -> tuple[str, str, dict[str, list[str]]]:
            parsed = urlparse(self.path)
            parts = parsed.path.lstrip("/").split("/", 1)
            bucket = parts[0]
            key = unquote(parts[1]) if len(parts) > 1 else ""
            return bucket, key, parse_qs(parsed.query, keep_blank_values=True)

        def do_HEAD(self) -> None:
            bucket, key, _ = self._parse()
            with lock:
                state.requests.append(("HEAD", bucket, key))
                if not key:
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = state.objects.get((bucket, key))
            if data is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("ETag", f'"{hashlib.md5(data).hexdigest()}"')
            self.end_headers()

        def do_GET(self) -> None:
            bucket, key, qs = self._parse()
            if "list-type" in qs or not key:
                prefix = qs.get("prefix", [""])[0]
                with lock:
                    state.requests.append(("LIST", bucket, prefix))
                    matching = sorted(
                        (k, v) for (b, k), v in state.objects.items() if b == bucket and k.startswith(prefix)
                    )
                items = "".join(
                    f"<Contents><Key>{k}</Key><LastModified>2026-01-01T00:00:00.000Z</LastModified>"
                    f'<ETag>"{hashlib.md5(v).hexdigest()}"</ETag><Size>{len(v)}</Size>'
                    "<StorageClass>STANDARD</StorageClass></Contents>"
                    for k, v in matching
                )
                body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"<Name>{bucket}</Name><Prefix>{prefix}</Prefix><KeyCount>{len(matching)}</KeyCount>"
                    f"<MaxKeys>1000</MaxKeys><IsTruncated>false</IsTruncated>{items}</ListBucketResult>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            with lock:
                state.requests.append(("GET", bucket, key))
                data = state.objects.get((bucket, key))
            if data is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("ETag", f'"{hashlib.md5(data).hexdigest()}"')
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            nonlocal upload_counter
            bucket, key, qs = self._parse()
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            if "uploads" in qs:
                with lock:
                    if state.fail_on_put_key is not None and state.fail_on_put_key(key):
                        err = b"<Error><Code>AccessDenied</Code><Message>Injected failure</Message></Error>"
                        self.send_response(403)
                        self.send_header("Content-Type", "application/xml")
                        self.send_header("Content-Length", str(len(err)))
                        self.end_headers()
                        self.wfile.write(err)
                        return
                    upload_counter += 1
                    uid = f"upload-{upload_counter}"
                    uploads[(bucket, key, uid)] = {}
                body = (
                    '<InitiateMultipartUploadResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"<Bucket>{bucket}</Bucket><Key>{key}</Key><UploadId>{uid}</UploadId>"
                    "</InitiateMultipartUploadResult>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if "uploadId" in qs:
                uid = qs["uploadId"][0]
                with lock:
                    if state.fail_on_put_key is not None and state.fail_on_put_key(key):
                        self.send_response(500)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    parts = uploads.pop((bucket, key, uid), {})
                    data = b"".join(v for _, v in sorted(parts.items()))
                    state.objects[(bucket, key)] = data
                    state.requests.append(("PUT", bucket, key))
                body = (
                    '<CompleteMultipartUploadResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    f"<Bucket>{bucket}</Bucket><Key>{key}</Key>"
                    f'<ETag>"{hashlib.md5(data).hexdigest()}"</ETag>'
                    "</CompleteMultipartUploadResult>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        def do_PUT(self) -> None:
            bucket, key, qs = self._parse()
            copy_src = self.headers.get("x-amz-copy-source")
            if copy_src:
                src_parts = unquote(copy_src).lstrip("/").split("/", 1)
                with lock:
                    if state.fail_on_put_key is not None and state.fail_on_put_key(key):
                        err = b"<Error><Code>AccessDenied</Code><Message>Injected failure</Message></Error>"
                        self.send_response(403)
                        self.send_header("Content-Type", "application/xml")
                        self.send_header("Content-Length", str(len(err)))
                        self.end_headers()
                        self.wfile.write(err)
                        return
                    state.objects[(bucket, key)] = state.objects[(src_parts[0], src_parts[1])]
                    state.requests.append(("COPY", bucket, f"{src_parts[1]}->{key}"))
                body = (
                    b'<CopyObjectResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                    b'<LastModified>2026-01-01T00:00:00.000Z</LastModified><ETag>"abc"</ETag>'
                    b"</CopyObjectResult>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length) if length else b""
            with lock:
                if state.fail_on_put_key is not None and state.fail_on_put_key(key):
                    err = b"<Error><Code>AccessDenied</Code><Message>Injected failure</Message></Error>"
                    self.send_response(403)
                    self.send_header("Content-Type", "application/xml")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return
                if "uploadId" in qs:
                    uid = qs["uploadId"][0]
                    part_no = int(qs["partNumber"][0])
                    uploads[(bucket, key, uid)][part_no] = data
                else:
                    state.objects[(bucket, key)] = data
                    state.requests.append(("PUT", bucket, key))
            self.send_response(200)
            self.send_header("ETag", f'"{hashlib.md5(data).hexdigest()}"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_DELETE(self) -> None:
            bucket, key, qs = self._parse()
            with lock:
                if "uploadId" in qs:
                    uploads.pop((bucket, key, qs["uploadId"][0]), None)
                else:
                    state.objects.pop((bucket, key), None)
                    state.requests.append(("DELETE", bucket, key))
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.endpoint_url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def test_resolve_store_root_parses_s3_uri_and_hides_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", "s3://hydro-bucket/team/cache")
    monkeypatch.setenv("RIVRETRIEVE_S3_ENDPOINT_URL", "https://fsn1.your-objectstorage.com")
    monkeypatch.setenv("RIVRETRIEVE_S3_REGION", "fsn1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "AQoDYXdzEJr1EXAMPLE")

    store = discovery._resolve_store_root("usgs_nwis", None)
    assert isinstance(store, RemoteStoreRoot)
    assert store.bucket == "hydro-bucket"
    assert store.prefix == "team/cache/usgs_nwis/store"
    assert str(store) == "s3://hydro-bucket/team/cache/usgs_nwis/store"
    assert repr(store) == "RemoteStoreRoot('s3://hydro-bucket/team/cache/usgs_nwis/store')"
    for secret in (
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "AQoDYXdzEJr1EXAMPLE",
    ):
        assert secret not in str(store)
        assert secret not in repr(store)
        assert secret not in repr(store.config)


def test_resolve_store_root_reads_s3_settings_from_dotenv_with_env_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "RIVRETRIEVE_CACHE_DIR=s3://dotenv-bucket/prefix\n"
        "RIVRETRIEVE_S3_ENDPOINT_URL=https://nbg1.your-objectstorage.com\n"
        "RIVRETRIEVE_S3_REGION=nbg1\n"
        "RIVRETRIEVE_S3_ACCESS_KEY_ID=dotenv-key\n"
        "RIVRETRIEVE_S3_SECRET_ACCESS_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    store = discovery._resolve_store_root("pl_imgw", None)
    assert isinstance(store, RemoteStoreRoot)
    assert str(store) == "s3://dotenv-bucket/prefix/pl_imgw/store"
    assert store.config.endpoint_url == "https://nbg1.your-objectstorage.com"
    assert store.config.region == "nbg1"

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", "s3://env-bucket")
    monkeypatch.setenv("RIVRETRIEVE_S3_REGION", "hel1")
    overridden = discovery._resolve_store_root("pl_imgw", None)
    assert isinstance(overridden, RemoteStoreRoot)
    assert str(overridden) == "s3://env-bucket/pl_imgw/store"
    assert overridden.config.region == "hel1"


@pytest.mark.parametrize(
    ("env", "match"),
    [
        ({"RIVRETRIEVE_CACHE_DIR": "s3://"}, "bucket"),
        ({"RIVRETRIEVE_CACHE_DIR": "s3:///prefix"}, "bucket"),
        ({"RIVRETRIEVE_CACHE_DIR": "s3://bucket/a/../b"}, "parent"),
        ({"RIVRETRIEVE_CACHE_DIR": "s3://bucket/prefix?x=1"}, "query"),
        (
            {
                "RIVRETRIEVE_CACHE_DIR": "s3://bucket/prefix",
                "RIVRETRIEVE_S3_ENDPOINT_URL": "ftp://example.com",
                "AWS_ACCESS_KEY_ID": "ak",
                "AWS_SECRET_ACCESS_KEY": "sk",
            },
            "endpoint",
        ),
        (
            {
                "RIVRETRIEVE_CACHE_DIR": "s3://bucket/prefix",
                "RIVRETRIEVE_S3_ENDPOINT_URL": "   ",
                "AWS_ACCESS_KEY_ID": "ak",
                "AWS_SECRET_ACCESS_KEY": "sk",
            },
            "RIVRETRIEVE_S3_ENDPOINT_URL",
        ),
        (
            {
                "RIVRETRIEVE_CACHE_DIR": "s3://bucket/prefix",
                "RIVRETRIEVE_S3_ENDPOINT_URL": "https://fsn1.your-objectstorage.com",
            },
            "credentials",
        ),
        (
            {
                "RIVRETRIEVE_CACHE_DIR": "s3://bucket/prefix",
                "AWS_ACCESS_KEY_ID": "only-access-key",
            },
            "secret",
        ),
    ],
)
def test_resolve_store_root_rejects_invalid_s3_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    match: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=match):
        discovery._resolve_store_root("usgs_nwis", None)


def _series_definition(series_id: str, provider_id: str = "usgs_nwis", product_id: str = "level") -> SourceSeries:
    from rivretrieve._internal.source_series import known

    return SourceSeries(
        series_id=series_id,
        provider_id=provider_id,
        station_id="07374000",
        product_id=product_id,
        identity=SourceIdentity(
            namespace="recorded-field",
            published_id=series_id,
            origin="response",
            evidence=("fixture",),
        ),
        facts=(
            PhysicalFacts(
                facts_id="facts",
                quantity=known("stage", "fixture"),
                source_unit=known("cm", "fixture"),
                normalized_unit="cm",
            ),
        ),
    )


def _series_replacement(
    series_id: str,
    outcome_id: str,
    year: int,
    day: int,
    values: list[float | None],
    *,
    product_id: str = "level",
) -> tuple[RetrievalOutcome, SuccessfulReplacement]:
    window = SeriesWindow(
        start=datetime(year, 1, day),
        end=datetime(year, 1, day, 23, 59, 59, 999999),
    )
    outcome = RetrievalOutcome(
        outcome_id=outcome_id,
        series_id=series_id,
        station_id="07374000",
        product_id=product_id,
        window=window,
        status=OutcomeStatus.SUCCESS if values else OutcomeStatus.EMPTY,
        facts_ids=("facts",),
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    rows = pl.DataFrame(
        {
            "station_id": ["07374000"] * len(values),
            "product_id": [product_id] * len(values),
            "time": [window.start] * len(values),
            "value": values,
            "time_zone": ["unknown"] * len(values),
            "series_id": [series_id] * len(values),
            "facts_id": ["facts"] * len(values),
            "source_unit": ["cm"] * len(values),
        },
        schema={
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "value": pl.Float64,
            "time_zone": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
        },
    )
    replacement = SuccessfulReplacement(
        CoverageInterval(
            series_id,
            RequestedInterval(window.start, window.end),
            outcome.retrieved_at,
            outcome_id,
        ),
        rows,
    )
    return outcome, replacement


def test_remote_accumulate_selective_read_and_partition_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    s3_server: S3TestServer,
) -> None:
    monkeypatch.chdir(tmp_path)
    s3_server.configure_env(monkeypatch, bucket="hydro-bucket", prefix="archive")
    store = discovery._resolve_store_root("usgs_nwis", None)
    provider = ProviderId("usgs_nwis")

    initial_status = rr.cache_status("usgs_nwis")
    assert initial_status.presence is StorePresence.ABSENT
    assert not initial_status.exists
    assert str(initial_status.store) == "s3://hydro-bucket/archive/usgs_nwis/store"

    definition = _series_definition("s1")
    out_2020, rep_2020 = _series_replacement("s1", "o-2020", 2020, 1, [12.5])
    out_2021, rep_2021 = _series_replacement("s1", "o-2021", 2021, 1, [18.0])
    accumulate(
        store,
        provider,
        StoreUpdate((definition,), (), (out_2020, out_2021), (rep_2020, rep_2021)),
    )

    status = rr.cache_status("usgs_nwis")
    assert status.presence is StorePresence.PRESENT
    assert status.exists
    assert status.generation_id is not None
    assert status.bytes_on_disk > 0
    assert {
        "archive/usgs_nwis/store/manifest.json",
        "archive/usgs_nwis/store/integrity.json",
        "archive/usgs_nwis/store/product=level/year=2020/rows.parquet",
        "archive/usgs_nwis/store/product=level/year=2021/rows.parquet",
    } == s3_server.get_keys("hydro-bucket")

    # Selective query for 2021 must NOT download the 2020 partition from S3.
    s3_server.requests.clear()
    read_2021 = StoreReader().query(
        StoreQuery(
            store,
            provider,
            ("07374000",),
            ("level",),
            datetime(2021, 1, 1),
            datetime(2021, 1, 31),
        )
    )
    assert read_2021.rows.get_column("value").to_list() == [18.0]
    assert s3_server.get_requests_for("GET", "year=2021/rows.parquet") != []
    assert s3_server.get_requests_for("GET", "year=2020/rows.parquet") == []

    # Updating 2021 only must reuse 2020 in S3 without downloading or re-uploading year=2020/rows.parquet.
    s3_server.requests.clear()
    out_2021_day2, rep_2021_day2 = _series_replacement("s1", "o-2021-d2", 2021, 2, [21.0])
    accumulate(
        store,
        provider,
        StoreUpdate((definition,), (), (out_2021_day2,), (rep_2021_day2,)),
    )
    assert s3_server.get_requests_for("GET", "year=2020/rows.parquet") == []
    assert s3_server.get_requests_for("PUT", "year=2020/rows.parquet") == []

    read_both = StoreReader().query(
        StoreQuery(
            store,
            provider,
            ("07374000",),
            ("level",),
            datetime(2020, 1, 1),
            datetime(2021, 1, 31),
        )
    )
    assert sorted(read_both.rows.get_column("value").to_list()) == [12.5, 18.0, 21.0]

    audit = rr.audit_cache("usgs_nwis")
    assert audit.partitions_checked == 2
    assert audit.rows_checked == 3


def test_remote_interruption_integrity_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    s3_server: S3TestServer,
) -> None:
    monkeypatch.chdir(tmp_path)
    s3_server.configure_env(monkeypatch, bucket="hydro-bucket", prefix="archive")
    store = discovery._resolve_store_root("usgs_nwis", None)
    provider = ProviderId("usgs_nwis")
    definition = _series_definition("s1")

    # 1a. Interrupted first install during staging or Step 4 replacement must not expose a valid store.
    from rivretrieve._internal.store.lifecycle import StoreTransactionError

    s3_server.fail_on_put_key = lambda key: key.endswith("/integrity.json") and "/store/" in key
    out_1, rep_1 = _series_replacement("s1", "o-1", 2020, 1, [10.0])
    with pytest.raises((OSError, StoreTransactionError)):
        accumulate(store, provider, StoreUpdate((definition,), (), (out_1,), (rep_1,)))
    s3_server.fail_on_put_key = None
    assert not rr.cache_status("usgs_nwis").exists

    # 1b. Out-of-process crash during first-install Step 4 (objects in store/ without seal + stage + replacing journal).
    tx_first = "aaaa456789abcdef0123456789abcdef"
    s3_server.objects[("hydro-bucket", "archive/usgs_nwis/store/manifest.json")] = b"{}"
    s3_server.objects[("hydro-bucket", f"archive/usgs_nwis/.store.stage-{tx_first}/manifest.json")] = b"{}"
    s3_server.objects[("hydro-bucket", "archive/usgs_nwis/.store.transaction.json")] = (
        f'{{"id": "{tx_first}", "phase": "replacing"}}'.encode()
    )
    first_interrupted = rr.cache_status("usgs_nwis")
    assert not first_interrupted.exists
    assert len(first_interrupted.interrupted_paths) > 0
    first_recovered = rr.recover_cache("usgs_nwis")
    assert not first_recovered.status.exists
    assert first_recovered.status.interrupted_paths == ()

    # Commit a valid initial generation.
    accumulate(store, provider, StoreUpdate((definition,), (), (out_1,), (rep_1,)))
    committed_gen = rr.cache_status("usgs_nwis").generation_id
    assert committed_gen is not None

    # 2a. Failure partway through Step 2 backup (.store.previous-<id> during "preparing") preserves committed store.
    out_2, rep_2 = _series_replacement("s1", "o-2", 2021, 1, [20.0])
    s3_server.fail_on_put_key = lambda key: ".store.previous-" in key and key.endswith("rows.parquet")
    with pytest.raises((OSError, StoreTransactionError)):
        accumulate(store, provider, StoreUpdate((definition,), (), (out_2,), (rep_2,)))
    s3_server.fail_on_put_key = None
    assert rr.cache_status("usgs_nwis").exists
    assert rr.cache_status("usgs_nwis").generation_id == committed_gen

    # 2b. Process crash during Step 2 backup ("preparing" with partial .store.previous-<id> and intact store/).
    tx_prep = "bbbb456789abcdef0123456789abcdef"
    s3_server.objects[("hydro-bucket", f"archive/usgs_nwis/.store.previous-{tx_prep}/manifest.json")] = b"{}"
    s3_server.objects[("hydro-bucket", f"archive/usgs_nwis/.store.stage-{tx_prep}/manifest.json")] = b"{}"
    s3_server.objects[("hydro-bucket", "archive/usgs_nwis/.store.transaction.json")] = (
        f'{{"id": "{tx_prep}", "phase": "preparing"}}'.encode()
    )
    prep_recovery = rr.recover_cache("usgs_nwis")
    assert prep_recovery.status.exists
    assert prep_recovery.status.generation_id == committed_gen
    assert prep_recovery.status.interrupted_paths == ()

    # 2c. Simulate an interrupted Step 4 replacement where store/ has lost integrity.json while other objects
    # remain in store/, alongside .store.previous-<id> and .store.stage-<id>.
    tx_id = "0123456789abcdef0123456789abcdef"
    for key in list(s3_server.get_keys("hydro-bucket")):
        if key.startswith("archive/usgs_nwis/store/"):
            rel = key.removeprefix("archive/usgs_nwis/store/")
            s3_server.objects[("hydro-bucket", f"archive/usgs_nwis/.store.previous-{tx_id}/{rel}")] = s3_server.objects[
                ("hydro-bucket", key)
            ]
    s3_server.objects.pop(("hydro-bucket", "archive/usgs_nwis/store/integrity.json"))
    s3_server.objects[("hydro-bucket", f"archive/usgs_nwis/.store.stage-{tx_id}/manifest.json")] = b"{}"
    s3_server.objects[("hydro-bucket", "archive/usgs_nwis/.store.transaction.json")] = (
        f'{{"id": "{tx_id}", "phase": "replacing"}}'.encode()
    )

    interrupted_status = rr.cache_status("usgs_nwis")
    assert len(interrupted_status.interrupted_paths) > 0
    with pytest.raises(StoreLifecycleError):
        StoreReader().query(
            StoreQuery(
                store,
                provider,
                ("07374000",),
                ("level",),
                datetime(2020, 1, 1),
                datetime(2020, 1, 31),
            )
        )

    recovery = rr.recover_cache("usgs_nwis")
    assert recovery.status.exists
    assert recovery.status.generation_id == committed_gen
    assert recovery.status.interrupted_paths == ()
    assert any("restored previous store" in action for action in recovery.actions)

    # 3. Corrupting partition bytes in S3 is caught by digest verification on read and audit.
    parquet_key = "archive/usgs_nwis/store/product=level/year=2020/rows.parquet"
    original_bytes = s3_server.objects[("hydro-bucket", parquet_key)]
    s3_server.objects[("hydro-bucket", parquet_key)] = b"X" * len(original_bytes)
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        StoreReader().query(
            StoreQuery(
                store,
                provider,
                ("07374000",),
                ("level",),
                datetime(2020, 1, 1),
                datetime(2020, 1, 31),
            )
        )
    with pytest.raises(ObservationStoreRefusedError, match="digest"):
        rr.audit_cache("usgs_nwis")

    # 4. clear_cache removes the provider's remote objects without touching other providers.
    s3_server.objects[("hydro-bucket", "archive/other_provider/store/manifest.json")] = b"keep"
    cleared = rr.clear_cache("usgs_nwis")
    assert cleared.existed
    assert cleared.bytes_freed > 0
    assert not rr.cache_status("usgs_nwis").exists
    assert ("hydro-bucket", "archive/other_provider/store/manifest.json") in s3_server.objects


def test_public_fetch_and_fetch_by_provider_remote_s3_cache_reuse_refresh_and_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    s3_server: S3TestServer,
) -> None:
    from tests.test_usgs_continuous_cache_axis import STATION, _Spans

    vm1_dir = tmp_path / "vm1"
    vm1_dir.mkdir()
    monkeypatch.chdir(vm1_dir)
    s3_server.configure_env(monkeypatch, bucket="hetzner-bucket", prefix="rivretrieve-cache")

    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge")
    continuous = next(item for item in selected.series if item.product_id == "discharge_instantaneous")
    selected = rr.pick(selected, series_id=continuous.series_id)

    transport = _Spans(continuous.identity.published_id)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    # 1. Initial fetch for 1996..1999 populates year=1999 in S3, and 2000..2003 adds year=2003.
    early = rr.fetch(
        selected,
        start="1996-01-03",
        end="1999-02-01",
        cache="reuse",
        receipts=True,
        on_issue="raise",
    )
    assert len(transport.calls) == 2
    assert early.data.height == 2
    assert (
        "rivretrieve-cache/usgs_nwis/store/product=discharge_instantaneous/year=1999/rows.parquet"
        in s3_server.get_keys("hetzner-bucket")
    )

    first = rr.fetch(
        selected,
        start="2000-01-03",
        end="2003-02-01",
        cache="reuse",
        receipts=True,
        on_issue="raise",
    )
    assert len(transport.calls) == 4
    assert first.data.height == 2
    assert rr.cache_status("usgs_nwis").exists
    assert {
        "rivretrieve-cache/usgs_nwis/store/product=discharge_instantaneous/year=1999/rows.parquet",
        "rivretrieve-cache/usgs_nwis/store/product=discharge_instantaneous/year=2003/rows.parquet",
    }.issubset(s3_server.get_keys("hetzner-bucket"))

    # 2. Switch to an empty local directory (no local files at all) and reuse the remote S3 cache.
    vm2_dir = tmp_path / "vm2"
    vm2_dir.mkdir()
    monkeypatch.chdir(vm2_dir)
    s3_server.requests.clear()
    reused = rr.fetch(
        selected,
        start="2000-01-03",
        end="2003-02-01",
        cache="reuse",
        receipts=True,
        on_issue="raise",
    )
    assert len(transport.calls) == 4
    pl_testing.assert_frame_equal(reused.data, first.data)
    assert list(vm2_dir.iterdir()) == []
    assert s3_server.get_requests_for("GET", "year=2003/rows.parquet") != []
    assert s3_server.get_requests_for("GET", "year=1999/rows.parquet") == []

    # 4. Bundle export and import preserve s3:// receipt path and never leak S3 credentials.
    bundle_bytes = rr.to_bundle(reused)
    assert b"test-access-key" not in bundle_bytes
    assert b"test-secret-key" not in bundle_bytes
    restored = rr.from_bundle(bundle_bytes)
    pl_testing.assert_frame_equal(restored.data, reused.data)
    assert restored.receipts is not None
    assert str(restored.receipts.entries[0].store_path) == "s3://hetzner-bucket/rivretrieve-cache/usgs_nwis/store"

    # 5. fetch_by_provider with cache="refresh" updates the remote S3 cache, and failed refresh keeps held data.
    transport.value = 25
    by_provider = rr.fetch_by_provider(
        selected,
        start="2000-01-03",
        end="2003-02-01",
        cache="refresh",
        on_issue="raise",
    )
    assert len(transport.calls) == 6
    assert by_provider["usgs_nwis"].data.height == 2

    transport.failed_first = True
    transport.failed_second = True
    partial = rr.fetch(
        selected,
        start="2000-01-03",
        end="2003-02-01",
        cache="refresh",
        on_issue="ignore",
    )
    assert partial.data.height == 2
    pl_testing.assert_frame_equal(partial.data, by_provider["usgs_nwis"].data)
