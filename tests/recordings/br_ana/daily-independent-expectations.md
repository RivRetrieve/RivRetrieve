# Independent ANA daily-source expectations

## Independence and scope

Authored from the six untouched modern-monthly recordings, official Hidro 1.4 dictionary pages 21–24, source-owned selected SQL views and original hash chain. Read AGENTS.md, CONTEXT.md and the full standalone Brazil vision for intent. No provider code, daily implementation worktree, legacy parser, implementation output or output-derived tests were inspected. No checkout, credentials, owner.env, live requests, commits or PRs were used. This directory is a private evidence artifact, not an implementation worktree or publisher recording.

`daily-independent-read-source.py` is an independent standard-library reading script, run with `uv run python`. `daily-independent-expectations.json` is its derived machine output, not a source recording. It contains every numbered slot, exact strings/nulls/statuses, all row headers, source row indices (zero-based), header types, verified body hashes and the four probes. The script imports no project modules. Reproduce from repository root:

```text
uv run python tests/recordings/br_ana/daily-independent-read-source.py /path/to/private/brazil-daily-research /tmp/daily-independent-expectations.json --verify-originals
```

## Source semantics and calendar derivation

Hidro 1.4, pages 21/23: MediaDiaria 0 = Não, 1 = Sim, “Indica se a medição é uma média diária ou é instantânea”. Data has format MM/AAAA and means “Mês/ano em que foram realizadas as medições”. Pages 22/24 define Cota01..31 in cm and Vazao01..31 in m3/s as the value for each day of the month. Pages 21/22 define consistency 1 = Bruto, 2 = Consistido. The old Hidro 1.0 level codes are obsolete and not used.

Current source spelling matters: stage uses `nivelconsistencia`; discharge uses `Nivel_Consistencia`. Both use `Mediadiaria`, `codigoestacao`, `Data_Hora_Dado` and underscored numbered slots. All these identifiers, headers, flags, values and statuses in these recordings are JSON strings, except published JSON nulls. The request station code is a JSON integer. The exact current API values are authoritative; no SOAP replacement or precision adjustment occurs.

Publisher `vwCotaMedia` explicitly maps C.Cota15 to C.Data + 14 and C.Cota16 to C.Data + 15; the full series maps day n to Data + (n-1). The dictionary gives the same numbered-day/month semantics for discharge. All selected daily-mean headers are explicitly the first calendar day at `00:00:00.0`. Therefore day15/day16 preserve that recorded midnight **calendar label** on the 15th/16th. This is not an inferred timezone, absolute instant, midnight-to-midnight support interval or measurement time. Timezone and exact 24-hour support remain unknown. An unexpected non-midnight mean header cannot be silently reset using this evidence.

The SQL view's level2 restriction is local to that view, not a preference policy. Series_Cotas and Series_Vazoes group independently by station, consistency and mean flag. Bruto and Consistido names identify source variants only. No combining, preferred-level selection, fallback, status-based filtering or computation from 07:00/17:00 rows is authorized.

Daily status vocabulary from 1.4: 0 BRANCO; 1 Valor real; 2 Valor estimado (*); 3 Valor duvidoso (?); 4 Régua Seca (#); 5 Régua Coberta (!); 6 Rio Seco (@); 7 Rio Cortado (/). These are source judgments, not canonical quality ranks. Status “1” is the source's claim, not an independent accuracy assessment.

## Four boundary probes

All windows below are closed at both ends. The source request is the complete January month with `Tipo Filtro Data="DATA_LEITURA"`, station15400000, exact start/end shown in the recording filename. Source envelopes are GET /EstacoesTelemetricas/HidroSerieCotas/v1 or HidroSerieVazao/v1, HTTP200 application/json, body status="OK", code=200, message="Sucesso". Credential header names only are retained; no credential values or authentication response bytes are included.

### stage_daily_mean_bruto

Recording: `HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json`, source row index **2**.

```json
{
  "codigoestacao": "15400000",
  "Data_Hora_Dado": "2020-01-01 00:00:00.0",
  "Mediadiaria": "1",
  "nivelconsistencia": "1",
  "Tipo_Medicao_Cotas": "1",
  "Data_Ultima_Alteracao": "2020-05-12 00:00:00.0"
}
```

Requested: `2020-01-15T00:00:00` through `2020-01-16T00:00:00`.

**Literals: count=2; first=2020-01-15T00:00:00; last=2020-01-16T00:00:00.**

| Source field | Exact source string | Exact status string | Canonical value |
|---|---|---|---|
| `Cota_15` | `"1413.0"` | `"1"` | 14.13 m |
| `Cota_16` | `"1393.5"` | `"1"` | 13.935 m |

Count is enumerated from the two present, non-null numbered slots in the uniquely matching actual row, not assumed continuity.

### stage_daily_mean_consistido

Recording: `HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json`, source row index **3**.

```json
{
  "codigoestacao": "15400000",
  "Data_Hora_Dado": "2020-01-01 00:00:00.0",
  "Mediadiaria": "1",
  "nivelconsistencia": "2",
  "Tipo_Medicao_Cotas": "1",
  "Data_Ultima_Alteracao": "2023-04-20 00:00:00.0"
}
```

Requested: `2020-01-15T00:00:00` through `2020-01-16T00:00:00`.

**Literals: count=2; first=2020-01-15T00:00:00; last=2020-01-16T00:00:00.**

| Source field | Exact source string | Exact status string | Canonical value |
|---|---|---|---|
| `Cota_15` | `"1413.0"` | `"1"` | 14.13 m |
| `Cota_16` | `"1394.0"` | `"1"` | 13.94 m |

Count is enumerated from the two present, non-null numbered slots in the uniquely matching actual row, not assumed continuity.

### discharge_daily_mean_consistido

Recording: `HidroSerieVazao_15400000_2020-01-01_2020-01-31.recording.json`, source row index **0**.

```json
{
  "codigoestacao": "15400000",
  "Data_Hora_Dado": "2020-01-01 00:00:00.0",
  "Mediadiaria": "1",
  "Nivel_Consistencia": "2",
  "Metodo_Obtencao_Vazoes": "1",
  "Data_Ultima_Alteracao": "2025-07-07 00:00:00.0"
}
```

Requested: `2020-01-15T00:00:00` through `2020-01-16T00:00:00`.

**Literals: count=2; first=2020-01-15T00:00:00; last=2020-01-16T00:00:00.**

| Source field | Exact source string | Exact status string | Canonical value |
|---|---|---|---|
| `Vazao_15` | `"31218.674"` | `"1"` | 31218.674 m³/s |
| `Vazao_16` | `"30587.594"` | `"1"` | 30587.594 m³/s |

Count is enumerated from the two present, non-null numbered slots in the uniquely matching actual row, not assumed continuity.

### discharge_daily_mean_bruto

Recording: `HidroSerieVazao_15400000_2024-01-01_2024-01-31.recording.json`, source row index **0**.

```json
{
  "codigoestacao": "15400000",
  "Data_Hora_Dado": "2024-01-01 00:00:00.0",
  "Mediadiaria": "1",
  "Nivel_Consistencia": "1",
  "Metodo_Obtencao_Vazoes": "1",
  "Data_Ultima_Alteracao": "2025-01-08 00:00:00.0"
}
```

Requested: `2024-01-15T00:00:00` through `2024-01-16T00:00:00`.

**Literals: count=2; first=2024-01-15T00:00:00; last=2024-01-16T00:00:00.**

| Source field | Exact source string | Exact status string | Canonical value |
|---|---|---|---|
| `Vazao_15` | `"13202.701"` | `"1"` | 13202.701 m³/s |
| `Vazao_16` | `"13652.53"` | `"1"` | 13652.53 m³/s |

Count is enumerated from the two present, non-null numbered slots in the uniquely matching actual row, not assumed continuity.

## Leap-day and month-boundary source facts

February2024 has 29 calendar days. Below are **all** rows in the two February bodies, including explicitly non-mean stage rows to make exclusions auditable. Every value and status field shown is present. `null` is a published JSON null, never an absent key or numeric zero. Day30/31 are invalid slots of February and cannot become March1/2 observations. No March recording was inspected or invented, so these facts do not establish March availability or continuity across February/March.

| Endpoint, row | Header Data_Hora_Dado | mean / level strings | day28 value/status | day29 value/status | day30 value/status | day31 value/status |
|---|---|---|---|---|---|---|
| Cotas, 0 | `2024-02-01 07:00:00.0` | `0` / `1` | `"1368.0"` / `"1"` | `"1393.0"` / `"1"` | `null` / `"0"` | `null` / `"0"` |
| Cotas, 1 | `2024-02-01 17:00:00.0` | `0` / `1` | `"1382.0"` / `"1"` | `"1399.0"` / `"1"` | `null` / `"0"` | `null` / `"0"` |
| Cotas, 2 | `2024-02-01 00:00:00.0` | `1` / `1` | `"1375.0"` / `"1"` | `"1396.0"` / `"1"` | `null` / `"0"` | `null` / `"0"` |
| Vazao, 0 | `2024-02-01 00:00:00.0` | `1` / `1` | `"29893.217"` / `"1"` | `"30559.402"` / `"1"` | `null` / `"0"` | `null` / `"0"` |

Daily-mean Bruto stage on February28/29 is respectively **13.75m, 13.96m**, with calendar labels `2024-02-28T00:00:00` and `2024-02-29T00:00:00`. Daily-mean Bruto discharge is **29893.217m³/s, 30559.402m³/s**, same labels. Each has two present non-null observations in that closed two-label window. These February responses contain no Consistido rows; that is a bounded response fact, not proof the variant is unavailable for the station or other requests.

For an actually recorded inter-month edge, January31/February1 daily-mean Bruto source strings and statuses follow. These facts do not require a fabricated March response.

| Endpoint | January31 value/status | February1 value/status |
|---|---|---|
| HidroSerieCotas | `"1045.0"` / `"1"` | `"1075.5"` / `"1"` |
| HidroSerieVazao | `"20299.523"` / `"1"` | `"21116.312"` / `"1"` |

Across all six recordings, every valid calendar-day value is present and non-null in every returned row. There are no empty-string numbered values. Each January row has 31 present values. Each February row has 29 present values plus day30/31 present-null values with status "0". This bounded finding does not test a null on a valid observation date, an absent numbered key, a non-leap February, a year boundary or a wholly absent month. Such behavior must not be claimed as evidenced by this corpus.

## Verified provenance

All six body SHA-256 checks pass after strict base64 decoding. Request envelopes retain precise month limits and recording UTC instants in machine output. Authentication prerequisite envelopes withhold secret responses. The script also verifies original ZIP bytes against acquisition identity, ZIP-member equality against retained installer bytes, installer hash against extraction manifest, and retained PDF/SQL hashes and byte counts against that manifest. Every selected SQL view is an exact substring of the original UTF-16 SQL. Installer extraction itself was recorded by the researcher (binary-refinery0.11.2), not repeated here; the installer was not executed. The dictionary text is a researcher-derived page extraction from the hashed PDF, read here along with the report; this author did not re-render or independently visually verify those pages.

Original distribution URL: https://www.snirh.gov.br/portal/snirh-1/sistemas/gestao-e-analise-de-dados-hidrologicos/instalador-hidro-build-1-4-0-81.zip

- zip: `68a8da15e82d254e631431fd18a64c29f1ad1e46b58e6c94b3aa1f3f3e33d373`
- installer: `0a004473f7ae4e98f0e968ec747146f0064bd0f9b564cde74e4b1c468c0812ac`
- Hidro 1.4 - Novidades do Sistema.pdf: `d098fe733740299c25ef3fc33ac7e96d6b21ff01925150d6b1d74791914e24f8`
- Hidro SQLSERVER 2008.sql: `6136dd163ba52d5863ffd6b70c9f3aace5d5551abdd1599c5f2972f0a4f9fb98`

| Recording | Body SHA-256 | Retrieval UTC |
|---|---|---|
| HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json | `cc33bfc96aeebd9fcdb88fc3262d7fa91ec88b3c8154495cc4739dd59979f552` | 2026-09-16T13:06:14.122416Z |
| HidroSerieCotas_15400000_2024-01-01_2024-01-31.recording.json | `4a663fe96402026175c08fec6a8bba14767f693e254f78f7ade3a725f79487a3` | 2026-09-16T13:06:16.319327Z |
| HidroSerieCotas_15400000_2024-02-01_2024-02-29.recording.json | `852c468844854122e8ccb29ff3be495e93cfaf27f42bd02c0c7d6a894c0a0eec` | 2026-09-16T13:06:18.477913Z |
| HidroSerieVazao_15400000_2020-01-01_2020-01-31.recording.json | `e681d5067c0672f793c736f6c31aeb0bd07f872a37a749a65d438a67a55f99fe` | 2026-09-16T13:06:12.898706Z |
| HidroSerieVazao_15400000_2024-01-01_2024-01-31.recording.json | `ec4528bc3024514cde576a5ce69fc2aa0f29ebf72b81ee05fc1c8df9780bcb2c` | 2026-09-16T13:06:15.120739Z |
| HidroSerieVazao_15400000_2024-02-01_2024-02-29.recording.json | `dd5d8878a92abf2045381d36b3362fa7e7ac978ac1545c56c9c11655d0edc6f9` | 2026-09-16T13:06:17.330254Z |

## Extension: independently audited December2023 and non-leap February2023

This appended audit reads four additional exact source recordings only. Original four January probes are unchanged (machine-object equality checked). The reading script now admits the ten `HidroSerie*.recording.json` monthly recordings only, not unrelated telemetry files. All ten body hashes and envelopes pass the same offline verification. The earlier six-recording limitations describe the original corpus; this extension adds a real year boundary and non-leap February, but still no valid-calendar null value or absent month evidence. Null **status** is now positively observed and remains distinct from null **value**.

### Year boundary

Closed requested window: `2023-12-31T00:00:00` through `2024-01-01T00:00:00`. Day31 is December header +30days; day1 is the January header itself. Both mean headers are explicitly midnight. No timezone or exact daily support is inferred.

December2023 stage has mean1 level1 and mean1 level2, plus level1 mean0 07/17 rows. January2024 stage has mean1 level1 and level1 mean0 07/17 rows, **no level2 row in this response**. Thus the source does not confirm both stage mean levels in both months. December2023 discharge contains only mean1 level2; January2024 discharge contains only mean1 level1. Counts below keep levels separate and use only actual matching rows. No fallback is allowed. A missing variant here is a bounded response fact, not global station unavailability.

| Product | Count literal | First literal | Last literal |
|---|---|---|---|
| stage_daily_mean_bruto | 2 | `2023-12-31T00:00:00` | `2024-01-01T00:00:00` |
| stage_daily_mean_consistido | 1 | `2023-12-31T00:00:00` | `2023-12-31T00:00:00` |
| discharge_daily_mean_bruto | 1 | `2024-01-01T00:00:00` | `2024-01-01T00:00:00` |
| discharge_daily_mean_consistido | 1 | `2023-12-31T00:00:00` | `2023-12-31T00:00:00` |

Exact source evidence for each hit (all station codes `"15400000"`, all `Mediadiaria="1"`; stage key `nivelconsistencia`, discharge key `Nivel_Consistencia`):

| Product | Recording / row index | Monthly Data_Hora_Dado | Level | Day field | Value / status | Canonical value |
|---|---|---|---|---|---|---|
| stage_daily_mean_bruto | `HidroSerieCotas_15400000_2023-12-01_2023-12-31.recording.json` / 2 | `2023-12-01 00:00:00.0` | `1` | `Cota_31` | `"759.5"` / `null` | 7.595 m |
| stage_daily_mean_bruto | `HidroSerieCotas_15400000_2024-01-01_2024-01-31.recording.json` / 0 | `2024-01-01 00:00:00.0` | `1` | `Cota_01` | `"778.0"` / `"1"` | 7.78 m |
| stage_daily_mean_consistido | `HidroSerieCotas_15400000_2023-12-01_2023-12-31.recording.json` / 3 | `2023-12-01 00:00:00.0` | `2` | `Cota_31` | `"758.0"` / `"1"` | 7.58 m |
| discharge_daily_mean_bruto | `HidroSerieVazao_15400000_2024-01-01_2024-01-31.recording.json` / 0 | `2024-01-01 00:00:00.0` | `1` | `Vazao_01` | `"13774.469"` / `"1"` | 13774.469 m³/s |
| discharge_daily_mean_consistido | `HidroSerieVazao_15400000_2023-12-01_2023-12-31.recording.json` / 0 | `2023-12-01 00:00:00.0` | `2` | `Vazao_31` | `"13299.191"` / `"1"` | 13299.191 m³/s |

The December31 Bruto stage value is published and must not be discarded because its status is JSON null. All December2023 stage Bruto rows have null daily statuses on every valid date, while their daily values are present. All daily values on valid dates in the four new recordings are present and non-null; no empty-string daily values occur. These are direct source facts, not quality judgments.

### Non-leap February2023 versus leap February2024

Every field below is present. `null` means JSON null, not a missing key. February2023 day29/30/31 cannot represent March observations. Crucially, invalid-slot statuses are not uniformly "0": the Consistido rows have **null status** as well as null value. The source does not authorize replacing null status with "0".

| Endpoint / row | Data_Hora_Dado | Mean / level | day28 value/status | day29 value/status | day30 value/status | day31 value/status |
|---|---|---|---|---|---|---|
| Cotas / 0 | `2023-02-01 00:00:00.0` | `1` / `1` | `"1350.0"` / `"1"` | `null` / `"0"` | `null` / `"0"` | `null` / `"0"` |
| Cotas / 1 | `2023-02-01 17:00:00.0` | `0` / `1` | `"1344.0"` / `"1"` | `null` / `"0"` | `null` / `"0"` | `null` / `"0"` |
| Cotas / 2 | `2023-02-01 07:00:00.0` | `0` / `1` | `"1356.0"` / `"1"` | `null` / `"0"` | `null` / `"0"` | `null` / `"0"` |
| Cotas / 3 | `2023-02-01 00:00:00.0` | `1` / `2` | `"1350.0"` / `"1"` | `null` / `null` | `null` / `null` | `null` / `null` |
| Vazao / 0 | `2023-02-01 00:00:00.0` | `1` / `2` | `"29151.938"` / `"1"` | `null` / `null` | `null` / `null` | `null` / `null` |

Mean1 February28 stage: both variants publish "1350.0"cm = **13.5m**, status"1". Mean1 Consistido discharge: "29151.938"m³/s, status"1". Their label is `2023-02-28T00:00:00`; no February29 label exists in 2023. For comparison, in February2024 mean1 Bruto stage day29 is "1396.0"cm/status"1" and Bruto discharge day29 is "30559.402"m³/s/status"1". Day30/31 remain present-null/status"0" in the recorded 2024 rows. This comparison describes the returned variants without implying Consistido availability in 2024 or Bruto discharge availability in February2023.

### New recording identity

All requests are GET to the endpoint named in the filename at the same official ANA origin, station integer15400000, `Tipo Filtro Data="DATA_LEITURA"`, exact complete-month dates in the filename. All are HTTP200 application/json and body status"OK"/code200/message"Sucesso". Header envelopes contain no credential values. Full typed row headers and every slot are in the extended machine output.

| Recording | Verified body SHA-256 | Retrieval UTC |
|---|---|---|
| HidroSerieCotas_15400000_2023-02-01_2023-02-28.recording.json | `f21abfe9fb42ec6221c0eedce3620e7c6bce9ffdc25dcdd263d29456b79d91bc` | 2026-09-16T13:23:23.640838Z |
| HidroSerieCotas_15400000_2023-12-01_2023-12-31.recording.json | `7209fe8a81a6bbd53d3bb550a54144f0bcf9d29f15bca10639e1caed81fc9f03` | 2026-09-16T13:23:21.551952Z |
| HidroSerieVazao_15400000_2023-02-01_2023-02-28.recording.json | `f77f751e1bff6d1e6bc9fa32b098a9923eb790fb9d4ca75aed5d15260b6d7894` | 2026-09-16T13:23:22.562922Z |
| HidroSerieVazao_15400000_2023-12-01_2023-12-31.recording.json | `68c7946311f5906135c34ac15c64fbe6e9461b970773f9a1d8b1657d011c79f3` | 2026-09-16T13:23:20.240768Z |

## Retention note

The implementation test owner copied this independent report after authorship. Only artifact names, invocation paths and this retention note were updated. The JSON is retained unchanged. The copied script received repository formatter/import-order changes and an explicit ten-file input list matching the author's original JSON. This prevents later captures from changing the original authorship scope; the source-reading and expectation logic is unchanged. Full hash-chain replay requires the private research originals, including publisher software, which are deliberately not committed or packaged. The ten observation envelopes are retained beside this report.

### Retained-only replay (maintenance adaptation)

The implementation owner added a retained-only mode after independent authorship:

```text
uv run python tests/recordings/br_ana/daily-independent-read-source.py tests/recordings/br_ana /tmp/daily-retained-audit.json
```

This mode verifies observation body hashes, reads the retained dictionary/SQL derived excerpts and reproduces the original ten-recording slot audit and four January probes and four year-boundary probes. It does **not** revalidate the excluded original ZIP, installer, PDF or SQL. Its output explicitly leaves `verified_source_hash_chain` empty and names that limitation. The optional `--verify-originals` mode preserves the original full-chain check against private research inputs. Input wiring and this optional check were adapted after authorship; numbered-slot and probe arithmetic remain the independent author's code. The retained `daily-independent-expectations.json` is the unchanged original output, not this maintenance adaptation's output.
