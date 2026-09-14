# Historical research utility; not project policy or a certification/publication gate.
# Full governing evidence is retained privately; do not run stripping on that corpus.
"""Pack working receipts and staged bodies into the committed evidence bundles.

    pack : (WorkingReceipts, StagedBodies, PriorBundle?) -> Bundle   (deterministic)

Each bundle is one tar.xz holding `receipts.csv` - every request attempt, successful or not - and
`bodies/<request_id>.body` for every attempt whose body carries no observation value. Bodies come from
the staging zip written by the acquisition script and, when the bundle already exists, from the
bundle itself, so a retry run adds to the evidence rather than replacing it.

Refuses to pack when a receipt marked `body_retained=True` has no body, when a body's SHA-256 or size
disagrees with its receipt, when a body has no receipt, or when any body carries an observation value.
On success the working receipt table is removed; the acquisition scripts re-seed it from the bundle.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/pack_evidence.py <hubeau_staging.zip> <hydroportail_staging.zip>
Output: evidence/hubeau_counts.tar.xz, evidence/hydroportail_history.tar.xz
"""

from __future__ import annotations

import csv
import hashlib
import io
import pathlib
import sys
import tarfile
import zipfile
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evidence_bundle import BODY_PREFIX, BODY_SUFFIX, RECEIPTS_MEMBER, bodies  # noqa: E402
from observation_scan import body_carries_observations  # noqa: E402

EVIDENCE = pathlib.Path(__file__).resolve().parents[1] / "evidence"
DATASETS = (
    ("hubeau_count_receipts.csv", "hubeau_counts.tar.xz"),
    ("hydroportail_history_receipts.csv", "hydroportail_history.tar.xz"),
)


def _member(name: str, payload: bytes, mtime: float) -> tuple[tarfile.TarInfo, io.BytesIO]:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode, info.uid, info.gid = len(payload), int(mtime), 0o644, 0, 0
    return info, io.BytesIO(payload)


def pack(working: pathlib.Path, bundle: pathlib.Path, staging: pathlib.Path) -> None:
    rows = list(csv.DictReader(working.open(newline="", encoding="utf-8")))
    available = bodies(bundle) if bundle.exists() else {}
    if staging.exists():
        with zipfile.ZipFile(staging) as staged:
            for name in staged.namelist():
                available[name.removesuffix(BODY_SUFFIX)] = staged.read(name)
    by_id = {row["request_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise SystemExit(f"{working.name}: duplicate request ids")
    orphans = sorted(set(available) - set(by_id))
    if orphans:
        raise SystemExit(f"{bundle.name}: bodies without a receipt: {orphans[:5]}")
    members: list[tuple[tarfile.TarInfo, io.BytesIO]] = []
    for row in sorted(rows, key=lambda r: r["request_id"]):
        if row["body_retained"] != "True":
            continue
        raw = available.get(row["request_id"])
        if raw is None:
            raise SystemExit(f"{row['request_id']}: receipt says body retained, but no body was staged")
        if hashlib.sha256(raw).hexdigest() != row["response_sha256"] or str(len(raw)) != row["response_bytes"]:
            raise SystemExit(f"{row['request_id']}: staged body disagrees with its receipt")
        if body_carries_observations(raw):
            raise SystemExit(f"{row['request_id']}: staged body carries an observation value")
        instant = datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00")).timestamp()
        members.append(_member(f"{BODY_PREFIX}{row['request_id']}{BODY_SUFFIX}", raw, instant))
    table = io.StringIO()
    writer = csv.DictWriter(table, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    temporary = bundle.with_suffix(".tmp")
    with tarfile.open(temporary, "w:xz", preset=9) as archive:
        archive.addfile(*_member(RECEIPTS_MEMBER, table.getvalue().encode("utf-8"), 0))
        for info, payload in members:
            archive.addfile(info, payload)
    temporary.replace(bundle)
    working.unlink()
    print(f"{bundle.name}: {len(rows):,} receipts, {len(members):,} bodies, {bundle.stat().st_size:,} B")


def main(stagings: list[pathlib.Path]) -> None:
    for (working, bundle), staging in zip(DATASETS, stagings, strict=True):
        pack(EVIDENCE / working, EVIDENCE / bundle, staging)


if __name__ == "__main__":
    main([pathlib.Path(arg) for arg in sys.argv[1:3]])
