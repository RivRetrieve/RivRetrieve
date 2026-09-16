# ANA daily cross-endpoint research (2026-09-16)

Research only. No production code or port output was read. No boundary expectation literals were authored. No checkout, credential read, exchange, environment copy or production edit was performed. All commands used `uv run` from the project root. Five bounded one-station/month SOAP observation requests were sent through `RecordingTransport(HttpClient())` to the public official SOAP origin; no ANA credentials were forwarded to that different origin. Each `.recording.json` retains the exact safe request, original response bytes, retrieval instant, and payload SHA-256.

## Official source partition documentation

https://telemetriaws1.ana.gov.br/ServiceANA.asmx?op=HidroSerieHistorica

Original `soap-operation.html`, SHA-256 `ff0daebe58630a50916bb181dc7afed25b7c1243d1a56b83f8a4846d699ff229`, retrieved 2026-09-16T13:01:02.586415+00:00. Exact words:

- “Série Histórica estação - HIDRO.”
- “codEstacao: Código Plu ou Flu”
- “dataFim: Caso não preenchido, trará até o último dado mais recente armazenado”
- “tipoDados: 1-Cotas, 2-Chuvas ou 3-Vazões”
- “nivelConsistencia: 1-Bruto ou 2-Consistido”

The page documents HTTP GET and POST plus SOAP 1.1/1.2, with all five parameters. WSDL retained at `soap-wsdl.xml` from https://telemetriaws1.ana.gov.br/ServiceANA.asmx?WSDL (identity in public-jobs.json.identities.json). Thus explicit named source-level filters exist in an official ANA historical-series interface. This is not a precedence rule and does not establish an undocumented filter on the newer API.

## Actual pairs establish correspondence, not global interchangeability

All original modern recordings referenced here remain in `../brazil-live-evidence/`. Modern endpoint row fields are compared to original SOAP fields in `paired-{stage,discharge}-{2020,2024}-comparison.json`. `compare_pairs.py` reproduces these **derived comparisons**, not recordings. It joins station, consistency, wall-clock monthly header and MediaDiaria; parses numeric text to Decimal; parses dates without applying a timezone; preserves exact original strings. It records XML absent versus empty optional fields separately. No fields in any paired row are unmapped. No rows are silently discarded.

Station 15400000, January 2020 stage:
- Modern response has four rows. Union of SOAP filter1 (three rows) and filter2 (one row) matches those four identities exactly.
- Level1: midnight MediaDiaria1, 07:00 MediaDiaria0, 17:00 MediaDiaria0. Level2: midnight MediaDiaria1.
- All 124 day-slot values and 124 day statuses are exactly equal numerically across endpoints. All row identities, source measurement-type codes, header times and update dates match.
- Of 312 total field comparisons, one monthly Media differs: SOAP 1355.77417 versus modern 1355.7742. Do not claim complete endpoint equality.
- The simultaneous midnight level1 and level2 versions have differing values, as already observed. Both are source records. Source documentation explicitly names them Bruto and Consistido. Neither may be removed under an invented quality rule.

January 2024 stage: three paired rows (midnight/07:00/17:00), all 234 field comparisons equal numerically, including all slots/statuses and headers.

January 2020 discharge level2 and January 2024 discharge level1: one paired row each, MediaDiaria1. Identity, slots, status layout and source method codes correspond. All 62 day statuses match. Daily values are **not generally numerically identical**: all 62 modern values equal SOAP values only after decimal rounding to 0.1. `discharge-rounding-diagnostic.json` states that explicit diagnostic transformation. It is not permission to round or substitute values. The source update dates differ too:
- 2020: SOAP DataIns 2023-04-20; modern Data_Ultima_Alteracao 2025-07-07.
- 2024: SOAP DataIns 2024-03-07; modern Data_Ultima_Alteracao 2025-01-08.

Consequently retain modern numbers when retrieving modern output. SOAP supplies corroborating field/row structure and its own documented source partition vocabulary, not proof that all publications are interchangeable. Note endpoint-specific native casing: modern stage `nivelconsistencia`, modern discharge `Nivel_Consistencia`; SOAP `NivelConsistencia`.

## Frontend published download route

Official Hidroweb frontend and runtime/chunks retained as publisher research material with exact URLs/hashes/timestamps in *jobs.json.identities.json. Source JS, not guessed routes, shows conventional download formats MDB, TXT and CSV, and `/documento/download/files` with `codigoestacao`, `tipodocumento`, `forcenewfiles=N`. It also shows `/documento/download/selectedfiles` and `/documento` listing using the frontend OAuth headers. `frontend-download-excerpts.json` is a derived exact-substring excerpt with material identities in the adjacent manifests; not original observation bytes.

The public document list request at https://www.snirh.gov.br/hidroweb/rest/api/documento?size=100&page=0 returned 401, retained with safe URL/timestamp/hash. No frontend auth exchange was attempted and no exchange tokens were passed between origins. The station download route lacks a bounded date argument in the inspected frontend and may download the entire station history, so it was not invoked under this task's bounded-observations constraint. This does not establish source absence or rule out usable manuals.

## Meaning and remaining tests

1. A faithful design can expose both explicitly source-named consistency partitions, with no preferred/winning level. The root must decide the appropriate existing public-series representation; this research does not prescribe product-id changes or select one level. Modern requests currently return both levels, so any filtered partition must still retain its full original receipt and explicitly declare the source-level filter.
2. A Hidro dictionary/manual still must establish MediaDiaria's exact codes, daily slots/calendar interpretation and conventional units. Paired evidence makes reference to actual Hidro field definitions supportable; Portuguese names alone do not suffice. Root coordinates this with the documentation worker.
3. Source-established timezone and daily support remain unestablished by these materials; no timezone/24-hour window was inferred.
4. Later implementation tests must cover both simultaneous levels, distinguish the 07:00/17:00 rows from the MediaDiaria1 row, preserve current source values without SOAP rounding, and account for endpoint-specific casing and null/empty states.
5. Existing modern recordings include month-selection asymmetry, leap day and partial-month bounds. Once daily label definitions are documented, separately acquire final engine-aligned requests if needed and give original recordings plus official definitions to an independent expectation author. This worker has not authored those boundary literals.
6. This comparison proves five bounded SOAP requests only. It does not establish national product availability, universal cross-endpoint equality, source precedence, or a current-API undocumented query selector.

## Follow-up: modern exact month recordings

On parent authorization, six exact month requests were additionally acquired through the established root composition: `RecordingTransport(CredentialExchangeTransport(HttpClient(), CredentialHeader(...), ExchangeSpec.ana(), _SystemClock()))`. Root ignored `.env` was read only by `credential_value` at the script composition root with process-environment precedence. No credential copy, secret output, exchange recording or alternate-origin credential use occurred. This follow-up used credentials; the public SOAP phase above did not.

Outputs are in `modern-monthly/`. Both HidroSerieVazao and HidroSerieCotas were requested for station15400000, DATA_LEITURA, with exact pairs 2020-01-01..2020-01-31, 2024-01-01..2024-01-31 and 2024-02-01..2024-02-29. Optional hour fields were omitted. All six returned HTTP200, no retries. `months.json` holds job identities, `months.json.results.json` response digests and monthly row counts, and `source-field-summary.json` is explicitly derived JSON field/header/slot census preserving all source strings/statuses/nulls. Original bytes remain in the six recording envelopes. No observation boundary literals or product semantics were authored. These requests match the root-specified future year-month inclusive-date request identities, without consulting port code/output.
