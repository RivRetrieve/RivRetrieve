# Source terms finding — br_ana

Agency: ANA Hidroweb, National Water and Sanitation Agency
Country: Brazil
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

Only **app-scoped** terms were found; the data licence proper was not located. Treat the
first two as probably wrong and the third as the likeliest.

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos | Plano de Dados Abertos da ANA | pt-BR | ANA's institutional open-data page — **likeliest home of an agency-level data policy. Start here** |
| https://dadosabertos.ana.gov.br/ | ANA open-data portal (ArcGIS Hub) | pt-BR | Per-dataset item pages may carry licence fields |
| https://www.gov.br/ana/.../manuais/manual-hidrowebservice_publica.pdf | Manual do Serviço de Disponibilização de Dados Hidrológicos — API HidroWebservice | pt-BR | **PDF.** API manuals often state use conditions |
| https://www.snirh.gov.br/hidroweb-mobile/termo | ANA - Hidroweb | pt-BR | **JS-only.** Scoped to the Hidroweb *mobile app* — probably not the data licence |
| https://www.gov.br/ana/.../11-politica-de-privacidade-do-aplicativo-hidroweb-da-ana | Política de Privacidade do Aplicativo Hidroweb | pt-BR | Companion privacy policy; also app-scoped |

The Hidroweb data portal itself (`snirh.gov.br/hidroweb`) is JS-only and carries no terms page.

## licence

- Page URL: https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T09:30:30+00:00
- Language: pt-BR
- Agency publishes nothing: no

```text
Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle.
```

## citation

- Page URL: https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos
- Recording: licence-1
- Retrieved (UTC): 2026-08-21T09:30:30+00:00
- Language: pt-BR
- Agency publishes nothing: yes

ANA publishes no citation request for the hydrometric data RivRetrieve reads. It does publish
one for **some** of its datasets, in machine-readable metadata rather than on any web page, and
not for this one — set out below and recorded as `citation-1`.

```text
```

## Notes

### What we actually fetch, and why the app-scoped leads are irrelevant

`br_ana` reads two endpoints, both on ANA's own host and both behind OAuth credentials
(`ANA_IDENTIFICADOR` / `ANA_SENHA`, per `provider.json`):

```
https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1
https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroInventarioEstacoes/v1
```

The candidate table's first two leads were the Hidroweb **mobile app** terms and the mobile app
privacy policy. Neither is in our path and neither is recorded.

### The licence statement, and its scope

The quote in the licence slot is ANA's own statement about its open data, on its own domain.
Note what it is: a description of how ANA's open data is made available — freely, to all of
society, without restriction of licences, patents or control mechanisms. **It names no licence
instrument**, unlike Czechia's CC BY or Lithuania's CC BY-SA.

A scope question follows and is left open: the hydrowebservice endpoints we read require
registration and OAuth credentials, which is a form of access control, and the sentence above
speaks of data available *"sem … mecanismos de controle"*. Whether the hydrowebservice data is
"dados abertos" in the sense of that sentence is not decided here.

### A separate statement on the same page, about the site and not the data

```text
Todo o conteúdo deste site está publicado sob a licença Creative Commons Atribuição-SemDerivações 3.0 Não Adaptada.
```

That is **CC BY-ND 3.0** — Attribution-NoDerivatives — and it is scoped to *"todo o conteúdo
deste site"*, the site's content. It is not the data licence and is quoted here so it is not
mistaken for one. It is the most restrictive licence instrument named anywhere in this survey,
which is exactly why its scope matters.

### ANA's portal does declare a licence — in metadata, for some datasets

`dadosabertos.ana.gov.br` is JavaScript-only in the browser, but it publishes a **DCAT-US 1.1
feed**, recorded as `citation-1` (1,167,818 bytes, 345 datasets, every one prefixed `HIDRO`).
Every dataset carries a `license` field. Across the 345:

| `license` value | Datasets |
|---|---|
| *(empty string)* | 268 |
| *"É permitida a reprodução de dados e de informações, desde que citada a fonte."* (some entries wrapped in HTML markup) | 75 |
| `creativecommons.org/publicdomain/zero/1.0` (CC0) | 2 |

So ANA does state, for 75 of its datasets, that reproduction of data and information is
permitted provided the source is cited — a licence and a citation condition in one sentence.
Two further datasets are declared CC0.

**But not for ours.** The dataset matching what RivRetrieve reads,
*"HIDRO - Inventário pluviométrico/fluviométrico atualizado"*, carries an **empty** `license`
field. That is why the citation slot records nothing published for this data rather than
borrowing another dataset's wording.

**The checker cannot verify any of this.** `citation-1` is `application/json`, so `check.py`
would refuse to machine-check a quote taken from it. The figures above were produced by parsing
the recorded feed, and anyone can re-run that against the recording.

### Also checked and not relevant

- `gov.br/ana/pt-br/politica-de-uso` (`licence-2`) — recorded and read. It is the **Banco de
  Imagens** policy, governing photographs: crediting is required as *"Nome do Autor / Banco de
  Imagens ANA"*, and modification and sale are prohibited. **It is about images, not data**, and
  is recorded so nobody later mistakes an image policy for a data licence.
- `gov.br/ana/pt-br/termos-de-uso` — linked twice from the open-data page as *"Termos de Uso"*
  and *"Termo de Uso e Aviso de Privacidade"*, and it **returns 404**. A dead link on ANA's own
  site, the same shape as the dead `/page/mentions-legales` on `fr_hubeau`.
- The *Plano de Dados Abertos 2025-2027* — a 96-page, 3 MB PDF, read. It is a governance plan.
  It restates the eight open-data principles, including *"Livres de licenças"*, and requires
  each published dataset to carry a *"Licença de Uso"* field per the Portal Brasileiro de Dados
  Abertos standard — which is the field found empty for our dataset above. It states no licence
  for ANA's hydrological data. Not recorded, since it establishes nothing about terms.
- `dados.gov.br` — the federal portal. **JavaScript-only**, and its API returns HTTP 401 without
  a key, so per-dataset licence fields there could not be read. ANA's own DCAT feed was used
  instead, which is the agency's own publication rather than a portal describing it.
- `www.ana.gov.br/hidrowebservice/` — 404. There is no human-readable landing page for the
  service we call.

### Access notes

- `licence-1` and `licence-2` recorded with `record.py`; the DCAT feed likewise.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
