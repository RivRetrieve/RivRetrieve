"""Bounded extraction of verified evidence archives into a new private directory."""

from __future__ import annotations

import gzip
import io
import lzma
import stat
import struct
import tarfile
import unicodedata
import zipfile
import zlib
from pathlib import Path
from typing import IO, Self

from .index import Asset, EvidenceError


def _path(name: str, directory: bool) -> tuple[str, ...]:
    if directory and name.endswith("/"):
        name = name[:-1]
    parts = name.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((".", " "))
        or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)
        or part.split(".")[0].upper() in reserved
        for part in parts
    ):
        raise EvidenceError("Archive contains an unsafe path; request a reviewed replacement collection.")
    return tuple(parts)


class ArchivePaths:
    """Track explicit entries and portable aliases across every selected asset."""

    def __init__(self) -> None:
        self.entries: set[tuple[str, ...]] = set()
        self.spelling: dict[tuple[str, ...], tuple[str, ...]] = {}

    def admit(self, name: str, directory: bool) -> tuple[str, ...]:
        parts = _path(name, directory)
        key = tuple(unicodedata.normalize("NFC", part).casefold() for part in parts)
        if key in self.entries:
            raise EvidenceError("Archive contains duplicate paths; request a reviewed replacement collection.")
        for length in range(1, len(parts) + 1):
            prefix, original = key[:length], parts[:length]
            if prefix in self.spelling and self.spelling[prefix] != original:
                raise EvidenceError("Archive contains aliased paths; request a reviewed replacement collection.")
            self.spelling[prefix] = original
        self.entries.add(key)
        return parts


def _copy(source: IO[bytes], target: Path, expected: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with target.open("xb") as output:
        target.chmod(0o600)
        remaining = expected
        while remaining:
            block = source.read(min(1024 * 1024, remaining))
            if not block:
                raise EvidenceError("Archive member is truncated; obtain the pinned asset again.")
            output.write(block)
            remaining -= len(block)
        if source.read(1):
            raise EvidenceError("Archive member exceeds its declared size; reject this collection.")


def _tar_headers(member_count: int) -> type[tarfile.TarInfo]:
    class BoundedTarInfo(tarfile.TarInfo):
        headers = 0

        @classmethod
        def frombuf(cls, buf: bytes | bytearray, encoding: str, errors: str) -> Self:
            info = super().frombuf(buf, encoding, errors)
            cls.headers += 1
            if cls.headers > 3 * member_count + 1:
                raise EvidenceError("Archive exceeds reviewed header limits; reject this collection.")
            if info.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
                if info.size > 65536:
                    raise EvidenceError("Archive extension metadata exceeds safety limits; reject this collection.")
            elif not (info.isfile() or info.isdir()) or info.issparse():
                raise EvidenceError("Archive contains a link or special entry; reject this collection.")
            return info

    return BoundedTarInfo


class _TarBytes(io.RawIOBase):
    def __init__(self, source: gzip.GzipFile | lzma.LZMAFile, limit: int) -> None:
        self.source = source
        self.remaining = limit

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise EvidenceError("Unbounded archive read refused; reject this collection.")
        block = self.source.read(min(size, self.remaining + 1))
        self.remaining -= len(block)
        if self.remaining < 0:
            raise EvidenceError("Archive exceeds reviewed decompression limits; reject this collection.")
        return block


def _check_zip_directory(archive: Path, asset: Asset) -> None:
    # Read the bounded end record before ZipFile allocates the central directory.
    with archive.open("rb") as source:
        source.seek(max(0, asset.byte_size - 65557))
        tail = source.read(65557)
    start = tail.rfind(b"PK\x05\x06")
    if start < 0 or len(tail) - start < 22:
        raise EvidenceError("ZIP end record is invalid; reject this collection.")
    _, disk, directory_disk, disk_entries, entries, size, offset, comment = struct.unpack(
        "<4s4H2LH", tail[start : start + 22]
    )
    end_offset = asset.byte_size - (len(tail) - start)
    with archive.open("rb") as source:
        source.seek(max(0, end_offset - 20))
        locator = source.read(20)
    if (
        locator.startswith(b"PK\x06\x07")
        or disk != 0
        or directory_disk != 0
        or disk_entries != entries
        or entries != asset.member_count
        or entries == 65535
        or size > min(8 * 1024 * 1024, asset.member_count * 65536)
        or size == 0xFFFFFFFF
        or offset == 0xFFFFFFFF
        or offset + size > asset.byte_size - (len(tail) - start)
        or len(tail) - start != 22 + comment
    ):
        raise EvidenceError("ZIP directory exceeds reviewed limits or uses unsupported ZIP64/volume metadata.")


def extract_archive(archive: Path, asset: Asset, destination: Path, paths: ArchivePaths) -> None:
    """Extract regular files only, bounded by the index's exact byte and entry totals.

    The caller must verify compressed size and SHA-256 first and provide a new,
    private staging directory. File modes and ownership from archives are ignored.
    """
    count = 0
    expanded = 0

    def admit(name: str, directory: bool, size: int) -> Path:
        nonlocal count, expanded
        count += 1
        expanded += size
        if size < 0 or count > asset.member_count or expanded > asset.extracted_byte_size:
            raise EvidenceError("Archive exceeds reviewed extraction limits; reject this collection.")
        return destination.joinpath(*paths.admit(name, directory))

    try:
        if asset.archive_format == "zip":
            _check_zip_directory(archive, asset)
            with zipfile.ZipFile(archive) as bundle:
                if len(bundle.infolist()) != asset.member_count:
                    raise EvidenceError("ZIP directory count differs from reviewed limits; reject this collection.")
                for member in bundle.infolist():
                    directory = member.is_dir()
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    if (
                        (directory and kind not in (0, stat.S_IFDIR))
                        or (not directory and kind not in (0, stat.S_IFREG))
                        or member.flag_bits & 1
                        or "\x00" in member.orig_filename
                    ):
                        raise EvidenceError(
                            "Archive contains a link, special or encrypted entry; reject this collection."
                        )
                    if directory and member.file_size:
                        raise EvidenceError("Archive directory contains data; reject this collection.")
                    target = admit(member.filename, directory, member.file_size)
                    if directory:
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    else:
                        with bundle.open(member) as source:
                            _copy(source, target, member.file_size)
        else:
            opener = gzip.open if asset.archive_format == "tar.gz" else lzma.open
            # Include bounded extension records, header/file padding and end padding.
            limit = asset.extracted_byte_size + asset.member_count * (65536 + 2048) + 10240
            with (
                opener(archive, "rb") as compressed,
                tarfile.open(
                    fileobj=_TarBytes(compressed, limit), mode="r|", tarinfo=_tar_headers(asset.member_count)
                ) as bundle,
            ):
                for member in bundle:
                    if not (member.isfile() or member.isdir()) or member.issparse():
                        raise EvidenceError("Archive contains a link or special entry; reject this collection.")
                    if member.isdir() and member.size:
                        raise EvidenceError("Archive directory contains data; reject this collection.")
                    target = admit(member.name, member.isdir(), member.size)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    else:
                        source = bundle.extractfile(member)
                        if source is None:
                            raise EvidenceError("Archive has no regular-file content; reject this collection.")
                        with source:
                            _copy(source, target, member.size)
        if count != asset.member_count or expanded != asset.extracted_byte_size:
            raise EvidenceError("Archive differs from reviewed extraction totals; reject this collection.")
    except (
        OSError,
        tarfile.TarError,
        zipfile.BadZipFile,
        lzma.LZMAError,
        zlib.error,
        EOFError,
        RuntimeError,
        ValueError,
    ) as error:
        if isinstance(error, EvidenceError):
            raise
        raise EvidenceError("Archive could not be safely extracted; check the reviewed collection.") from error
