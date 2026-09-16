# ANA adopted telemetry recordings

These four unchanged `RecordingEnvelope` files were acquired through the shared
credential-exchange and recording transports on 2026-09-16. They carry safe request
identities, response bytes, retrieval instants and SHA-256 digests. Token-exchange
bodies and credential values are not retained. These test inputs do not ship in the wheel.

Official sources:
- OpenAPI: https://www.ana.gov.br/hidrowebservice/api-docs
- Manual: https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf
- Endpoint: `EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1`

All requests use station `15400000`, `Tipo Filtro Data=DATA_LEITURA` and
`Range Intervalo de busca=DIAS_30`. Filenames name the exact `Data de Busca` date.
The current OpenAPI documents a 30-day cap and DIAS_30; the older manual screenshot
shows only 24-hour choices. The source versions are not conflated.

## Evidence and contracts

Manual PDF page 11 documents `Cota_Adotada` in cm, `Vazao_Adotada` in m3/s and
`Data_Hora_Medicao` as measurement/collection time. The safe page 11–12 text excerpt
is retained here. Source timezone and sentinel meanings are not established.
Finite decimal strings remain values; JSON nulls remain nulls. Blank, nonfinite,
malformed values and invalid source identity fail loudly. No value is discarded
or selected using adopted status or update time. Status strings/nulls are surfaced
as uninterpreted informational issues. Receipt bytes preserve all native fields.
Duplicate source rows retain their multiplicity, including differing values.

The four exact recordings establish:
- Dec5: a full November6–December5 source range, including real null adopted
  values and null statuses at November18. Null update time does not erase values.
- Jan1 and Jan31: adjacent whole30-day ranges December3–January1 and
  January2–January31. No continuity is inferred from their source gaps.
- Jan4: December6–January4, unordered in the source array. It overlaps Jan1 and
  supports the independent midnight probe documented in `independent-expectations.md`.

Independent expectation author inspected source bytes and official documentation
only, not the stage implementation or its output. Both products have the three
independent literals: count5, first2024-01-01T23:30:00, last2024-01-02T00:30:00,
zone unknown. The recorded manual example values are not used as observations.

## Window regression

The engine's existing capped-span30 declaration produces a short final span.
For requested December5–January2, padding gives December3–January4. Using DIAS_30
at each rendered stop gives anchors January1 and January4, repeating source rows.
A fail-first diagnostic over the real engine and exact replays found duplicated
canonical observations. Neither driver nor conversion deduplicates.

`fixed-backward-span` instead covers padded calendar dates with disjoint, fixed-size
inclusive spans, working backward from the padded final date. Each span contains
exactly30 source days; the earliest may extend less than30 days before the padded
start. The provider uses only the rendered stop as the DIAS_30 anchor. The engine
performs all arithmetic and final clipping. That same request now uses December5
and January4, with no duplicate requested rows. Existing granularities are unchanged.
The test also replays adjacent January1/January31 requests, and property-style
planner tests cover short tails, multiples, leap days and year changes.

## Scope

These are two public stage products: `discharge_instantaneous` and
`stage_instantaneous`, using the adopted endpoint rather than a new quality axis.
The certified national catalogue exposes both as explicit candidates for every
Fluviometrica station, with unknown support except where exact per-product
observations establish bounded availability. This is not the complete Brazil outcome.
Conventional daily semantics and water temperature remain unresolved; legacy reference
code is deliberately retained. These recordings prove one station's measurements,
not national station-product availability or a published period of record.

## Safe manual acquisition identity

`manual-page11-acquisition.json` records the actual unauthenticated shared-transport
retrieval instant, source URL, content type and digest/size of the publisher PDF.
The original PDF existed only in memory and was discarded to exclude its
illustrative authentication tutorial. `manual-page11-derived.txt` is explicitly
**derived**, not a RecordingEnvelope or original HTTP response. Its independent
SHA-256 and size are recorded beside the deterministic extraction rule:
`pypdf==6.13.1`, `PdfReader(BytesIO(content)).pages[10].extract_text(extraction_mode="plain").encode("utf-8")`.

The source investigator's capture script is retained with output directory made
an explicit command-line argument. It never reads credentials or persists the full
PDF. An authorized maintainer can reacquire into a separate directory using:

```sh
uv run --with pypdf==6.13.1 python tests/recordings/br_ana/capture_manual_page11.py .worktrees/ana-manual-refresh
```

This command makes a live unauthenticated request; ordinary tests do not run it.
A fresh response may differ. Original source identity and derived identity must
not be conflated or overwritten without evidence review.

## Root-owned public live verification

The root implementing agent ran the normal public API with its intentionally
provisioned working-directory credentials against implementation commit
`c3ec5f34972ce8076daeac4a19037c6299867f39` on 2026-09-16. No credential file was copied.
`public-live-verification.json` is the unchanged sanitized summary, not a source
recording or independent expectation. Both products returned five native rows across
midnight, unknown zone, two exact-body receipts matching the Jan4 recording SHA,
and three source calls (one shared exchange and two observation requests). Only
informational source-status and unestablished-citation issues occurred.

The root-authored script is retained as `verify_public_ana.py`; formatting and
creation of its output directory were added, without changing its public calls.
An authorized maintainer can run `uv run python tests/recordings/br_ana/verify_public_ana.py`
from the working directory containing their own credentials. It makes live requests;
ordinary tests never run it. This proves representative telemetry access, not daily
support, universal station availability or completion of the full Brazil vision.
