"""Official ANA manual PDF → source acquisition identity × explicitly derived safe page11 text."""

import hashlib
import io
import json
import sys
from importlib.metadata import version
from pathlib import Path

from pypdf import PdfReader

from rivretrieve._internal.recordings import _payload_has_secret_field
from rivretrieve._internal.transport import HttpClient, HttpMethod, RedirectPolicy, TransportRequest

URL = "https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf"


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    response = HttpClient().send(TransportRequest(HttpMethod.GET, URL, redirect_policy=RedirectPolicy.REFUSE))
    if response.status_code != 200:
        print(json.dumps({"failure": "manual_http_status", "status_code": response.status_code}))
        return 1
    if not response.content.startswith(b"%PDF-"):
        print("manual acquisition failed: content is not PDF")
        return 1
    original_digest = hashlib.sha256(response.content).hexdigest()
    document = PdfReader(io.BytesIO(response.content))
    text = document.pages[10].extract_text(extraction_mode="plain")
    required = ("Cota_Adotada", "Vazao_Adotada", "Data_Hora_Medicao", "Cota (cm)", "Vazão (m3/s)")
    if not all(item in text for item in required):
        print("manual extraction refused: required unit/time evidence absent")
        return 1
    forbidden = ("tokenautenticacao", "identificador", "senha", "bearer ", "oauth", "authorization")
    if any(item in text.casefold() for item in forbidden) or _payload_has_secret_field(text, content_type="text/plain"):
        print("manual extraction refused: secret-bearing terminology")
        return 1
    derived = text.encode("utf-8")
    metadata = {
        "publisher_material": {
            "method": "GET",
            "requested_url": URL,
            "transport_response_url": response.url,
            "redirect_policy": "refuse",
            "status_code": response.status_code,
            "retrieved_at": response.retrieved_at.isoformat(),
            "content_type": response.content_type,
            "sha256": original_digest,
            "bytes": len(response.content),
            "retention": "Full publisher PDF not retained: authentication tutorial deliberately excluded; original bytes existed only in process memory.",
            "ordinary_request_headers": dict(response.executed_request.ordinary_headers)
            if response.executed_request
            else None,
            "credential_header_names": list(response.applied_credential_header_names),
        },
        "derived_excerpt": {
            "path": "manual-page11-derived.txt",
            "authorship": "derived text extraction, NOT original publisher response bytes",
            "sha256": hashlib.sha256(derived).hexdigest(),
            "bytes": len(derived),
            "transformation": {
                "implementation": "pypdf.PdfReader(io.BytesIO(response.content)).pages[10].extract_text(extraction_mode=plain).encode(utf-8)",
                "pypdf_version": version("pypdf"),
                "pdf_page_1_based": 11,
                "printed_page_label": "9",
                "text_encoding": "UTF-8",
                "post_extraction_modifications": "none",
            },
        },
        "qualification": "retrieved_at is HttpClient transport acquisition time for the original PDF, not extraction time; excerpt hash identifies derived bytes separately. Full PDF not retained, so the excerpt is not a replayable recording of the original HTTP response.",
    }
    (output / "manual-page11-derived.txt").write_bytes(derived)
    (output / "manual-page11-acquisition.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        print("manual acquisition failed; exception suppressed")
        code = 1
    sys.exit(code)
