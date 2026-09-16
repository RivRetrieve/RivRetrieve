# Independent telemetric boundary expectations

## Independence and scope

Authored only from the specified source recording, official manual pages 11–12 text, official OpenAPI, AGENTS.md, CONTEXT.md and the full Brazil vision. No provider implementation, implementation output, legacy parser, test expectations or telemetry implementation worktree was read. No credentials, authentication response body or owner `.env` was read. The recording carries only withheld-authentication provenance metadata, not an authentication body.

Station: `15400000`. Closed native wall-clock request: `2024-01-01T23:30:00` through `2024-01-02T00:30:00`. `Data_Hora_Medicao` is the measurement timestamp, not `Data_Atualizacao`. No timezone is established by these evidence items. Preserve these naive times and represent the zone as `unknown`; do not infer UTC or a geographical zone.

## Independently authored literals

| Claimed product | Count | First native wall-clock timestamp | Last native wall-clock timestamp |
|---|---:|---|---|
| Adopted telemetric discharge (`Vazao_Adotada`) | **5** | **2024-01-01T23:30:00** | **2024-01-02T00:30:00** |
| Adopted telemetric stage (`Cota_Adotada`) | **5** | **2024-01-01T23:30:00** | **2024-01-02T00:30:00** |

These are literals established by enumerating the actual five source rows, not by assuming a 15-minute cadence. Product IDs are intentionally not chosen by this evidence author. No source row is removed on QC grounds.

## Visible source rows

`items` index is zero-based in the decoded original JSON body. All seven rows have station `15400000`, both adopted QC statuses equal to string `"0"`, and `Data_Atualizacao: null`. Value spellings below are copied from the recording, not the manual example.

| items index | Data_Hora_Medicao | Vazao_Adotada (m³/s) | Cota_Adotada (cm) | Canonical stage (m) | In closed window |
|---:|---|---:|---:|---:|---|
| 93 | 2024-01-01 23:15:00.0 | 13841.20 | 781.00 | 7.81 | no |
| 94 | 2024-01-01 23:30:00.0 | 13841.20 | 781.00 | 7.81 | yes |
| 95 | 2024-01-01 23:45:00.0 | 13841.20 | 781.00 | 7.81 | yes |
| 96 | 2024-01-02 00:00:00.0 | 13863.50 | 782.00 | 7.82 | yes |
| 97 | 2024-01-02 00:15:00.0 | 13885.80 | 783.00 | 7.83 | yes |
| 98 | 2024-01-02 00:30:00.0 | 13885.80 | 783.00 | 7.83 | yes |
| 99 | 2024-01-02 00:45:00.0 | 13885.80 | 783.00 | 7.83 | no |

## Evidence identity and integrity

Input at authorship: `.worktrees/brazil-live-evidence/telemetry_15400000_2024-01-04_DIAS_30.recording.json`. The unchanged recording is now retained beside this report.

- Computed recording-envelope file SHA256: `8a5ef970522616dc49b6b1817fa009f124edcd641d056de8a2e1ade61fdac604`.
- Strict Base64 decoding of `response.content_base64` succeeded.
- Computed body SHA256: `7cd09799a09f22f8d18cb5f34e6b08a1d74066a70ef9a16fc4bb1bcb27cdc691`.
- This equals both the supplied expected digest and `response.sha256` in the envelope. No external expected envelope digest was supplied; its computed identity is recorded, not independently authenticated.
- Envelope format version 2; HTTP 200; retrieved `2026-09-16T11:35:34.908979Z`.
- Body: `status: "OK"`, `code: 200`, `message: "Sucesso"`.
- GET `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1`.
- Recorded parameters: `Código da Estação: 15400000`, `Tipo Filtro Data: DATA_LEITURA`, `Data de Busca (yyyy-MM-dd): 2024-01-04`, `Range Intervalo de busca: DIAS_30`.

## Documentation basis

Official manual extraction `.worktrees/brazil-source-evidence/manual-pages11-12.txt`, PDF page 11 (printed page 9), explicitly labels:

- `Cota_Adotada`: `[Cota (cm)]`.
- `Vazao_Adotada`: `[Vazão (m3/s)]`.
- `Data_Hora_Medicao`: `[DataHora da medição/coleta do dado]`.
- `Data_Atualizacao`: `[DataHora da atualização do dado na base]`.
- QC fields: `0 = ok, 1 = suspeito, 2 = ruim`.

Discharge needs no unit scaling for canonical m³/s. Stage uses exact physical conversion cm / 100 = m. These are adopted telemetric measurements, not inferred daily means. The manual's illustrative discharge at 2024-01-01 23:15 is `13225.42`, whereas this recording publishes `13841.20`. The manual grounds units and field meaning only; it cannot replace the actual recorded values or establish why they differ.

Official `.worktrees/brazil-source-evidence/api-docs.json`, path `/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1`, GET summary states adopted rain, level and discharge and a period limited to 30 days per request. Its parameter enums include `DATA_LEITURA`, `DATA_ULTIMA_ATUALIZACAO` and `DIAS_30`. This supports the recorded request vocabulary. It does not establish a timezone or a general exact stop convention. This single recording cannot certify all endpoint boundary semantics, supported stations, coverage continuity or other products.

## Nulls, sentinels, duplicates and status

- Entire body: 2,876 rows, all station `15400000`; minimum measurement time `2023-12-06T00:00:00`, maximum `2024-01-04T23:45:00`. Original body order is not globally chronological. First/last expectations mean chronological bounds, not payload order.
- No repeated `(station, measurement timestamp)` keys in the entire body or selected window.
- Both adopted fields contain zero JSON nulls, zero blank strings and zero nonfinite numeric values in the entire body and selected window.
- Entire-body discharge numeric range: 9756.70–14177.20 m³/s; stage: 582.00–796.00 cm. All adopted discharge and stage QC statuses are `"0"` (2,876 of each; 5 of each in-window).
- No sentinel meaning is documented in the inspected manual text or endpoint declaration. The observed in-window values are positive finite numbers; this author does not assign undocumented sentinel meanings or invent replacement rules. This fixture does not prove behavior for published nulls, sentinels or nonzero QC.
- `Data_Atualizacao` is null in 384 body rows, including all five in-window rows. This does not erase valid measurement timestamps or adopted values.

## Reproduce

From repository root:

```sh
uv run python tests/recordings/br_ana/read_telemetry_source.py
```

The small independent standard-library script directly decodes source bytes, verifies the body digest against the envelope and supplied digest, enumerates rows in the closed native-time window, and reports source properties. It imports no project code. Saved execution output: `telemetry-source-audit.txt` in this directory. This report supplies source-grounded expectations, not a claim that a provider has passed them.

### Repository retention note

The implementation owner retained the independent author's script and original output
alongside this report. Only the script's input path was relocated to its sibling recording;
formatting/import order were normalized without changing audit logic or literals.
The retained script has no provider imports. Its output is checked against the original
`telemetry-source-audit.txt`. The original independence statement remains unchanged.
