"""record_observations : ProviderDeclaration × stations × products × RequestedWindow × CredentialSources × HttpClient → RecordingEnvelope files   (composition root).

Maintainer entry point that drives one live provider exactly as a public fetch would, with the
engine's own padding, window planning and stop convention, and writes every source exchange the
adapter issued as a v2 recording. It performs network access, file writes and credential reads;
nothing else does.

Usage::

    uv run python -m rivretrieve._internal.record_observations --provider za_dws --station X3H001 \\
        --product discharge_instantaneous --product stage_instantaneous \\
        --start 2020-01-05 --end 2020-01-06 --out-dir tests/test_data --name za_dws_X3H001_Point_2020-01-03_2020-01-09

Declared direct and exchanged credentials are resolved here from the environment or the explicit
``--env-file``. Credential exchange runs below the recorder, so token responses are never recorded.
The existing explicit direct-header options remain supported for maintainer use::

    uv run python -m rivretrieve._internal.record_observations --provider no_nve --station 1.200.0 \\
        --product stage_daily_mean --start 2025-07-10T00:00:00 --end 2025-07-12T00:00:00 \\
        --credential-header X-API-Key --credential-env NVE_API_KEY --credential-origin https://hydapi.nve.no \\
        --env-file .env --out-dir tests/test_data --name no_nve_1.200.0_1000_1440_2025-07-08_2025-07-14

``--env-file`` is consulted only when the environment does not already carry the variable.

One captured exchange is written as ``<name>.recording.json``; several are written as
``<name>_p1.recording.json``, ``<name>_p2.recording.json`` and so on, in send order.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from dotenv import dotenv_values

from rivretrieve._internal.authentication import CredentialExchangeTransport
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import ObservationRequest as EngineObservationRequest
from rivretrieve._internal.engine import RequestedWindow
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance
from rivretrieve._internal.observations import ObservationRequest as PublicObservationRequest
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.recordings import RecordingEnvelope, RecordingTransport, write_recording
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    Transport,
    _SystemClock,
)


def record_observations(
    provider_id: str,
    stations: Sequence[str],
    products: Sequence[str],
    start: str,
    end: str,
    out_dir: Path,
    name: str,
    credentials: tuple[CredentialHeader, ...] = (),
    transport: Transport | None = None,
) -> tuple[Path, ...]:
    """Drive one live provider through a recording transport and write what it exchanged.

    ``transport`` is the live transport to record through; it defaults to the engine ``HttpClient``.
    """
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
    client = HttpClient() if transport is None else transport
    recording_transport = RecordingTransport(AuthenticatedTransport(client, credentials) if credentials else client)
    try:
        drive(
            request,
            observations.stages,
            provenance=ObservationProvenance(source="live", provider_id=public_request.provider_id),
            transport=recording_transport,
        )
    finally:
        written = _write(recording_transport.recordings, out_dir, name)
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


def credential_value(variable: str, environment: Mapping[str, str], env_file: Path | None) -> str:
    """Resolve one credential value from the environment, then from an explicit dotenv file."""
    value: str | None
    if variable in environment:
        value = environment[variable]
    else:
        dotenv = dotenv_values(env_file) if env_file is not None and env_file.is_file() else {}
        file_value = dotenv.get(variable)
        value = file_value if isinstance(file_value, str) else None
    if value is not None and value.strip():
        return value
    location = "the environment" if env_file is None else f"the environment or {env_file}"
    raise FatalContractError(f"credential variable {variable} is not set in {location}")


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
    parser.add_argument("--credential-header", help="Credential header name the source requires, e.g. X-API-Key.")
    parser.add_argument("--credential-env", help="Environment variable holding the credential value.")
    parser.add_argument("--credential-origin", help="Exact origin the credential is scoped to, e.g. https://host.")
    parser.add_argument("--env-file", type=Path, help="Dotenv-style file consulted when the variable is not set.")
    arguments = parser.parse_args(argv)
    credential_options = (arguments.credential_header, arguments.credential_env, arguments.credential_origin)
    if any(option is not None for option in credential_options) and not all(credential_options):
        parser.error("--credential-header, --credential-env and --credential-origin must be given together")
    (declared,) = load_manifest((arguments.provider,))
    declaration = declared.declaration
    if not isinstance(declaration.observations, LiveStages):
        raise FatalContractError(f"Provider {arguments.provider} is not a LiveStages provider; nothing to record")
    exchange = declaration.credential_exchange
    if exchange is not None and any(credential_options):
        parser.error("declared credential exchange cannot be overridden by direct credential options")
    credentials: tuple[CredentialHeader, ...] = ()
    transport: Transport | None = None
    if all(credential_options):
        value = credential_value(arguments.credential_env, os.environ, arguments.env_file)
        credentials = (CredentialHeader(arguments.credential_header, value, (arguments.credential_origin,)),)
    else:
        bindings = declaration.credential_headers if exchange is None else exchange.credential_headers
        credentials = tuple(
            CredentialHeader(
                binding.header, credential_value(binding.variable, os.environ, arguments.env_file), binding.origins
            )
            for binding in bindings
        )
        if exchange is not None:
            transport = CredentialExchangeTransport(HttpClient(), credentials, exchange.spec, _SystemClock())
            credentials = ()
    record_observations(
        arguments.provider,
        arguments.station,
        arguments.product,
        arguments.start,
        arguments.end,
        arguments.out_dir,
        arguments.name,
        credentials,
        transport=transport,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
