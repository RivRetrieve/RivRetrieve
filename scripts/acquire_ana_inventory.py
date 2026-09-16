"""ANA inventory acquisition : InventoryRequests × CredentialExchangeTransport → Recordings × AttemptOutcomes.

This composition root is maintainer-only. No credential or exchange response is written.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rivretrieve._internal.authentication import CredentialExchangeError, CredentialExchangeTransport, ExchangeSpec
from rivretrieve._internal.providers.br_ana.inventory import BRAZILIAN_UNITS, INVENTORY_URL
from rivretrieve._internal.record_observations import credential_value
from rivretrieve._internal.recordings import RecordingTransport, write_recording
from rivretrieve._internal.transport import (
    CredentialHeader,
    HttpClient,
    HttpMethod,
    TransportFailure,
    TransportRequest,
    _SystemClock,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture ANA inventory through the shared credential exchange.")
    parser.add_argument(
        "--out", type=Path, required=True, help="New recording directory; existing files are never overwritten"
    )
    parser.add_argument("--env-file", type=Path, default=Path.cwd() / ".env")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    spec = ExchangeSpec.ana()
    headers = tuple(
        CredentialHeader(header, credential_value(variable, os.environ, args.env_file), (spec.allowed_data_origin,))
        for header, variable in (("Identificador", "ANA_IDENTIFICADOR"), ("Senha", "ANA_SENHA"))
    )
    recorder = RecordingTransport(CredentialExchangeTransport(HttpClient(), headers, spec, _SystemClock()))
    requests: list[tuple[str, dict[str, str | int]]] = [
        (f"inventory_UF_{uf}", {"Unidade Federativa": uf}) for uf in BRAZILIAN_UNITS
    ]
    requests.extend((f"population_inventory_basin{basin}", {"Código da Bacia": basin}) for basin in range(1, 10))
    outcomes: list[dict[str, object]] = []
    # Sole isolation point for independent population requests. Contract failures remain fatal.
    for name, parameters in requests:
        outcome: dict[str, object] = {"name": name}
        try:
            response = recorder.send(TransportRequest(HttpMethod.GET, INVENTORY_URL, params=parameters))
        except CredentialExchangeError as error:
            outcome.update(failure=error.reason.value, http_status=error.status_code)
        except TransportFailure:
            outcome.update(failure="transport_failure")
        else:
            recording = recorder.recordings[-1]
            write_recording(recording, args.out / f"{name}.recording.json")
            outcome.update(http_status=response.status_code, sha256=recording.sha256, bytes=len(response.content))
        outcomes.append(outcome)
        (args.out / "attempts.json").write_text(json.dumps(outcomes, indent=2) + "\n")
        print(json.dumps(outcome), flush=True)


if __name__ == "__main__":
    main()
