"""record_observations : ProviderId × stations × products × RequestedWindow × HttpClient → RecordingEnvelope files   (composition root).

Maintainer entry point that drives one live provider exactly as a public fetch would, with the
engine's own padding, window planning and stop convention, and writes every source exchange the
adapter issued as a v2 recording. It performs network access and file writes; nothing else does.

Usage::

    uv run python -m rivretrieve._internal.record_observations --provider za_dws --station X3H001 \\
        --product discharge_instantaneous --product stage_instantaneous \\
        --start 2020-01-05 --end 2020-01-06 --out-dir tests/test_data --name za_dws_X3H001_Point_2020-01-03_2020-01-09

One captured exchange is written as ``<name>.recording.json``; several are written as
``<name>_p1.recording.json``, ``<name>_p2.recording.json`` and so on, in send order.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest as EngineObservationRequest
from rivretrieve._internal.engine import RequestedWindow
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.observations import ObservationRequest as PublicObservationRequest
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.recordings import RecordingEnvelope, RecordingTransport, write_recording
from rivretrieve._internal.transport import HttpClient


def record_observations(
    provider_id: str,
    stations: Sequence[str],
    products: Sequence[str],
    start: str,
    end: str,
    out_dir: Path,
    name: str,
) -> tuple[Path, ...]:
    """Drive one live provider through a recording transport and write what it exchanged."""
    (declared,) = load_manifest((provider_id,))
    observations = declared.declaration.observations
    if not isinstance(observations, LiveStages):
        raise FatalContractError(f"Provider {provider_id} is not a LiveStages provider; nothing to record")
    public_request = PublicObservationRequest.from_inputs(
        provider_id=provider_id,
        stations=tuple(stations),
        products=tuple(products),
        start=start,
        end=end,
    )
    request = EngineObservationRequest(
        provider_id=public_request.provider_id,
        stations=public_request.stations,
        products=tuple(ProductId(product) for product in public_request.products),
        window=RequestedWindow(start=public_request.start, end=public_request.end),
    )
    transport = RecordingTransport(HttpClient())
    try:
        drive(
            request,
            observations.stages,
            provenance=ObservationProvenance(source="live", provider_id=public_request.provider_id),
            transport=transport,
        )
    finally:
        written = _write(transport.recordings, out_dir, name)
    return written


def _write(recordings: tuple[RecordingEnvelope, ...], out_dir: Path, name: str) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, recording in enumerate(recordings, start=1):
        suffix = "" if len(recordings) == 1 else f"_p{index}"
        path = out_dir / f"{name}{suffix}.recording.json"
        write_recording(recording, path)
        paths.append(path)
        print(
            f"{path}: HTTP {recording.status_code} {recording.content_type} at {recording.retrieved_at.isoformat()} "
            f"for {recording.request.describe()}"
        )
    if not recordings:
        print("no source exchange was issued; nothing written")
    return tuple(paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="record-observations",
        description="Record the exact source exchanges one live provider issues for a requested window.",
    )
    parser.add_argument("--provider", required=True, help="Built-in provider id, e.g. za_dws.")
    parser.add_argument("--station", action="append", required=True, help="Station id; repeatable.")
    parser.add_argument("--product", action="append", required=True, help="Product id; repeatable.")
    parser.add_argument("--start", required=True, help="Requested wall-clock start, e.g. 2020-01-05.")
    parser.add_argument("--end", required=True, help="Requested wall-clock end; a bare date means the whole day.")
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory receiving the recording files.")
    parser.add_argument("--name", required=True, help="File stem, e.g. za_dws_X3H001_Point_2020-01-03_2020-01-09.")
    arguments = parser.parse_args(argv)
    record_observations(
        arguments.provider,
        arguments.station,
        arguments.product,
        arguments.start,
        arguments.end,
        arguments.out_dir,
        arguments.name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
