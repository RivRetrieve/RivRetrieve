"""Content identities for one local observation-store generation.

Inspection hashes metadata, inventories paths, and checks file identities. It never
reads observation bytes. Selected reads and complete audits verify content hashes.
Hardlink reuse preserves those hashes; it does not certify changed bytes. The cheap
witness includes ctime. Owned hardlink operations advance this witness under the
writer lease. Interrupted transitions require verification against the old digest.
This is corruption detection, not authentication against an attacker who can edit
both data and its seal. Concurrent external mutation is unsupported.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import islice
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome
from rivretrieve._internal.store.authority import retained_snapshot_outcome
from rivretrieve._internal.store.validation import (
    AccumulatedStoreManifest,
    PartitionIdentifier,
    StoreRefusalKind,
    StoreRoot,
    ValidatedStore,
    _check_revision,
    _read_raw_manifest,
    _refuse,
    _supporting_outcomes,
    _validate_store_contents,
    validate_store,
)
from rivretrieve._internal.time_axis import TimeAxis

SEAL_NAME = "integrity.json"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @property
    def witness(self) -> tuple[int, int, int, int, int]:
        return self.device, self.inode, self.size, self.mtime_ns, self.ctime_ns


@dataclass(frozen=True, slots=True)
class SealedStore:
    store: ValidatedStore
    generation_id: str
    files: Mapping[str, FileIdentity]
    supporting_outcomes: tuple[RetrievalOutcome, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    @property
    def bytes_on_disk(self) -> int:
        return sum(item.size for item in self.files.values()) + (Path(self.store.root) / SEAL_NAME).stat().st_size


@dataclass(frozen=True, slots=True)
class ReusedPartition:
    generation_id: str
    identifier: PartitionIdentifier
    destination: Path
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class CacheAuditResult:
    """A complete local integrity and semantic check of one generation.

    A returned result means every managed file and observation passed its local
    checks. It does not repeat certification against publisher artifacts.
    ``bytes_checked`` counts the sealed metadata and partition bytes hashed.
    ``checked_at`` is the UTC completion instant.
    """

    provider_id: ProviderId
    path: Path
    generation_id: str
    checked_at: datetime
    partitions_checked: int
    rows_checked: int
    bytes_checked: int


def _fail(root: StoreRoot, provider: ProviderId, reason: str) -> NoReturn:
    _refuse(StoreRefusalKind.MALFORMED, root, provider, "integrity." + reason)


def _witness(path: Path) -> tuple[int, int, int, int, int]:
    item = path.lstat()
    if not stat.S_ISREG(item.st_mode):
        raise ValueError("not a regular file")
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _closed_files(root: StoreRoot, provider: ProviderId, expected: set[str]) -> None:
    """Reject every unlisted entry, special file and managed symlink."""
    try:
        if not stat.S_ISDIR(Path(root).lstat().st_mode):
            _fail(root, provider, "root")
        directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
        pending = [Path(root)]
        found: set[str] = set()
        while pending:
            for path in pending.pop().iterdir():
                name = path.relative_to(root).as_posix()
                mode = path.lstat().st_mode
                if stat.S_ISDIR(mode) and name in directories:
                    pending.append(path)
                elif stat.S_ISREG(mode) and name in expected:
                    found.add(name)
                else:
                    _fail(root, provider, f"unlisted_or_unsafe:{name}")
        if found != expected:
            _fail(root, provider, "inventory")
    except OSError as error:
        _fail(root, provider, f"inventory_io:{error}")


def _record(identity: FileIdentity) -> dict[str, object]:
    return {
        "sha256": identity.sha256,
        "device": identity.device,
        "inode": identity.inode,
        "size": identity.size,
        "mtime_ns": identity.mtime_ns,
        "ctime_ns": identity.ctime_ns,
    }


def _check_identity(root: StoreRoot, provider: ProviderId, name: str, identity: FileIdentity) -> None:
    try:
        if _witness(Path(root) / name) != identity.witness:
            _fail(root, provider, f"file_identity:{name}")
    except (OSError, ValueError):
        _fail(root, provider, f"file_identity:{name}")


def inspect_integrity(root: StoreRoot, provider_id: ProviderId, *, allow_pending: bool = False) -> SealedStore:
    """Check the closed inventory and metadata without opening observations.

    Published stores require a seal. Inspection checks device, inode, size and
    mtime. A ctime-only change is retained as an unverified transition: writers
    must verify the original digest before reuse. Inspection never establishes
    observation-byte integrity; selected verification and audit do that.
    ``allow_pending`` is only for lifecycle inspection after it has identified
    the exact regular pending-seal entry. It never accepts links or pending data.
    """
    return _inspect_integrity(root, provider_id, allow_ctime_drift=True, allow_pending=allow_pending)


def _inspect_integrity(
    root: StoreRoot,
    provider_id: ProviderId,
    *,
    allow_ctime_drift: bool,
    allow_pending: bool = False,
) -> SealedStore:
    seal_path = Path(root) / SEAL_NAME
    try:
        if not stat.S_ISDIR(Path(root).lstat().st_mode):
            _fail(root, provider_id, "root")
        _witness(Path(root) / "manifest.json")
    except (OSError, ValueError) as error:
        _fail(root, provider_id, f"manifest:{error}")
    # Explain an obsolete layout before the seal check. Other semantic rules
    # remain behind digest verification, and valid unsealed stores still refuse.
    _check_revision(_read_raw_manifest(root, provider_id), root, provider_id)
    try:
        _witness(seal_path)

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate seal key")
                result[key] = value
            return result

        raw = json.loads(seal_path.read_bytes(), object_pairs_hook=unique)
        if set(raw) != {"version", "provider_id", "generation_id", "seal_sha256", "files"} or raw["version"] != 1:
            raise ValueError("seal schema")
        if raw["provider_id"] != provider_id:
            raise ValueError("seal provider")
        checksum = raw.pop("seal_sha256")
        if checksum != hashlib.sha256(_canonical(raw)).hexdigest():
            raise ValueError("seal checksum")
        generation = raw["generation_id"]
        if generation != _generation_id(raw["provider_id"], raw["files"]):
            raise ValueError("seal generation")
        files: dict[str, FileIdentity] = {}
        for name, item in raw["files"].items():
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
        _fail(root, provider_id, f"seal:{error}")
    pending = {".integrity.pending"} if allow_pending and (Path(root) / ".integrity.pending").exists() else set()
    _closed_files(root, provider_id, {*files, SEAL_NAME, *pending})
    for name, identity in files.items():
        if allow_ctime_drift:
            if _witness(Path(root) / name)[:-1] != identity.witness[:-1]:
                _fail(root, provider_id, f"file_identity:{name}")
        else:
            _check_identity(root, provider_id, name, identity)
    if _digest(Path(root) / "manifest.json") != files["manifest.json"].sha256:
        _fail(root, provider_id, "digest:manifest.json")
    store = _validate_store_contents(root, provider_id, frozenset())
    expected = {"manifest.json", *(path.relative_to(root).as_posix() for path in store.partition_files.values())}
    if set(files) != expected:
        _fail(root, provider_id, "manifest_inventory")
    return SealedStore(store, generation, files, _supporting_outcomes(_read_raw_manifest(root, provider_id)))


def verify_files(sealed: SealedStore, identifiers: Iterable[PartitionIdentifier]) -> None:
    """Hash selected observation files before use; metadata must be freshly inspected.

    This is the request-bounded verification contract. It does not check unselected
    observation bytes. A cached SealedStore is not permanent trust in its paths.
    """
    current = inspect_integrity(sealed.store.root, sealed.store.manifest.provider_id)
    if current.generation_id != sealed.generation_id:
        _fail(sealed.store.root, sealed.store.manifest.provider_id, "generation_changed")
    for identifier in set(identifiers):
        path = current.store.partition_files[identifier]
        name = path.relative_to(current.store.root).as_posix()
        before = _witness(path)
        if _digest(path) != current.files[name].sha256 or _witness(path) != before:
            _fail(current.store.root, current.store.manifest.provider_id, f"digest:{name}")


def link_partition(previous: SealedStore, identifier: PartitionIdentifier, destination: Path) -> ReusedPartition:
    """Link an unchanged partition after checking its captured file identity.

    Writers must unlink the candidate entry before writing changed content. The
    inherited digest remains authoritative. A changed ctime triggers a digest
    check against the previous seal before reuse, including restored-mtime edits.
    """
    source = previous.store.partition_files[identifier]
    name = source.relative_to(previous.store.root).as_posix()
    identity = previous.files[name]
    before = _witness(source)
    if before != identity.witness:
        # An interrupted owned transition and a timestamp-restoring rewrite are
        # indistinguishable from stat alone. Preserve the original content hash.
        if _digest(source) != identity.sha256 or _witness(source) != before:
            _fail(previous.store.root, previous.store.manifest.provider_id, f"digest:{name}")
        if before[:-1] != identity.witness[:-1]:
            _fail(previous.store.root, previous.store.manifest.provider_id, f"file_identity:{name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination, follow_symlinks=False)
    after = _witness(destination)
    if after[:-1] != identity.witness[:-1] or _witness(source) != after:
        _fail(previous.store.root, previous.store.manifest.provider_id, "linked_identity")
    linked = FileIdentity(identity.sha256, *after)
    return ReusedPartition(previous.generation_id, identifier, destination, linked)


def _preserves_support(previous: ValidatedStore, candidate: ValidatedStore, reused: set[PartitionIdentifier]) -> None:
    old, new = previous.manifest, candidate.manifest
    if not isinstance(old, AccumulatedStoreManifest) or not isinstance(new, AccumulatedStoreManifest):
        _fail(candidate.root, new.provider_id, "reuse_requires_accumulated_store")
    definitions = {item.series_id: item for item in new.series}
    old_definitions = {item.series_id: item for item in old.series}
    old_outcomes = {item.outcome_id: item for item in old.outcomes}
    new_outcomes = {item.outcome_id: item for item in new.outcomes}
    years: dict[str, set[int]] = defaultdict(set)
    for identifier in reused:
        product, year = str(identifier).split("/")
        years[product.removeprefix("product=")].add(int(year.removeprefix("year=")))
    for definition in old.series:
        if definition.product_id not in years:
            continue
        retained = definitions.get(definition.series_id)
        retained_facts = {} if retained is None else {fact.facts_id: fact for fact in retained.facts}
        if (
            retained is None
            or retained.identity != definition.identity
            or retained.station_id != definition.station_id
            or retained.product_id != definition.product_id
            or any(retained_facts.get(fact.facts_id) != fact for fact in definition.facts)
        ):
            _fail(candidate.root, new.provider_id, f"reuse_series:{definition.series_id}")
    spans: dict[tuple[str, str, TimeAxis, str], list[tuple[datetime, datetime]]] = defaultdict(list)
    for coverage in new.coverage:
        for facts_id in coverage.facts_ids:
            spans[(coverage.series_id, facts_id, coverage.interval.axis, coverage.outcome_id)].append(
                (coverage.interval.start, coverage.interval.end)
            )
    for values in spans.values():
        values.sort()
    starts = {key: [span[0] for span in values] for key, values in spans.items()}
    for coverage in old.coverage:
        product = old_definitions[coverage.series_id].product_id
        margin = timedelta(days=1) if coverage.interval.axis is TimeAxis.UTC else timedelta(0)
        possible = range(max(1, coverage.interval.start.year - 1), min(9999, coverage.interval.end.year + 1) + 1)
        for year in years.get(product, set()).intersection(possible):
            lower = datetime(year, 1, 1)
            upper = datetime(year, 12, 31, 23, 59, 59, 999999)
            if year > 1:
                lower -= margin
            if year < 9999:
                upper += margin
            start, end = max(coverage.interval.start, lower), min(coverage.interval.end, upper)
            if start > end:
                continue
            if new_outcomes.get(coverage.outcome_id) != old_outcomes[coverage.outcome_id]:
                _fail(candidate.root, new.provider_id, f"reuse_acquisition:{coverage.outcome_id}")
            for facts_id in coverage.facts_ids:
                key = (coverage.series_id, facts_id, coverage.interval.axis, coverage.outcome_id)
                intervals = spans.get(key, [])
                position = max(0, bisect_right(starts.get(key, []), start) - 1)
                cursor = start
                covered = False
                for left, right in islice(intervals, position, None):
                    if right < cursor:
                        continue
                    if left > cursor:
                        break
                    if right >= end:
                        covered = True
                        break
                    cursor = right + timedelta(microseconds=1)
                if not covered:
                    _fail(candidate.root, new.provider_id, f"reuse_coverage:{product}/{year}")
    snapshots: dict[str, list[RetrievalOutcome]] = defaultdict(list)
    for outcome in new.outcomes:
        if outcome.status is OutcomeStatus.SUCCESS and outcome.coverage == "observations":
            signature = outcome.model_dump_json(exclude={"outcome_id", "observation_keys"})
            snapshots[signature].append(outcome)
    for outcome in old.outcomes:
        if (
            outcome.coverage != "observations"
            or outcome.status is not OutcomeStatus.SUCCESS
            or outcome.series_id is None
        ):
            continue
        product = old_definitions[outcome.series_id].product_id
        retained_years = years.get(product, set())
        relevant_keys = [key for key in outcome.observation_keys if key[1].year in retained_years]
        if not relevant_keys:
            continue
        signature = outcome.model_dump_json(exclude={"outcome_id", "observation_keys"})
        for retained in snapshots.get(signature, ()):
            retained_keys = set(retained.observation_keys)
            projection = tuple(key for key in outcome.observation_keys if key in retained_keys)
            if retained == retained_snapshot_outcome(outcome, projection) and set(relevant_keys) <= retained_keys:
                break
        else:
            _fail(candidate.root, new.provider_id, f"reuse_observations:{outcome.series_id}")


def seal_store(
    root: StoreRoot,
    provider_id: ProviderId,
    *,
    previous: SealedStore | None = None,
    reused: Mapping[PartitionIdentifier, ReusedPartition] | None = None,
) -> SealedStore:
    """Validate candidate contents and bind a closed file inventory to a generation.

    Without reuse, all observation semantics and bytes are checked. Reuse requires
    verified unchanged hardlinks and retained metadata support; only new or changed
    partitions are decoded and hashed. This must run under the writer lease.
    """
    reused = reused or {}
    try:
        if not stat.S_ISDIR(Path(root).lstat().st_mode):
            _fail(root, provider_id, "root")
        for path in Path(root).rglob("*"):
            mode = path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                _fail(root, provider_id, f"unsafe:{path.relative_to(root)}")
    except OSError as error:
        _fail(root, provider_id, f"inventory_io:{error}")
    candidate = _validate_store_contents(root, provider_id, frozenset())
    expected = {"manifest.json", *(path.relative_to(root).as_posix() for path in candidate.partition_files.values())}
    _closed_files(root, provider_id, expected | ({SEAL_NAME} if (Path(root) / SEAL_NAME).exists() else set()))
    if reused:
        if previous is None or not set(reused).issubset(candidate.partition_files):
            _fail(root, provider_id, "reuse_prior")
        for identifier, item in reused.items():
            if item.generation_id != previous.generation_id or item.identifier != identifier:
                _fail(root, provider_id, "reuse_generation")
            path = candidate.partition_files[identifier]
            if item.destination != path or _witness(path) != item.identity.witness:
                _fail(root, provider_id, "reuse_identity")
            name = previous.store.partition_files[identifier].relative_to(previous.store.root).as_posix()
            if (item.identity.sha256, item.identity.witness[:-1]) != (
                previous.files[name].sha256,
                previous.files[name].witness[:-1],
            ) or candidate.manifest.partition_row_counts[identifier] != previous.store.manifest.partition_row_counts[
                identifier
            ]:
                _fail(root, provider_id, "reuse_record")
        _preserves_support(previous.store, candidate, set(reused))
    candidate = _validate_store_contents(root, provider_id, frozenset(set(candidate.partition_files) - set(reused)))
    inherited = {
        candidate.partition_files[key].relative_to(root).as_posix(): value.identity for key, value in reused.items()
    }
    files: dict[str, FileIdentity] = {}
    for name in sorted(expected):
        if name in inherited:
            identity = inherited[name]
            _check_identity(root, provider_id, name, identity)
        else:
            path = Path(root) / name
            before = _witness(path)
            digest = _digest(path)
            if before != _witness(path):
                _fail(root, provider_id, f"changed_during_seal:{name}")
            identity = FileIdentity(digest, *before)
        files[name] = identity
    return _write_seal(candidate, files, _supporting_outcomes(_read_raw_manifest(root, provider_id)))


def _generation_id(provider: str, files: Mapping[str, Mapping[str, object]]) -> str:
    contents = {name: {"sha256": item["sha256"], "size": item["size"]} for name, item in files.items()}
    return hashlib.sha256(_canonical({"version": 1, "provider_id": provider, "files": contents})).hexdigest()


def _write_seal(
    store: ValidatedStore,
    files: Mapping[str, FileIdentity],
    supporting_outcomes: tuple[RetrievalOutcome, ...] = (),
) -> SealedStore:
    records = {name: _record(item) for name, item in files.items()}
    generation = _generation_id(str(store.manifest.provider_id), records)
    payload = {
        "version": 1,
        "provider_id": str(store.manifest.provider_id),
        "files": records,
        "generation_id": generation,
    }
    payload["seal_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    # The reserved temporary file belongs to this seal transition. Interruption
    # leaves recognizable unfinished metadata rather than truncating the seal.
    temporary = Path(store.root) / ".integrity.pending"
    with temporary.open("xb") as stream:
        stream.write(_canonical(payload))
    os.replace(temporary, Path(store.root) / SEAL_NAME)
    return SealedStore(store, generation, files, supporting_outcomes)


def refresh_witnesses(sealed: SealedStore, root: StoreRoot | None = None) -> SealedStore:
    """Advance ctime only after this writer's own hardlink creation or deletion.

    The caller must hold the exclusive lease and supply the snapshot captured
    before its owned operation. This is not a generic repair operation. No hash,
    inode, size or mtime is replaced. Unexplained drift must pass a complete
    audit against the original digests before this operation is used.
    """
    root = root if root is not None else sealed.store.root
    provider = sealed.store.manifest.provider_id
    files: dict[str, FileIdentity] = {}
    _closed_files(root, provider, {*sealed.files, SEAL_NAME})
    for name, identity in sealed.files.items():
        now = _witness(Path(root) / name)
        if now[:-1] != identity.witness[:-1]:
            _fail(root, provider, f"transition_identity:{name}")
        files[name] = FileIdentity(identity.sha256, *now)
    store = ValidatedStore(
        root,
        sealed.store.manifest,
        {key: Path(root) / path.relative_to(sealed.store.root) for key, path in sealed.store.partition_files.items()},
    )
    return _write_seal(store, files, sealed.supporting_outcomes)


def audit_store(root: StoreRoot, provider_id: ProviderId, *, allow_pending: bool = False) -> CacheAuditResult:
    """Verify every sealed byte and every store semantic rule, without network access.

    Recovery may pass ``allow_pending=True`` under its exclusive lease to check
    the committed seal before removing an identified incomplete seal replacement.
    This operation never removes or adopts the pending file.
    """
    sealed = _inspect_integrity(root, provider_id, allow_ctime_drift=True, allow_pending=allow_pending)
    observed = {name: _witness(Path(root) / name) for name in sealed.files}
    for name, identity in sealed.files.items():
        if _digest(Path(root) / name) != identity.sha256 or _witness(Path(root) / name) != observed[name]:
            _fail(root, provider_id, f"digest:{name}")
    checked = validate_store(root, provider_id)
    after = _inspect_integrity(root, provider_id, allow_ctime_drift=True, allow_pending=allow_pending)
    if after.generation_id != sealed.generation_id or any(
        _witness(Path(root) / name) != witness for name, witness in observed.items()
    ):
        _fail(root, provider_id, "generation_changed")
    return CacheAuditResult(
        provider_id,
        Path(root),
        sealed.generation_id,
        datetime.now(UTC),
        len(checked.partition_files),
        sum(checked.manifest.partition_row_counts.values()),
        sum(item.size for item in sealed.files.values()),
    )
