"""Read one committed evidence bundle: its receipt table and its observation-free response bodies.

    receipts : Bundle -> [Receipt]              (pure read)
    bodies   : Bundle -> {request_id: bytes}    (pure read)

A bundle is a tar.xz holding `receipts.csv` (one row per request attempt) and `bodies/<request_id>.body`
for every attempt whose body carries no observation value.
"""

from __future__ import annotations

import csv
import io
import pathlib
import tarfile

RECEIPTS_MEMBER = "receipts.csv"
BODY_PREFIX = "bodies/"
BODY_SUFFIX = ".body"


def receipts(bundle: pathlib.Path) -> list[dict[str, str]]:
    with tarfile.open(bundle, "r:xz") as archive:
        handle = archive.extractfile(RECEIPTS_MEMBER)
        if handle is None:
            raise FileNotFoundError(f"{bundle.name} has no {RECEIPTS_MEMBER}")
        return list(csv.DictReader(io.StringIO(handle.read().decode("utf-8"))))


def bodies(bundle: pathlib.Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tarfile.open(bundle, "r:xz") as archive:
        for member in archive:
            if member.name.startswith(BODY_PREFIX):
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError(f"{bundle.name}!{member.name} is not a regular file")
                out[member.name[len(BODY_PREFIX) : -len(BODY_SUFFIX)]] = handle.read()
    return out
