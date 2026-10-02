"""source_audit : ANARecordingBytes -> BoundarySourceRows (no provider imports)."""

import argparse
import base64
import hashlib
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("recording", type=Path, help="External retained telemetry recording")
SOURCE = parser.parse_args().recording
DIGEST = "7cd09799a09f22f8d18cb5f34e6b08a1d74066a70ef9a16fc4bb1bcb27cdc691"
envelope_bytes = SOURCE.read_bytes()
envelope = json.loads(envelope_bytes)
body = base64.b64decode(envelope["response"]["content_base64"], validate=True)
assert hashlib.sha256(body).hexdigest() == envelope["response"]["sha256"] == DIGEST
assert envelope["request"]["parameters"] == {
    "Código da Estação": 15400000,
    "Tipo Filtro Data": "DATA_LEITURA",
    "Data de Busca (yyyy-MM-dd)": "2024-01-04",
    "Range Intervalo de busca": "DIAS_30",
}
data = json.loads(body)
print("Envelope SHA256:", hashlib.sha256(envelope_bytes).hexdigest())
print("Body SHA256:", DIGEST)
print("HTTP:", envelope["response"]["status_code"], "retrieved:", envelope["response"]["retrieved_at"])
print("Body status:", {k: v for k, v in data.items() if k != "items"})
rows = data["items"]
start = datetime.fromisoformat("2024-01-01T23:30:00")
stop = datetime.fromisoformat("2024-01-02T00:30:00")
indexed = [(i, r, datetime.fromisoformat(r["Data_Hora_Medicao"])) for i, r in enumerate(rows)]
selected = [(i, r, t) for i, r, t in indexed if start <= t <= stop]
nearby = sorted(
    [(i, r, t) for i, r, t in indexed if datetime(2024, 1, 1, 23, 15) <= t <= datetime(2024, 1, 2, 0, 45)],
    key=lambda item: item[2],
)
print("Stations:", dict(Counter(r["codigoestacao"] for r in rows)))
print("Rows:", len(rows), "min:", min(t for _, _, t in indexed), "max:", max(t for _, _, t in indexed))
print("Source timestamp order ascending:", all(indexed[i][2] <= indexed[i + 1][2] for i in range(len(indexed) - 1)))
print("SOURCE TABLE (zero-based items index):")
for i, r, t in nearby:
    print(
        i,
        r["Data_Hora_Medicao"],
        r["Vazao_Adotada"],
        r["Cota_Adotada"],
        r["Vazao_Adotada_Status"],
        r["Cota_Adotada_Status"],
        "update=" + str(r["Data_Atualizacao"]),
        "in_window=" + str(start <= t <= stop),
        "stage_m=" + str(Decimal(r["Cota_Adotada"]) / 100),
    )
for name, subset in [("entire body", indexed), ("requested window", selected)]:
    print("AUDIT", name)
    keys = Counter((r["codigoestacao"], t) for _, r, t in subset)
    print("duplicate station/timestamp keys:", {str(k): v for k, v in keys.items() if v > 1})
    for field in ["Vazao_Adotada", "Cota_Adotada"]:
        values = [r[field] for _, r, _ in subset]
        nulls = sum(v is None for v in values)
        blanks = sum(isinstance(v, str) and not v.strip() for v in values)
        numeric = [Decimal(v) for v in values if v is not None and str(v).strip()]
        print(
            field,
            "nulls",
            nulls,
            "blanks",
            blanks,
            "min",
            min(numeric),
            "max",
            max(numeric),
            "nonfinite",
            sum(not n.is_finite() for n in numeric),
            "statuses",
            dict(Counter(r[field + "_Status"] for _, r, _ in subset)),
        )
    print("null update times:", sum(r["Data_Atualizacao"] is None for _, r, _ in subset))
print(
    "BOUNDARY count:", len(selected), "first:", min(t for _, _, t in selected), "last:", max(t for _, _, t in selected)
)
