"""S3-compatible object-storage location, configuration and transport boundary for native observation stores."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pyarrow.fs as pafs

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store.lifecycle import (
    LifecycleState,
    Ownership,
    StoreLifecycleError,
    StorePostCommitCleanupError,
    StoreTransactionError,
    _unique_record,
)
from rivretrieve._internal.store.validation import (
    ObservationStoreRefusedError,
    PartitionIdentifier,
    StoreRefusalKind,
    StoreRoot,
    ValidatedStore,
    _check_revision,
    _refuse,
    _supporting_outcomes,
    _validate_store_contents,
    validate_store,
)

if TYPE_CHECKING:
    from rivretrieve._internal.store.integrity import CacheAuditResult, FileIdentity, SealedStore

SEAL_NAME = "integrity.json"

S3_ENV_VARIABLE_NAMES = (
    "RIVRETRIEVE_S3_ENDPOINT_URL",
    "AWS_ENDPOINT_URL_S3",
    "AWS_ENDPOINT_URL",
    "RIVRETRIEVE_S3_REGION",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "RIVRETRIEVE_S3_ACCESS_KEY_ID",
    "AWS_ACCESS_KEY_ID",
    "RIVRETRIEVE_S3_SECRET_ACCESS_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "RIVRETRIEVE_S3_SESSION_TOKEN",
    "AWS_SESSION_TOKEN",
)


@dataclass(frozen=True, slots=True)
class S3StoreConfig:
    """Resolved S3-compatible endpoint and credential configuration for one store root."""

    bucket: str
    prefix: str
    endpoint_url: str | None = None
    region: str | None = None
    access_key_id: str | None = field(default=None, repr=False, compare=False)
    secret_access_key: str | None = field(default=None, repr=False, compare=False)
    session_token: str | None = field(default=None, repr=False, compare=False)


class ObjectStoreClient:
    """Thin PyArrow S3 filesystem adapter for one bucket."""

    def __init__(self, config: S3StoreConfig, *, filesystem: pafs.FileSystem | None = None) -> None:
        self._bucket = config.bucket
        self._config = config
        self._fs: pafs.FileSystem | None = filesystem

    @property
    def filesystem(self) -> pafs.FileSystem:
        if self._fs is None:
            os.environ.setdefault("AWS_REQUEST_CHECKSUM_CALCULATION", "WHEN_REQUIRED")
            os.environ.setdefault("AWS_RESPONSE_CHECKSUM_VALIDATION", "WHEN_REQUIRED")
            scheme: str | None = None
            endpoint_override: str | None = None
            if self._config.endpoint_url is not None:
                scheme, endpoint_override = _parse_endpoint_origin(self._config.endpoint_url)
            region = self._config.region or ("us-east-1" if endpoint_override is not None else None)
            self._fs = pafs.S3FileSystem(
                access_key=self._config.access_key_id,
                secret_key=self._config.secret_access_key,
                session_token=self._config.session_token,
                region=region,
                scheme=scheme,
                endpoint_override=endpoint_override,
            )
        return self._fs

    def _full_path(self, key: str) -> str:
        clean = key.strip("/")
        return f"{self._bucket}/{clean}" if clean else self._bucket

    def list_objects(self, prefix: str) -> dict[str, tuple[int, int | None]]:
        """Return `{relative_key: (size_bytes, mtime_ns)}` for all regular objects under `prefix`."""
        clean_prefix = prefix.strip("/")
        selector_base = self._full_path(clean_prefix)
        infos = self.filesystem.get_file_info(pafs.FileSelector(selector_base, allow_not_found=True, recursive=True))
        prefix_with_slash = f"{selector_base}/"
        found: dict[str, tuple[int, int | None]] = {}
        for info in infos:
            if info.type != pafs.FileType.File:
                continue
            if info.path == selector_base:
                continue
            if not info.path.startswith(prefix_with_slash):
                continue
            rel = info.path[len(prefix_with_slash) :]
            if rel:
                found[rel] = (int(info.size or 0), info.mtime_ns)
        return found

    def get_bytes(self, key: str) -> bytes:
        full = self._full_path(key)
        with self.filesystem.open_input_stream(full) as stream:
            return stream.read()

    def put_bytes(self, key: str, data: bytes) -> None:
        full = self._full_path(key)
        with self.filesystem.open_output_stream(full) as stream:
            stream.write(data)

    def upload_file(self, source: Path, key: str) -> None:
        self.put_bytes(key, source.read_bytes())

    def download_file(self, key: str, destination: Path) -> None:
        data = self.get_bytes(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def copy_object(self, source_key: str, destination_key: str) -> None:
        self.filesystem.copy_file(self._full_path(source_key), self._full_path(destination_key))

    def delete_object(self, key: str) -> None:
        with suppress(FileNotFoundError):
            self.filesystem.delete_file(self._full_path(key))


class RemoteStoreRoot(Path):
    """Typed S3 object-storage location that cannot be used as a local OS filesystem path."""

    bucket: str
    prefix: str
    config: S3StoreConfig
    _client: ObjectStoreClient | None

    def __new__(
        cls,
        bucket: str,
        prefix: str = "",
        *,
        config: S3StoreConfig | None = None,
        client: ObjectStoreClient | None = None,
    ) -> RemoteStoreRoot:
        clean_prefix = prefix.strip("/")
        rel = f"{bucket}/{clean_prefix}" if clean_prefix else bucket
        self = super().__new__(cls, f"s3:/{rel}")
        resolved_config = (
            S3StoreConfig(
                bucket=bucket,
                prefix=clean_prefix,
                endpoint_url=config.endpoint_url,
                region=config.region,
                access_key_id=config.access_key_id,
                secret_access_key=config.secret_access_key,
                session_token=config.session_token,
            )
            if config is not None
            else S3StoreConfig(bucket=bucket, prefix=clean_prefix)
        )
        self.bucket = bucket
        self.prefix = clean_prefix
        self.config = resolved_config
        self._client = client if client is not None else ObjectStoreClient(resolved_config)
        return self

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        config: S3StoreConfig | None = None,
        client: ObjectStoreClient | None = None,
    ) -> None:
        clean_prefix = prefix.strip("/")
        rel = f"{bucket}/{clean_prefix}" if clean_prefix else bucket
        super().__init__(f"s3:/{rel}")

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        config: S3StoreConfig | None = None,
        client: ObjectStoreClient | None = None,
    ) -> RemoteStoreRoot:
        bucket, prefix = parse_s3_cache_uri(uri)
        return cls(bucket, prefix, config=config, client=client)

    @property
    def client(self) -> ObjectStoreClient:
        if self._client is None:
            self._client = ObjectStoreClient(self.config)
        return self._client

    def __str__(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}" if self.prefix else f"s3://{self.bucket}"

    def __repr__(self) -> str:
        return f"RemoteStoreRoot({str(self)!r})"

    def __fspath__(self) -> str:
        raise TypeError("RemoteStoreRoot is an S3 object-storage location, not a local filesystem path")

    @property
    def parent(self) -> RemoteStoreRoot:
        if not self.prefix or "/" not in self.prefix:
            return RemoteStoreRoot(self.bucket, "", config=self.config, client=self._client)
        return RemoteStoreRoot(self.bucket, self.prefix.rsplit("/", 1)[0], config=self.config, client=self._client)

    def child(self, relative_key: str) -> RemoteStoreRoot:
        rel = relative_key.strip("/")
        if not rel:
            return self
        new_prefix = f"{self.prefix}/{rel}" if self.prefix else rel
        return RemoteStoreRoot(self.bucket, new_prefix, config=self.config, client=self._client)

    def __truediv__(self, key: str | os.PathLike[str]) -> RemoteStoreRoot:
        if isinstance(key, RemoteStoreRoot):
            raise TypeError("Cannot join two RemoteStoreRoot instances")
        return self.child(str(key))

    def with_name(self, name: str) -> RemoteStoreRoot:
        return self.parent.child(name)

    def relative_to(self, other: object, *extra: object, walk_up: bool = False) -> Path:
        if isinstance(other, RemoteStoreRoot) and self.bucket == other.bucket:
            base = PurePosixPath(other.prefix) if other.prefix else PurePosixPath(".")
            target = PurePosixPath(self.prefix) if self.prefix else PurePosixPath(".")
            return Path(target.relative_to(base).as_posix())
        raise ValueError(f"{str(self)!r} is not in the subpath of {str(other)!r}")


def parse_s3_cache_uri(uri: str) -> tuple[str, str]:
    """Validate and split `s3://<bucket>[/<prefix>]` into `(bucket, clean_prefix)`."""
    raw = uri.strip()
    if not raw.startswith("s3://"):
        raise ValueError(f"Expected an s3:// cache URI, got {uri!r}")
    rest = raw[len("s3://") :]
    if "?" in rest or "#" in rest:
        raise ValueError("RIVRETRIEVE_CACHE_DIR s3:// URI must not include query parameters or fragments")
    bucket_part, _, path_part = rest.partition("/")
    if "@" in bucket_part:
        raise ValueError("RIVRETRIEVE_CACHE_DIR s3:// URI must not embed credentials")
    bucket = bucket_part.strip()
    if not bucket or "/" in bucket or ":" in bucket:
        raise ValueError("RIVRETRIEVE_CACHE_DIR s3:// URI must include a valid bucket name")
    raw_path = path_part.strip("/")
    if not raw_path:
        return bucket, ""
    if "//" in raw_path:
        raise ValueError("RIVRETRIEVE_CACHE_DIR s3:// URI must not contain empty or parent path segments")
    segments = [segment for segment in raw_path.split("/") if segment]
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError("RIVRETRIEVE_CACHE_DIR s3:// URI must not contain empty or parent path segments")
    return bucket, "/".join(segments)


def _parse_endpoint_origin(endpoint_url: str) -> tuple[str, str]:
    raw = endpoint_url.strip()
    if raw.startswith("https://"):
        scheme, rest = "https", raw[len("https://") :]
    elif raw.startswith("http://"):
        scheme, rest = "http", raw[len("http://") :]
    else:
        raise ValueError(
            "S3 endpoint URL must be a bare http:// or https:// origin without path, query, or embedded credentials"
        )
    if "?" in rest or "#" in rest:
        raise ValueError(
            "S3 endpoint URL must be a bare http:// or https:// origin without path, query, or embedded credentials"
        )
    netloc, sep, path = rest.partition("/")
    if not netloc or "@" in netloc or (sep and path):
        raise ValueError(
            "S3 endpoint URL must be a bare http:// or https:// origin without path, query, or embedded credentials"
        )
    return scheme, netloc


def _read_setting(
    names: tuple[str, ...],
    environ: Mapping[str, str],
    dotenv: Mapping[str, str | None],
) -> tuple[str | None, str | None]:
    for name in names:
        if name in environ:
            value = environ[name].strip()
            if not value:
                raise ValueError(f"{name} must not be empty when set")
            return name, value
    for name in names:
        if name in dotenv and dotenv[name] is not None:
            value = str(dotenv[name]).strip()
            if not value:
                raise ValueError(f"{name} must not be empty when set")
            return name, value
    return None, None


def resolve_remote_store_root(
    uri: str,
    provider_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    dotenv: Mapping[str, str | None] | None = None,
) -> RemoteStoreRoot:
    """Resolve an `s3://` cache URI and S3 settings at a public composition boundary."""
    env = os.environ if environ is None else environ
    dotenv_map = {} if dotenv is None else dotenv
    bucket, base_prefix = parse_s3_cache_uri(uri)
    store_prefix = f"{base_prefix}/{provider_id}/store" if base_prefix else f"{provider_id}/store"

    _, endpoint_url = _read_setting(
        ("RIVRETRIEVE_S3_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL"),
        env,
        dotenv_map,
    )
    if endpoint_url is not None:
        scheme, netloc = _parse_endpoint_origin(endpoint_url)
        endpoint_url = f"{scheme}://{netloc}"

    _, region = _read_setting(
        ("RIVRETRIEVE_S3_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"),
        env,
        dotenv_map,
    )
    _, access_key_id = _read_setting(
        ("RIVRETRIEVE_S3_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
        env,
        dotenv_map,
    )
    _, secret_access_key = _read_setting(
        ("RIVRETRIEVE_S3_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
        env,
        dotenv_map,
    )
    _, session_token = _read_setting(
        ("RIVRETRIEVE_S3_SESSION_TOKEN", "AWS_SESSION_TOKEN"),
        env,
        dotenv_map,
    )

    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError(
            "S3 cache configuration requires both access key ID and secret access key when static credentials are used"
        )
    if session_token is not None and access_key_id is None:
        raise ValueError("S3 session token requires access key ID and secret access key")
    if endpoint_url is not None and access_key_id is None:
        raise ValueError(
            "S3 cache with a custom endpoint requires explicit S3 credentials "
            "(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY or RIVRETRIEVE_S3_ACCESS_KEY_ID and RIVRETRIEVE_S3_SECRET_ACCESS_KEY)"
        )

    config = S3StoreConfig(
        bucket=bucket,
        prefix=store_prefix,
        endpoint_url=endpoint_url,
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        session_token=session_token,
    )
    return RemoteStoreRoot(bucket, store_prefix, config=config)


def _entry(root: RemoteStoreRoot, suffix: str) -> RemoteStoreRoot:
    return root.with_name(f".{root.name}.{suffix}")


def _parent_objects(root: RemoteStoreRoot) -> dict[str, tuple[int, int | None]]:
    return root.client.list_objects(root.parent.prefix)


def _residue_tops(
    root: RemoteStoreRoot, parent_objs: Mapping[str, tuple[int, int | None]]
) -> tuple[RemoteStoreRoot, ...]:
    prefixes = tuple(
        f".{root.name}.{name}" for name in ("stage-", "previous-", "pending-", "backup-", "staging-", "workspace-")
    )
    prefixes += (".publisher-artifacts.rollback-",)
    exact = {
        f".{root.name}.transaction.json",
        f".{root.name}.transaction.new",
        f".{root.name}.write-lock",
    }
    tops = {key.split("/", 1)[0] for key in parent_objs}
    matched = sorted(top for top in tops if top.startswith(prefixes) or top in exact)
    return tuple(root.parent.child(top) for top in matched)


def _remote_ownership(root: RemoteStoreRoot, parent_objs: Mapping[str, tuple[int, int | None]]) -> Ownership:
    lock_name = f".{root.name}.write-lock"
    if any(k == lock_name or k.startswith(f"{lock_name}/") for k in parent_objs):
        return Ownership.AMBIGUOUS
    owner_name = f".{root.name}.owner"
    if owner_name not in parent_objs:
        return Ownership.IDLE
    try:
        text = root.client.get_bytes(root.parent.child(owner_name).prefix).decode("utf-8")
        if not text:
            return Ownership.IDLE
        value = json.loads(text, object_pairs_hook=_unique_record)
        if value == {"state": "idle"}:
            return Ownership.IDLE
        if (
            set(value) == {"host", "pid", "token"}
            and isinstance(value["host"], str)
            and type(value["pid"]) is int
            and value["pid"] > 0
            and isinstance(value["token"], str)
        ):
            return Ownership.ABANDONED
    except (ValueError, TypeError, OSError):
        pass
    return Ownership.AMBIGUOUS


def _remote_journal(root: RemoteStoreRoot, parent_objs: Mapping[str, tuple[int, int | None]]) -> dict[str, str] | None:
    tx_name = f".{root.name}.transaction.json"
    if tx_name not in parent_objs:
        return None
    tx_root = _entry(root, "transaction.json")
    try:
        raw_text = root.client.get_bytes(tx_root.prefix).decode("utf-8")
        value = json.loads(raw_text, object_pairs_hook=_unique_record)
        if (
            set(value) != {"id", "phase"}
            or not isinstance(value["id"], str)
            or len(value["id"]) != 32
            or any(c not in "0123456789abcdef" for c in value["id"])
            or value["phase"] not in {"preparing", "replacing", "committed"}
        ):
            raise ValueError("invalid journal")
        return value
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise StoreLifecycleError(f"Ambiguous transaction journal: {tx_root}") from error


def _write_remote_journal(root: RemoteStoreRoot, record: dict[str, str]) -> None:
    tx_root = _entry(root, "transaction.json")
    root.client.put_bytes(tx_root.prefix, json.dumps(record).encode("utf-8"))


def _remove_remote_tree(
    target: RemoteStoreRoot, parent_objs: Mapping[str, tuple[int, int | None]] | None = None
) -> int:
    rel_prefix = target.relative_to(target.parent).as_posix()
    objs = _parent_objects(target) if parent_objs is None else parent_objs
    freed = 0
    for key, (size, _) in list(objs.items()):
        if key == rel_prefix or key.startswith(f"{rel_prefix}/"):
            target.client.delete_object(target.parent.child(key).prefix)
            freed += size
    return freed


def _copy_remote_tree(
    source: RemoteStoreRoot,
    destination: RemoteStoreRoot,
    parent_objs: Mapping[str, tuple[int, int | None]] | None = None,
) -> None:
    src_rel = source.relative_to(source.parent).as_posix()
    objs = _parent_objects(source) if parent_objs is None else parent_objs
    prefix = f"{src_rel}/"
    for key in sorted(objs):
        if key.startswith(prefix):
            sub = key[len(prefix) :]
            source.client.copy_object(source.child(sub).prefix, destination.child(sub).prefix)


def inspect_remote_lifecycle(root: RemoteStoreRoot) -> LifecycleState:
    """Inspect remote transaction journal, residue prefixes, and committed store presence."""
    parent_objs = _parent_objects(root)
    record = _remote_journal(root, parent_objs)
    residue = _residue_tops(root, parent_objs)
    store_prefix = f"{root.name}/"
    store_exists = any(k.startswith(store_prefix) for k in parent_objs)
    committed: Path | None = root if store_exists else None
    pending_key = f"{root.name}/.integrity.pending"
    cleanup: tuple[Path, ...] = (root.child(".integrity.pending"),) if pending_key in parent_objs else ()
    if record:
        stage = _entry(root, f"stage-{record['id']}")
        previous = _entry(root, f"previous-{record['id']}")
        stage_exists = stage in residue
        previous_exists = previous in residue
        installed = record["phase"] in {"replacing", "committed"} and not stage_exists and store_exists
        if installed:
            cleanup = (*cleanup, *residue)
        elif not store_exists and previous_exists and record["phase"] == "replacing":
            committed = previous
    return LifecycleState(
        committed,
        tuple(p for p in residue if p not in cleanup),
        cleanup,
        _remote_ownership(root, parent_objs),
        record["id"] if record else None,
    )


def remote_inventory_witness(root: RemoteStoreRoot) -> tuple[tuple[object, ...], ...]:
    try:
        objs = root.client.list_objects(root.prefix)
        return tuple((name, size, mtime_ns) for name, (size, mtime_ns) in sorted(objs.items()))
    except OSError:
        return ()


def _rewrite_refusal_store(
    error: ObservationStoreRefusedError, target_store: StoreRoot
) -> ObservationStoreRefusedError:
    return ObservationStoreRefusedError(replace(error.refusal, store=target_store))


def _read_raw_manifest_bytes(raw_bytes: bytes, store: StoreRoot, provider_id: ProviderId) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, f"manifest.json:{error}")
    if not isinstance(parsed, dict):
        _refuse(StoreRefusalKind.MALFORMED, store, provider_id, "manifest.json:root must be a JSON object")
    return parsed


def inspect_remote_integrity(
    root: RemoteStoreRoot,
    provider_id: ProviderId,
    *,
    allow_pending: bool = False,
) -> SealedStore:
    """Check closed remote object inventory and metadata without downloading observation partitions."""
    from rivretrieve._internal.store.integrity import FileIdentity, SealedStore, _canonical, _fail, _generation_id

    store_root = StoreRoot(root)
    try:
        remote_objects = root.client.list_objects(root.prefix)
    except OSError as error:
        _fail(store_root, provider_id, f"inventory_io:{error}")
    if "manifest.json" not in remote_objects:
        _fail(store_root, provider_id, "manifest:missing")
    try:
        manifest_bytes = root.client.get_bytes(root.child("manifest.json").prefix)
    except OSError as error:
        _fail(store_root, provider_id, f"manifest:{error}")
    raw_manifest = _read_raw_manifest_bytes(manifest_bytes, store_root, provider_id)
    _check_revision(raw_manifest, store_root, provider_id)

    if SEAL_NAME not in remote_objects:
        _fail(store_root, provider_id, "seal:missing")
    try:
        seal_bytes = root.client.get_bytes(root.child(SEAL_NAME).prefix)

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate seal key")
                result[key] = value
            return result

        raw_seal = json.loads(seal_bytes.decode("utf-8"), object_pairs_hook=unique)
        if (
            set(raw_seal) != {"version", "provider_id", "generation_id", "seal_sha256", "files"}
            or raw_seal["version"] != 1
        ):
            raise ValueError("seal schema")
        if raw_seal["provider_id"] != provider_id:
            raise ValueError("seal provider")
        checksum = raw_seal.pop("seal_sha256")
        if checksum != hashlib.sha256(_canonical(raw_seal)).hexdigest():
            raise ValueError("seal checksum")
        generation = raw_seal["generation_id"]
        if generation != _generation_id(raw_seal["provider_id"], raw_seal["files"]):
            raise ValueError("seal generation")
        files: dict[str, FileIdentity] = {}
        for name, item in raw_seal["files"].items():
            if not isinstance(name, str) or name.startswith("/") or ".." in Path(name).parts or name == SEAL_NAME:
                raise ValueError("seal path")
            if set(item) != {"sha256", "device", "inode", "size", "mtime_ns", "ctime_ns"}:
                raise ValueError("seal file")
            if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise ValueError("seal digest")
            if any(
                type(item[key]) is not int or item[key] < 0
                for key in ("device", "inode", "size", "mtime_ns", "ctime_ns")
            ):
                raise ValueError("seal witness")
            files[name] = FileIdentity(**item)
        if "manifest.json" not in files:
            raise ValueError("seal manifest")
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        _fail(store_root, provider_id, f"seal:{error}")

    pending = {".integrity.pending"} if allow_pending and ".integrity.pending" in remote_objects else set()
    expected_keys = {*files, SEAL_NAME, *pending}
    for key in remote_objects:
        if key not in expected_keys:
            _fail(store_root, provider_id, f"unlisted_or_unsafe:{key}")
    if set(remote_objects) != expected_keys:
        _fail(store_root, provider_id, "inventory")

    for name, identity in files.items():
        actual_size, _ = remote_objects[name]
        if actual_size != identity.size:
            _fail(store_root, provider_id, f"file_identity:{name}")

    if hashlib.sha256(manifest_bytes).hexdigest() != files["manifest.json"].sha256:
        _fail(store_root, provider_id, "digest:manifest.json")

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "manifest.json").write_bytes(manifest_bytes)
        for name in files:
            if name != "manifest.json":
                placeholder = tmp_path / name
                placeholder.parent.mkdir(parents=True, exist_ok=True)
                placeholder.write_bytes(b"")
        try:
            validated_local = _validate_store_contents(StoreRoot(tmp_path), provider_id, frozenset())
        except ObservationStoreRefusedError as error:
            raise _rewrite_refusal_store(error, store_root) from error

    remote_partitions = {
        identifier: root.child(path.relative_to(tmp_path).as_posix())
        for identifier, path in validated_local.partition_files.items()
    }
    expected_manifest_files = {
        "manifest.json",
        *(path.relative_to(root).as_posix() for path in remote_partitions.values()),
    }
    if set(files) != expected_manifest_files:
        _fail(store_root, provider_id, "manifest_inventory")

    validated_remote = ValidatedStore(
        root=store_root,
        manifest=validated_local.manifest,
        partition_files=remote_partitions,
    )
    return SealedStore(
        validated_remote,
        generation,
        files,
        _supporting_outcomes(raw_manifest),
        seal_size=remote_objects[SEAL_NAME][0],
    )


def verify_remote_files(sealed: SealedStore, identifiers: Iterable[PartitionIdentifier]) -> None:
    """Verify selected partition digests against freshly inspected remote metadata."""
    from rivretrieve._internal.store.integrity import _fail

    root = sealed.store.root
    assert isinstance(root, RemoteStoreRoot)
    provider = sealed.store.manifest.provider_id
    current = inspect_remote_integrity(root, provider)
    if current.generation_id != sealed.generation_id:
        _fail(root, provider, "generation_changed")
    for identifier in set(identifiers):
        part_path = current.store.partition_files[identifier]
        name = part_path.relative_to(root).as_posix()
        try:
            data = root.client.get_bytes(root.child(name).prefix)
        except OSError:
            _fail(root, provider, f"digest:{name}")
        if len(data) != current.files[name].size or hashlib.sha256(data).hexdigest() != current.files[name].sha256:
            _fail(root, provider, f"digest:{name}")


def materialize_verified_remote_partitions(
    sealed: SealedStore,
    identifiers: Iterable[PartitionIdentifier],
    destination_dir: Path,
) -> dict[PartitionIdentifier, Path]:
    """Download and verify only the requested partitions into `destination_dir`."""
    from rivretrieve._internal.store.integrity import _fail

    root = sealed.store.root
    assert isinstance(root, RemoteStoreRoot)
    provider = sealed.store.manifest.provider_id
    local_paths: dict[PartitionIdentifier, Path] = {}
    unique_identifiers: list[PartitionIdentifier] = list(dict.fromkeys(identifiers))
    unique_identifiers.sort(key=lambda item: str(item).encode("utf-8"))
    for identifier in unique_identifiers:
        part_path = sealed.store.partition_files[identifier]
        name = part_path.relative_to(root).as_posix()
        try:
            data = root.client.get_bytes(root.child(name).prefix)
        except OSError:
            _fail(root, provider, f"digest:{name}")
        expected = sealed.files[name]
        if len(data) != expected.size or hashlib.sha256(data).hexdigest() != expected.sha256:
            _fail(root, provider, f"digest:{name}")
        target = destination_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        local_paths[identifier] = target
    return local_paths


def audit_remote_store(
    root: RemoteStoreRoot,
    provider_id: ProviderId,
    *,
    allow_pending: bool = False,
) -> CacheAuditResult:
    """Download and verify every sealed byte and semantic rule of one remote generation."""
    from rivretrieve._internal.store.integrity import CacheAuditResult, _fail

    store_root = StoreRoot(root)
    sealed = inspect_remote_integrity(root, provider_id, allow_pending=allow_pending)
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for name, identity in sealed.files.items():
            try:
                data = root.client.get_bytes(root.child(name).prefix)
            except OSError:
                _fail(store_root, provider_id, f"digest:{name}")
            if len(data) != identity.size or hashlib.sha256(data).hexdigest() != identity.sha256:
                _fail(store_root, provider_id, f"digest:{name}")
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        try:
            checked = validate_store(StoreRoot(tmp_path), provider_id)
        except ObservationStoreRefusedError as error:
            raise _rewrite_refusal_store(error, store_root) from error

    after = inspect_remote_integrity(root, provider_id, allow_pending=allow_pending)
    if after.generation_id != sealed.generation_id:
        _fail(store_root, provider_id, "generation_changed")
    return CacheAuditResult(
        provider_id,
        root,
        sealed.generation_id,
        datetime.now(UTC),
        len(checked.partition_files),
        sum(checked.manifest.partition_row_counts.values()),
        sum(item.size for item in sealed.files.values()),
    )


def seal_remote_stage(
    stage_dir: Path,
    remote_root: RemoteStoreRoot,
    provider_id: ProviderId,
    *,
    previous: SealedStore | None = None,
    reused_identities: Mapping[PartitionIdentifier, tuple[str, FileIdentity]] | None = None,
) -> SealedStore:
    """Validate staged new/changed files and reused remote partitions, writing `integrity.json` to `stage_dir`."""
    from rivretrieve._internal.store.integrity import (
        FileIdentity,
        SealedStore,
        _canonical,
        _digest,
        _fail,
        _generation_id,
        _preserves_support,
        _record,
    )

    reused_map = dict(reused_identities or {})
    stage_store = StoreRoot(stage_dir)
    remote_store = StoreRoot(remote_root)

    for rel_name, _ in reused_map.values():
        placeholder = stage_dir / rel_name
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        if not placeholder.exists():
            placeholder.write_bytes(b"")

    try:
        candidate_meta = _validate_store_contents(stage_store, provider_id, frozenset())
    except ObservationStoreRefusedError as error:
        raise _rewrite_refusal_store(error, remote_store) from error

    if reused_map:
        if previous is None or not set(reused_map).issubset(candidate_meta.partition_files):
            _fail(remote_store, provider_id, "reuse_prior")
        for identifier, (rel_name, identity) in reused_map.items():
            prev_rel = previous.store.partition_files[identifier].relative_to(previous.store.root).as_posix()
            if (
                rel_name != prev_rel
                or (identity.sha256, identity.size) != (previous.files[prev_rel].sha256, previous.files[prev_rel].size)
                or candidate_meta.manifest.partition_row_counts[identifier]
                != previous.store.manifest.partition_row_counts[identifier]
            ):
                _fail(remote_store, provider_id, "reuse_record")
        _preserves_support(previous.store, candidate_meta, set(reused_map))

    checked_subset = frozenset(set(candidate_meta.partition_files) - set(reused_map))
    try:
        candidate = _validate_store_contents(stage_store, provider_id, checked_subset)
    except ObservationStoreRefusedError as error:
        raise _rewrite_refusal_store(error, remote_store) from error

    expected_names = {
        "manifest.json",
        *(path.relative_to(stage_dir).as_posix() for path in candidate.partition_files.values()),
    }
    inherited_by_name = dict(reused_map.values())
    files: dict[str, FileIdentity] = {}
    for name in sorted(expected_names):
        if name in inherited_by_name:
            files[name] = inherited_by_name[name]
        else:
            local_file = stage_dir / name
            size = local_file.stat().st_size
            digest = _digest(local_file)
            files[name] = FileIdentity(digest, 0, 0, size, 0, 0)

    records = {name: _record(item) for name, item in files.items()}
    generation = _generation_id(str(provider_id), records)
    payload: dict[str, object] = {
        "version": 1,
        "provider_id": str(provider_id),
        "files": records,
        "generation_id": generation,
    }
    payload["seal_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    seal_bytes = _canonical(payload)
    (stage_dir / SEAL_NAME).write_bytes(seal_bytes)

    raw_manifest = _read_raw_manifest_bytes((stage_dir / "manifest.json").read_bytes(), remote_store, provider_id)
    remote_partitions = {
        identifier: remote_root.child(path.relative_to(stage_dir).as_posix())
        for identifier, path in candidate.partition_files.items()
    }
    validated_remote = ValidatedStore(
        root=remote_store,
        manifest=candidate.manifest,
        partition_files=remote_partitions,
    )
    return SealedStore(
        validated_remote,
        generation,
        files,
        _supporting_outcomes(raw_manifest),
        seal_size=len(seal_bytes),
    )


class RemoteStoreTransaction:
    """Stage locally, upload to `.store.stage-<id>`, back up prior store to `.store.previous-<id>`, and replace."""

    def __init__(self, root: RemoteStoreRoot, temp_dir: Path) -> None:
        self.root = root
        self.transaction_id = uuid4().hex
        self.record = {"id": self.transaction_id, "phase": "preparing"}
        self.stage = temp_dir / f"stage-{self.transaction_id}"
        self.workspace = temp_dir / f"workspace-{self.transaction_id}"
        self.remote_stage = _entry(root, f"stage-{self.transaction_id}")
        self.remote_previous = _entry(root, f"previous-{self.transaction_id}")
        self.cleanup_paths: tuple[Path, ...] = ()
        self.after_cleanup: Callable[[Path], object] | None = None
        self.committed = False
        self.generation_id: str | None = None
        self._reused_relpaths: set[str] = set()
        _write_remote_journal(root, self.record)

    def register_cleanup(self, paths: tuple[Path, ...]) -> None:
        self.cleanup_paths = tuple(dict.fromkeys((*self.cleanup_paths, *paths)))

    def set_reused_relpaths(self, relpaths: Iterable[str]) -> None:
        self._reused_relpaths = set(relpaths)

    def publish(self, validate: Callable[[Path], object]) -> object:
        if self.committed:
            raise StoreLifecycleError("Transaction has already committed")
        validated = validate(self.stage)
        generation_id = getattr(validated, "generation_id", None)
        self.generation_id = generation_id if isinstance(generation_id, str) else None

        # 1. Upload new/modified files to remote_stage and server-side copy reused partitions.
        for path in sorted(self.stage.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.stage).as_posix()
            if rel in self._reused_relpaths:
                self.root.client.copy_object(self.root.child(rel).prefix, self.remote_stage.child(rel).prefix)
            else:
                self.root.client.upload_file(path, self.remote_stage.child(rel).prefix)

        # 2. If a committed store exists, back it up to remote_previous before entering "replacing".
        existing_store_objs = self.root.client.list_objects(self.root.prefix)
        if existing_store_objs:
            for rel in sorted(existing_store_objs):
                self.root.client.copy_object(self.root.child(rel).prefix, self.remote_previous.child(rel).prefix)

        # 3. Advance journal to "replacing".
        self.record["phase"] = "replacing"
        _write_remote_journal(self.root, self.record)

        # 4. Replace canonical store objects: remove old seal and retired files first, copy new files, write seal last.
        staged_files = {path.relative_to(self.stage).as_posix() for path in self.stage.rglob("*") if path.is_file()}
        if SEAL_NAME in existing_store_objs:
            self.root.client.delete_object(self.root.child(SEAL_NAME).prefix)
        for rel in sorted(set(existing_store_objs) - staged_files):
            self.root.client.delete_object(self.root.child(rel).prefix)
        for rel in sorted(staged_files - {SEAL_NAME} - self._reused_relpaths):
            self.root.client.copy_object(self.remote_stage.child(rel).prefix, self.root.child(rel).prefix)
        if SEAL_NAME in staged_files:
            self.root.client.copy_object(self.remote_stage.child(SEAL_NAME).prefix, self.root.child(SEAL_NAME).prefix)

        # 5. Remove remote_stage: absence of remote_stage + presence of root marks commit!
        _remove_remote_tree(self.remote_stage)
        self.committed = True
        self.record["phase"] = "committed"
        _write_remote_journal(self.root, self.record)
        return validated

    def _finish(self, original: BaseException | None) -> None:
        errors: list[BaseException] = []
        parent_objs = _parent_objects(self.root)
        residue_before = _residue_tops(self.root, parent_objs)
        store_exists = any(k.startswith(f"{self.root.name}/") for k in parent_objs)
        stage_exists = self.remote_stage in residue_before
        previous_exists = self.remote_previous in residue_before

        committed = self.committed or (
            self.record["phase"] in {"replacing", "committed"} and not stage_exists and store_exists
        )
        self.committed = committed
        if not committed and previous_exists:
            try:
                _remove_remote_tree(self.root, parent_objs)
                _copy_remote_tree(self.remote_previous, self.root, parent_objs)
                _remove_remote_tree(self.remote_previous)
            except OSError as error:
                errors.append(error)
        elif not committed and not previous_exists and self.record["phase"] == "replacing":
            try:
                _remove_remote_tree(self.root, parent_objs)
            except OSError as error:
                errors.append(error)

        if not committed and not errors:
            self.record["phase"] = "preparing"
            try:
                _write_remote_journal(self.root, self.record)
            except OSError as error:
                errors.append(error)

        cleanup_targets = (self.remote_previous,) if committed else (self.remote_stage,)
        for target in cleanup_targets:
            try:
                _remove_remote_tree(target)
            except OSError as error:
                errors.append(error)

        if not errors:
            for tx_suffix in ("transaction.new", "transaction.json"):
                try:
                    self.root.client.delete_object(_entry(self.root, tx_suffix).prefix)
                except OSError as error:
                    errors.append(error)

        prior = original if isinstance(original, StoreTransactionError) else None
        if errors or prior is not None or (original is not None and committed):
            after_objs = _parent_objects(self.root)
            after_store = any(k.startswith(f"{self.root.name}/") for k in after_objs)
            after_prev = self.remote_previous in _residue_tops(self.root, after_objs)
            kind = StorePostCommitCleanupError if committed else StoreTransactionError
            cause = prior.original if prior is not None else original or errors[0]
            raise kind(
                cause,
                cleanup_errors=(*(prior.cleanup_errors if prior is not None else ()), *errors),
                committed_path=self.root if after_store else self.remote_previous if after_prev else None,
                transaction_id=self.transaction_id,
                generation_id=self.generation_id if committed else None,
                residue_paths=_residue_tops(self.root, after_objs),
            ) from cause


@contextmanager
def remote_store_transaction(root: RemoteStoreRoot) -> Iterator[RemoteStoreTransaction]:
    parent_objs = _parent_objects(root)
    if _remote_ownership(root, parent_objs) is not Ownership.IDLE or _residue_tops(root, parent_objs):
        raise StoreLifecycleError("Interrupted work or cleanup residue requires explicit recovery")
    with TemporaryDirectory() as tmp:
        transaction = RemoteStoreTransaction(root, Path(tmp))
        try:
            yield transaction
        except BaseException as error:
            transaction._finish(error)
            raise
        else:
            transaction._finish(None)


def recover_remote_store(root: RemoteStoreRoot, validate: Callable[[Path], object]) -> tuple[str, ...]:
    """Validate the committed remote candidate before restoring or removing transaction residue."""
    parent_objs = _parent_objects(root)
    ownership = _remote_ownership(root, parent_objs)
    if ownership in (Ownership.ACTIVE, Ownership.AMBIGUOUS):
        raise StoreLifecycleError(f"Store ownership requires recovery: {ownership}")
    record = _remote_journal(root, parent_objs)
    residue = _residue_tops(root, parent_objs)
    actions: list[str] = []
    generation_id: str | None = None

    if ownership is Ownership.ABANDONED:
        owner_root = _entry(root, "owner")
        root.client.put_bytes(owner_root.prefix, json.dumps({"state": "idle"}).encode("utf-8"))
        actions.append(f"released abandoned ownership: {owner_root}")

    def validate_candidate(candidate: RemoteStoreRoot) -> None:
        nonlocal generation_id
        validated = validate(candidate)
        identity = getattr(validated, "generation_id", None)
        generation_id = identity if isinstance(identity, str) else None
        pending_key = f"{candidate.relative_to(candidate.parent).as_posix()}/.integrity.pending"
        if pending_key in parent_objs:
            candidate.client.delete_object(candidate.child(".integrity.pending").prefix)
            actions.append(f"removed {candidate.child('.integrity.pending')}")

    store_exists = any(k.startswith(f"{root.name}/") for k in parent_objs)
    if record is None:
        temporary = _entry(root, "transaction.new")
        if any(path != temporary for path in residue):
            raise StoreLifecycleError("Unjournaled store residue; cannot infer committed generation")
        if store_exists:
            validate_candidate(root)
        if temporary in residue:
            _remove_remote_tree(temporary, parent_objs)
            actions.append(f"removed {temporary}")
        return tuple(actions)

    stage = _entry(root, f"stage-{record['id']}")
    previous = _entry(root, f"previous-{record['id']}")
    workspace = _entry(root, f"workspace-{record['id']}")
    allowed = {stage, previous, workspace, _entry(root, "transaction.json"), _entry(root, "transaction.new")}
    if any(p not in allowed for p in residue):
        raise StoreLifecycleError("Multiple transactions; recovery is ambiguous")

    stage_exists = stage in residue
    previous_exists = previous in residue
    installed = record["phase"] in {"replacing", "committed"} and not stage_exists and store_exists
    if installed:
        validate_candidate(root)
        actions.append(f"kept committed store: {root}")
    elif record["phase"] == "committed":
        raise StoreLifecycleError("Committed store missing or conflicting stage; refusing backup restoration")
    elif previous_exists and record["phase"] == "preparing":
        raise StoreLifecycleError("Previous store contradicts preparation journal")
    elif store_exists and previous_exists:
        raise StoreLifecycleError("Conflicting committed paths")
    elif previous_exists:
        validate_candidate(previous)
        _remove_remote_tree(root, parent_objs)
        _copy_remote_tree(previous, root, parent_objs)
        actions.append(f"restored previous store: {previous} -> {root}")
    elif store_exists:
        validate_candidate(root)
        actions.append(f"kept previous store: {root}")
    elif record["phase"] == "replacing" and not stage_exists:
        raise StoreLifecycleError("No recoverable store or staged candidate")

    if not installed:
        record["phase"] = "preparing"
        _write_remote_journal(root, record)
    for target in (stage, previous, workspace, _entry(root, "transaction.new"), _entry(root, "transaction.json")):
        if target in residue:
            _remove_remote_tree(target)
            actions.append(f"removed {target}")
    return tuple(actions)


def clear_remote_store(root: RemoteStoreRoot) -> tuple[tuple[Path, ...], int]:
    """Remove owned remote store and recognized transaction residue, returning `(removed_paths, bytes_freed)`."""
    parent_objs = _parent_objects(root)
    ownership = _remote_ownership(root, parent_objs)
    if ownership in (Ownership.ACTIVE, Ownership.AMBIGUOUS):
        raise StoreLifecycleError(f"Store ownership requires recovery: {ownership}")
    store_exists = any(k.startswith(f"{root.name}/") for k in parent_objs)
    residue = _residue_tops(root, parent_objs)
    candidates: list[RemoteStoreRoot] = []
    if store_exists:
        candidates.append(root)
    candidates.extend(residue)
    removed: list[Path] = []
    bytes_freed = 0
    for target in candidates:
        freed = _remove_remote_tree(target, parent_objs)
        bytes_freed += freed
        removed.append(target)
    return tuple(removed), bytes_freed
