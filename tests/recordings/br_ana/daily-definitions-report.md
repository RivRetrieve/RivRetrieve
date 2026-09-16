# Official ANA conventional-daily definitions research

Research completed with explicit Hidro1.4 dictionary definitions and source SQL. No owner credentials or authenticated ANA requests used. No production changes. Research outputs are not observation recordings.

## Definitive official dictionary evidence (supersedes earlier open leads below)

The publisher's **Hidro Build1.4.0.81** distribution contains **“Hidro 1.4 - Novidades do Sistema.pdf”**, whose Appendix A is the updated **Dicionário de Dados**. The extracted publisher PDF SHA-256 is `d098fe733740299c25ef3fc33ac7e96d6b21ff01925150d6b1d74791914e24f8`. Original archive identity and extraction transformation are in `hidro-distribution-identity.json` and `hidro-static-documents/extraction-manifest.json` (root used binary-refinery0.11.2; installer was never executed).

`hidro-1.4-conventional-dictionary-derived.json` retains exact text extracted from PDF pages20–24 and original material identity. **Pages21–24 were visually verified against derived page renders** (`hidro-1.4-dictionary-page21-derived.png` through24). These are derived PDF renderings, not original screenshots or observation recordings.

| Concept | Original source definition | PDF page |
|---|---|---|
| Cotas.MediaDiaria | “0 = Não”, “1 = Sim”; “Indica se a medição é uma média diária ou é instantânea” |21|
| Vazoes.MediaDiaria | “0 = Não”, “1 = Sim”; same exact description |23|
| Cotas.Data / Vazoes.Data | Format “MM/AAAA”; “Mês/ano em que foram realizadas as medições” |21/23|
| Cotas.Hora / Vazoes.Hora | Format “HH:MM”; “Hora em que foram realizadas as medições” |21/23|
| Cotas.Cota01..31 | Unit “cm”; “Valor da cota para cada dia do mês” |22|
| Vazoes.Vazao01..31 | Unit “m3/s”; “Valor da vazão para cada dia do mês” |24|
| NivelConsistencia | “1 = Bruto”, “2 = Consistido”; “Indica o nível de consistência do registro” |21/22|

Thus **MediaDiaria1 is the daily-mean source variant;0 is not a daily mean**. This is explicit publisher semantics, not boolean inference. The documented numbered fields are daily values of a monthly record. Their documented unit and statistic are established independently of telemetry.

Daily status values in the same1.4dictionary:0BRANCO,1Valor real,2Valor estimado(*),3Valor duvidoso(?),4Régua Seca(#),5Régua Coberta(!),6Rio Seco(@),7Rio Cortado(/). Retain these source judgements; no new canonical ranking or quality filtering follows.

### Important source-version conflict

The bundled old **Hidro1.0Manual do Usuário** has a data dictionary on PDFpages58–60 with the same meanflag/unit/month descriptions, but its NivelConsistencia rows say **0Bruto/1Consistido**. Do not silently use that outdated mapping. The updated1.3 and1.4 dictionaries say **1Bruto/2Consistido**, agreeing with the current SOAPoperation docs and live modernAPI rows. Cite the1.4dictionary explicitly. The1.0manual Table4(PDFp26, printed20) also lists Cotas and Vazões record identity as station code, consistency level, Data, Hora and Média Diária. This supports distinct record variants, but its old consistency numbers are not current authority.

### Source-owned SQL corroboration

Publisher member “Hidro SQLSERVER 2008.sql”, SHA-256 `6136dd163ba52d5863ffd6b70c9f3aace5d5551abdd1599c5f2972f0a4f9fb98`, is UTF-16 decoded in `hidro-sqlserver-selected-views-derived.json`. Exact CREATE VIEW blocks are retained, not paraphrased:

- `vwCotaMedia` maps `C.Cota01` to `C.Data + 0`, through `C.Cota31` to `C.Data + 30`, with `MediaDiaria=1`. This directly corroborates ordinal expansion. Its own `NivelConsistencia=2` is **local to that analysis view**, not authority to prefer2 or discard1 globally.
- `vwCotas` uses the same daily expansion for paired07:00/17:00 data and explicitly filters `MediaDiaria=0`.
- `Series_Cotas` and `Series_Vazoes` group by `EstacaoCodigo, NivelConsistencia, MediaDiaria` (plus Importado). Source series therefore distinguish processing/statistic variants; they are not accidental duplicates to collapse.

### Remaining scope of the binding

The source's conventional **Hidro** field definitions are now positive and explicit. The current API renames fields (`Data_Hora_Dado`, `Cota_01`, `Vazao_01`, `Mediadiaria`), so retain source-comparison's empirical currentAPI↔SOAP correspondence and the official service statement that this is the Hidrobase. No global byte/value equality is asserted; modern discharge can have different precision/update versions. Preserve modern API values. No timezone or exact24-hour daily support has been established by these definitions, and neither is inferred.

## Provenance and transformations

Official page downloads are identified by URL, final URL, HTTP status, retrieval UTC timestamp, original response SHA-256, byte count and content type in URL-hash-named JSON files. These JSON files contain **derived link lists**, not original HTML. Links with public page authenticity parameters are omitted. `official_research.py` describes extraction. The Progestão indexed search crawl is `progestao-index-crawl.json`; each entry identifies its original page and derived links. Library searches retain extracted visible text and original response hash, not forms/cookies/CSRF values.

The discovery chain for the full Hidro software is:
1. https://www.snirh.gov.br/portal/
2. https://www.snirh.gov.br/portal/search?SearchableText=hidro
3. Search result “Instalador Hidro Build 1.4.0.81.zip”:
   https://www.snirh.gov.br/portal/snirh-1/sistemas/gestao-e-analise-de-dados-hidrologicos/instalador-hidro-build-1-4-0-81.zip

`hidro-distribution-identity.json` identifies the **original public software distribution**, retained privately as `hidro-build-1.4.0.81-original.zip`. ZIP SHA-256 `68a8da15e82d254e631431fd18a64c29f1ad1e46b58e6c94b3aa1f3f3e33d373`; 13,850,470 bytes; retrieved 2026-09-16T13:07:07.223281+00:00. ZIP member “Instalador Hidro Build 1.4.0.exe” is retained as `hidro-installer-original.exe`. This renaming and ZIP extraction do not change the member bytes. Installer identified statically as Inno Setup 5.5.7; never executed. Installed 7z17.05 cannot open it; static extraction delegated to parent.

The official tutorial discovery chain is:
1. https://www.snirh.gov.br/portal/centrais-de-conteudos/central-de-tutoriais/central-de-tutoriais
2. “Tutorial do Sistema de Informações Hidrológicas - Hidro”:
   https://www.snirh.gov.br/portal/centrais-de-conteudos/central-de-tutoriais/tutorial-do-sistema-de-informacoes-hidrologicas-hidro
3. Source redirect to https://portal1.snirh.gov.br/tutorialhidro/
4. HTML names `assets/js/CPM.js`, which names each slide and `dr/*.png` image.

`official-hidro-tutorial-CPM.js` is original JS and `tutorial-identity.json` identifies it. Tutorial PNGs are original publisher screenshot assets, not screenshots generated by this research. Each has its own `.identity.json`. Files `ocr-Slide*.txt` are explicitly **derived OCR**, generated by installed Tesseract with English model, and must not be quoted without visual confirmation. Retained images discussed below were visually inspected. This tutorial visibly demonstrates **Hidro1.2**; current installer is Build1.4.0.81. Do not conflate versions or assert modern endpoint equality.

## Positive conventional units evidence

https://portal1.snirh.gov.br/tutorialhidro/dr/25491.png

Original tutorial asset, chapter03 “Dados de Cotas”, slide25514. It shows the legacy Hidroweb historical station page for PALMEIRAS DO JAVARI10200000. Exact visible words:
- “Consultar série de: Cotas (cm)”
- “Arquivo Access” / “Arquivo Texto”
- “Arquivo Access - para criar arquivo Access compactado com os dados da consulta (esse arquivo pode depois ser importado pelo Hidro).”

This establishes centimetres for the conventional historical cota series in the official Hidroweb/Hidro tutorial. It is not a telemetric-unit transfer. The current endpoint correspondence still requires the paired SOAP/modern field evidence held separately by the source-comparison worker.

https://portal1.snirh.gov.br/tutorialhidro/dr/27025.png

Hidro1.2 UI “Cotas Médias”: monthly Data labels such as 11/1982, 12/1982, 01/1983, 02/1983 and columns “Máxima (cm)”, “Mínima (cm)”, “Média (cm)”, with “Nível de consistência” Bruto. This strengthens conventional unit and monthly-record context. It is not yet a precise Data_Hora_Dado or numbered-day field definition.

https://portal1.snirh.gov.br/tutorialhidro/dr/27529.png

Hidro1.2 UI “Estatísticas de Cotas Médias”, with tabs “Médias Diárias”, “Gráfico de Médias Diárias”, “Médias Mensais”, “Máximas Mensais”, “Mínimas Mensais”. This positively separates daily and monthly means. It does not itself define MediaDiaria0/1.

## Positive conventional discharge and mean-variant UI evidence

https://portal1.snirh.gov.br/tutorialhidro/dr/17684.png

Chapter06 “Importação de dados de vazão”, original slide17714, visually confirmed. The old Hidroweb historical export UI says “Consultar série de: Vazões (m³/s)”. The screenshot shows VAZOES.ZIP containing VAZOES.MDB being extracted into Hidro1.2/dados. This is conventional historical discharge, not telemetric discharge.

https://portal1.snirh.gov.br/tutorialhidro/dr/17945.png

Original slide17975, visually confirmed. Hidro1.2 displays “Vazões Médias (importados)” and columns “Máxima (m³/s)”, “Mínima (m³/s)”, “Média (m³/s)”. Bottom source-defined filter states **“Restrições: Média diária = Sim”**. This demonstrates mean-series identity is controlled by an explicit source field rather than inferred from sampling. It does not alone prove numeric1=Sim. No such inference is made here.

## Positive monthly header and numbered-day UI evidence

https://portal1.snirh.gov.br/tutorialhidro/dr/26407.png

Visually confirmed original slide26437 shows “Cotas Médias”, monthly Data, centimetre columns, and explicit “Restrições: Média diária = Sim”. The tutorial then opens the February1983 monthly record.

https://portal1.snirh.gov.br/tutorialhidro/dr/26441.png

Visually confirmed original slides26456/26495 show the opened Hidro1.2 form “Cotas (10200000, 02/1983, -)”, header “Data: 02/1983”, and **“Cotas Diárias (cm)”** group containing slots01–31. Slots29–31 are disabled/blank for February1983. Graph x-axis shows day numbers and month02/1983; y-axis “Cota (cm)”. This directly establishes source-owned monthly-record/day-slot UI and daily cota units. It is not a declaration that midnight spans a particular24-hour period or any timezone. Current `Data_Hora_Dado` binding still requires the dictionary/current field mapping; no timestamp statistic is inferred from the header time.

## Earlier open leads (now closed by dictionary above except current-API correspondence)

- Explicit MediaDiaria0/1 enum in Hidro dictionary/help/software schema.
- Bind the established historical conventional units to the current endpoint through explicit field correspondence and source definitions; current values remain authoritative.
- Numbered day slots and month header mapping; no daily-support/timezone inference.
- Current endpoint field correspondence must stay field-by-field: source-comparison reports modern discharge precision differs from SOAP, so this evidence does not authorize substituting SOAP values.
- Keep Bruto and Consistido as source variants, never a quality-ranking or precedence decision.

## Research paths already examined

ANA's current official manuals collection lists the two previously consulted API manuals only. Progestão indexed hidro+manual search was paginated through 280 results, identifying mostly situation-room manuals and certification reports. The public Sophia library is searchable without owner credentials through its ordinary search form; exact queries “sistema hidro”, “hidro” “manual”, Hidroweb and a systems phrase did not find the full manual. These are bounded search results, not proof that definitions do not exist.

Current Hidroweb public frontend documentation component explicitly uses `/rest/api/documento` and `/documento/download?documentos=` with portal authentication. It does not expose meanflag/unit controls in the modules examined. Do not forward modern ANA bearer tokens to the portal or infer source silence from unauthenticated denial.


## Remaining executable tests after semantics are closed

1. Use the established dictionary `MediaDiaria=1` definition; reject/route0 without silently treating07:00/17:00 records as daily means. Test both variants with real recordings.
2. Expand explicit daily slots against each source month; leap/non-leap February, month/year end, invalid day slots and published blanks/nulls need real recordings.
3. Keep simultaneous Bruto/Consistido variants separately selectable. Prove no max-consistency deduplication, averaging or fallback occurs.
4. Test source monthly header filtering with a mid-month request and month-outward acquisition. Preserve engine ownership of padding/splitting/clipping.
5. Verify conventional Cota cm→m conversion through shared convert and unchanged native m³/s discharge using current API recordings, not values transcribed from screenshots.
6. Independently author the three boundary literals from real recordings and official definitions before viewing implementation output.

No production tests were run or changed by this documentation-only worker. No claim of completed conventional support is made.

## Final conventional product contract and naming review

- Source coordinates: current HidroSerieCotas or HidroSerieVazao endpoint; monthly row `Mediadiaria` corresponding to Hidro `MediaDiaria` must equal1 for a daily-mean product.0 identifies the non-mean/instantaneous variant and is outside that product.
- Source variants: keep `Nivel_Consistencia=1` (**Bruto**) and2 (**Consistido**) distinct. Neither may silently substitute for the other. A request for one variant that finds only the other is not permission to return the other.
- Native values: `Cota_01`–`Cota_31` in centimetres; `Vazao_01`–`Vazao_31` in m³/s, bound to the corresponding Hidro fields by source-comparison evidence. Engine converts stage units only once; do not calculate means.
- Calendar: the row month is the measurement month; dayNN is dayNN of that month. For recorded current daily-mean rows the source header time is midnight. A result may preserve that native midnight **label**, but the dictionary does not establish midnight-to-midnight support, UTC, a zone, or the representativeness of that time. The product's precise24-hour day definition remains unknown, and its timezone remains unknown absent further source evidence. Do not strip or overwrite an unexpected non-midnight dailymean header without a separately evidenced rule.
- Source status vocabulary remains native judgement. Do not use status values to rank, discard, interpolate or replace published values. Preserve published blanks/nulls through the normal existing pipeline contract; do not conflate blank with zero.
- Monthly acquisition filtering and366-day caps remain empirical/API request-planning facts to test. The dictionary does not define the current HTTP filter granularity or stop convention.

**Naming review:** source-vocabulary suffixes `bruto` and `consistido` are suitable for distinct provider-product identifiers, provided each complete name also states the physical parameter and daily-mean statistic. A discharge dailymean bruto product and discharge dailymean consistido product are two choices, not two quality ranks. Use the exact Portuguese words in display descriptions, linked to native consistency codes. Do not call either “best”, “verified”, “final”, “preferred”, or “fallback”. Do not expose a generic dailymean product that silently selects one, merges them, or changes variant by availability. The same rules apply to stage. This review approves the source-partition naming semantics, not a new public selection API or any implicit precedence.
