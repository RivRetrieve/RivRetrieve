# Brazil ANA inventory certification

Related issue: [#213](https://github.com/RivRetrieve/RivRetrieve/issues/213).

## Delivered boundary

The certified inventory now supports authenticated adopted telemetry through the normal
public API: `discharge_instantaneous` and `stage_instantaneous`. The declaration is
`LiveStages`, using the shared ANA credential exchange. Four conventional daily-mean source variants are also supported:
`discharge_daily_mean_bruto`, `discharge_daily_mean_consistido`,
`stage_daily_mean_bruto`, and `stage_daily_mean_consistido`.
Water temperature remains unsupported. Final vision completion and legacy retirement
require the root-owned verification record; implementation alone is not that claim.

Every certified Fluviometrica station is a candidate for all six supported products. Its
availability is `unknown` unless nonnull measurements of the exact source variant were recorded for
that station/product. Station `15400000` has this bounded observed evidence. Unknown
candidates remain selectable, not silently excluded by telemetry flags or empty periods.
Inventory membership does not establish endpoint/variant product availability. No probed
window or operating period becomes a published record bound. Source flags remain native
and uninterpreted; there are no inferred `unavailable` relationships.

Request access from `telemetria@ana.gov.br`. ANA's identifier is not the account email.
Copy `.env.example` to your own working-directory `.env` and fill `ANA_IDENTIFICADOR`
and `ANA_SENHA`, or set process variables (which take precedence). Credentials stay at the
public composition root and never enter recordings, receipts or provenance. Documentation:
https://www.ana.gov.br/hidrowebservice/swagger-ui.html#/ . Password reset:
https://www.snirh.gov.br/hidrotelemetria/Login2.aspx .

```python
import rivretrieve as rr
selection = rr.find(provider="br_ana", station="15400000", product="discharge_instantaneous")
result = rr.fetch(selection, start="2024-01-01 23:30", end="2024-01-02 00:30", receipts=True)
```

Times are native naive measurement timestamps with `time_zone="unknown"`. No geographic
offset is inferred. Adopted source statuses are informational source words, never canonical
quality classes. Null adopted values stay null; undocumented numeric sentinel meanings are
not invented. Shared conversion handles stage cm to m and discharge m3/s unchanged.

The endpoint's fixed backward DIAS_30 source ranges are declared to the shared engine.
The engine covers padded dates with disjoint30-day spans anchored at the final fetch date,
expands the earliest source span by less than30 days when needed, and clips once to the
closed requested wall-clock window. Provider code does no date arithmetic or deduplication.
See `tests/recordings/br_ana/` for exact observation recordings, independently authored
midnight expectations, the actual overlapping-tail regression, and safe derived manual evidence.

## Acquired population and native fidelity

The 2026-09-16 acquisition covers all 27 documented UF filters and all nine documented basin
filters of `HidroInventarioEstacoes/v1`. The 36 successful recordings contain 78,836 row
occurrences and 40,747 distinct station identities. All overlapping source rows are identical.
Every supporting recording and row occurrence is retained. Conflicting overlaps fail rather
than selecting a preferred source row. Native `retrieved_at` is the earliest containing
acquisition instant; it is not an observation date or a source update timestamp.

The native table preserves all 69 source columns, exact strings, nulls, casing and native
terms, including 2,658 foreign station identities absent from the domestic UF sweep.
Source columns and station identities are sorted lexically for deterministic materialization.
The canonical projection is exactly `Tipo_Estacao == "Fluviometrica"`: 17,914 river gauges.
The remaining 22,833 `Pluviometrica` records remain native and explicitly accounted, not
acquisition-withheld. Unknown or missing source station types fail. No acquired source row
is dropped for coordinates, geography, operating status or inferred product support.
The origin gate compares the explicit river-gauge native projection one-to-one with the
canonical table; its global no-row-loss invariant is unchanged.

This is the population returned by the documented enumerated filters, not a claim that
undocumented records with both null UF and null basin cannot exist. All UF identities also
occur in the basin sweep. The basin9 cross-check first exposed foreign records; the final
nine-basin sweep retains them instead of imposing an arbitrary geographic exclusion.
Original seven HTTP503 UF attempts and successful retries remain separate acquisition
outcomes. A failed attempt is never an empty successful response.

Latitude and longitude are strict numeric conversions of source strings. Their CRS is
withheld because acquisition evidence does not establish it. No CRS, coordinate-derived
timezone, area unit or availability is inferred. ANA's independently retained institutional
open-data statement is surfaced verbatim. No citation request was established.

## Offline reproduction and maintenance

Native input, compressed recordings and private acquisition reports are repository build
inputs, excluded from both distributions. The capture attestation identifies exact requests,
retrieval instants, recording and payload digests, counts and the revision-pinned native file.
The public provenance and Croissant descriptor are generated from exact emitted bytes.

```bash
uv run python src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py \
  --materialize-record tests/test_data/br_ana_inventory/capture.json \
  --repository-root . --native-out /tmp/ana-native.parquet
uv run python src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py \
  --native /tmp/ana-native.parquet \
  --capture-record tests/test_data/br_ana_inventory/capture.json \
  --out /tmp/ana-catalogue
```

Maintainer refresh uses the shared secure credential exchange. Run from the working directory
where the owner intentionally provisioned credentials; no secret file is copied into a worktree.
Process environment takes precedence over the explicit env file. The output directory must
not already exist, so a new acquisition never overwrites historical attempts.

```bash
uv run python scripts/acquire_ana_inventory.py --out <new-acquisition-directory> --env-file <owner-supplied-env-file>
```

A new capture requires reconciliation, fresh native materialization, a pinned input commit and
reviewed attestation before publishing. Do not point an old attestation at a new response.
The original acquisition scripts and outcome reports are retained under
`research/station-coverage/br_ana/inventory/` as historical evidence, not alternate generators.
Source-row occurrences bind every repeated station to all its acquired files and row indices.

The old `--fixture`, `--live`, `--withhold-uncertified` and direct payload build paths now fail
with an explicit migration message. They cannot publish invented fixtures or bypass the
attested native build. The legacy observation subtree stays intact pending verified replacement.

## Conventional daily source contract

The official Hidro Build1.4.0.81 distribution's **Hidro1.4 – Novidades do Sistema**
Appendix A (PDF pages21–24) states `MediaDiaria=0` means instantaneous and `1` means
daily mean. It defines `NivelConsistencia=1` as Bruto and `2` as Consistido, `Data`
as measurement month/year, `Cota01..31` as each day's stage in cm, and `Vazao01..31`
as each day's discharge in m3/s. The older Hidro1.0 dictionary's level codes differ
and are not used. Official SQL expands the monthly date by ordinal day and groups
series by station, consistency and mean flag. The SQL analysis view's level2 filter
is not a general permission to prefer Consistido.

Current `HidroSerieCotas/v1` and `HidroSerieVazao/v1` fields are bound to those
source definitions through retained current/SOAP field comparisons. Current API
numbers remain authoritative; differing SOAP precision or update dates never replace
or round them. Full original receipts retain the source's monthly records and statuses.

The daily products select **exactly** `Mediadiaria="1"` plus the requested consistency
code. Stage uses `nivelconsistencia`; discharge uses `Nivel_Consistencia`. Both are
explicit choices. There is no preferred level, fallback, averaging, or generic daily
product that silently changes variants. The simultaneous stage variants in January2020
contain different source values. Instantaneous07:00/17:00 rows with meanflag0 are not
converted into daily means. A response without the requested variant yields no readings,
not another variant and not evidence of permanent unavailability.

Daily headers must be the first calendar day at midnight. Numbered slots become their
corresponding calendar date's native midnight label. An unexpected non-midnight mean
header or malformed source code fails rather than being rewritten. This is a label,
not a claim of midnight-to-midnight support: day definition and zone remain `unknown`.
Invalid calendar slots with values fail. Published nulls and blanks become null in the
existing live carrier; no undocumented sentinel meaning is assigned. Duplicate records
within the exact requested variant retain their multiplicity, including differing values.
Status codes remain source judgement, surfaced as informational source-status facts.

The shared engine declares `year-month` granularity, DATE rendering and inclusive stop.
It expands padded requests to whole months, well below the documented366-day cap, then
clips once to the requested window. Provider fetch uses those rendered bounds unchanged.
Day-slot decoding is source-format parsing, not provider-owned request-window arithmetic.

```python
selection = rr.find(provider="br_ana", station="15400000",
                    product="stage_daily_mean_bruto")
result = rr.fetch(selection, start="2020-01-15", end="2020-01-17", receipts=True)
```

## Legacy reference audit

The former implementation's useful leads were the official OAuth, conventional,
adopted and detailed endpoint identities; Portuguese request parameter names; the
monthly day-slot shape; and the telemetry30-day limit. Each supported lead is now
bound to official documentation and exact real recordings rather than its invented
station12345000 payloads. The prior UTC/Brasília assumptions, quality ranking,
per-provider clipping, silent malformed-slot skipping and station-flag exclusion are
not retained. The shared transport handles ordinary Unicode parameter names; provider
code does not pre-encode them or own a credential cache.

A bounded exact detailed-endpoint request for station15400000, January2 2024,
`HORA_24`, returned96 records containing `Temperatura_Agua` and
`Temperatura_Agua_Status`, both null throughout. Their field existence is established;
a positive water-temperature measurement and unit/definition contract are not.
The retained recording digest is
`8f4049713c0b2e46b886052092191ae9d42a0def9047543a74b17eb1bf620feb`.
This one empty-valued request does not establish permanent or national unavailability.
No water-temperature product is exposed. `Temperatura_Interna` is a distinct nonnull
field with both strings and nulls in the same response. It is never substituted for water temperature.
The exact recording and derived field census are retained under `tests/recordings/br_ana/`.

The archived implementation and invented payloads remain recoverable at main commit
`33e063a`, under `reference/legacy_observations/br_ana/`; their original-path inventory
is that subtree's README. Removing the subtree is gated on verified daily and telemetry
replacement, including root-owned live public calls. Retained source evidence lives in
`tests/recordings/br_ana/` and the unchanged inventory capture inputs. These paths are
excluded from both distributions; only generated public catalogue evidence is packaged.
