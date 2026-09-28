# Brazil provider source research

Checked 2026-09-22T20:26:32.592947+00:00. Read-only research for vision `planning/visions/2026-09-22-brazil-provider-documentation-review.md`, PR #276. Repository baseline supplied by root: `19b4514`. Read the complete vision, `docs/AGENTS.md`, original `origin/docs/provider-brazil:docs/providers/br_ana.md`, and `docs/provider_ports/br_ana.md`. No production/docs changes, checkout, owner credential access, or authenticated ANA observation requests.

## Fresh authoritative findings

### Institutional responsibility

URL: https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais

HTTP 200; actual main content checked, not just a search snippet. ANA says water monitoring in Brazil is performed in large part by the **Rede Hidrometeorológica Nacional**, coordinated by ANA. Thousands of stations are operated by diverse public and private entities under ANA's direct supervision. Specialist staff and field observers collect the data; ANA standardizes measurement procedures and equipment.

Safe introduction: “ANA coordinates Brazil's Rede Hidrometeorológica Nacional. Public and private organisations operate its stations under ANA's supervision, with specialist staff and field observers collecting the measurements. ANA makes hydrological records available through Hidroweb and HidroWebService.” Do not imply ANA itself measures every station, or equate the complete RivRetrieve inventory with stations operated directly by ANA. This check did not establish an exhaustive list of operators or station-specific measurement producers.

The agency's monitoring landing page, https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico (200), links Hidroweb and live hydrological data separately. Its `/hidroweb` child redirects to https://www.snirh.gov.br/hidroweb/ (200 JS shell). The official API OpenAPI below supplies publication/service identity. The Hidro-Telemetria landing page says its purpose is acquiring, qualifying and managing near-real-time hydrometeorological data in SNIRH and recommends Hidroweb for historical-series download.

### API access guidance

Reader link: https://www.snirh.gov.br/hidroweb/acesso-api

200 JS application shell. Fresh content verification followed its public runtime route mapping to the access-page chunk: https://www.snirh.gov.br/hidroweb/8.52b1c33f058889fa1330.js (200). Extracted only its page-description string; did not execute JS or use credentials. Exact decoded page text:

> Os usuários que desejam acessar os dados e informações do HidroWeb de forma automatizada, utilizando API, devem encaminhar um email para telemetria@ana.gov.br , com o assunto “ Solicitação de acesso à API ”. No corpo do email, inclua uma breve explicação (em poucas linhas) sobre a motivação da solicitação e forneça as seguintes informações para o cadastro: Nome do usuário ou instituição CPF ou CNPJ (para ser utilizado como usuário) Endereço de e-mail (será utilizado para o recebimento da senha de acesso) Após o recebimento do e-mail nossa equipe irá avaliar sua solicitação e, caso necessário, entrar em contato para solicitar mais informações.

Thus preserve email `telemetria@ana.gov.br`, subject `Solicitação de acesso à API`, short motivation, name of user/institution, CPF/CNPJ used as username, and email used to receive the password. ANA reviews requests and may ask for more information. **The original PR's parenthetical “if you are Brazilian” is not in the checked guidance.** Do not invent a foreign-applicant procedure. Say applicants without CPF/CNPJ should ask ANA what identifier to use, if useful, clearly as practical advice rather than an established alternative process.

Fresh OpenAPI documents authentication headers `Identificador` (“IDENTIFICADOR/USUÁRIO”) and `Senha` (“SENHA”). This supports using the supplied identifier, not substituting email.

The historical password-reset URL https://www.snirh.gov.br/hidrotelemetria/Login2.aspx responded 200 after redirect to https://www.snirh.gov.br/hidrotelemetria/Default.html. The obtained page was a system/cookie introduction, not verified password-reset instructions. Do not present reset functionality as freshly verified.

### Current service links

- https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html : 200 Swagger application shell.
- https://www.ana.gov.br/hidrowebservice/swagger-ui.html#/ : redirects to the above index page, 200.
- https://www.ana.gov.br/hidrowebservice/api-docs : 200; parsed OpenAPI title “Hidro Webservice”, description “API para Consulta Hidro Webservice - REST API Documentation”. Includes current conventional `HidroSerieCotas/v1` and `HidroSerieVazao/v1`, adopted telemetry v1/v2 and authentication paths. Conventional summaries explicitly say stations are conventional, manually collected (“estações convencionais (coleta manual)”). API definitions confirm a service exists, not nationwide observation availability.
- Official manuals index above currently links https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf under “Manual do Serviço de Disponibilização de Dados Hidrológicos - API HidroWebservice”, dated 20/02/2026. Index/link freshly checked; PDF content was not re-downloaded in this research.

### Terms and citation

URL: https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos

HTTP 200, substantive content freshly checked. Exact statement:

> Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem restrição de licenças, patentes ou mecanismos de controle.

Unofficial translation: “Open data are made freely available for use by all of society, without restriction of licences, patents or control mechanisms.” Keep this as **ANA's institutional open-data statement**, not a newly inferred dataset-specific licence or legal conclusion. The page also has a generic website-content Creative Commons footer; do not collapse these into one dataset-specific licence.

No formatted hydrological-data citation was found in the substantive open-data page, the access-guidance text, the checked monitoring/manuals index, or OpenAPI metadata. This bounded check does **not** prove ANA has no citation instructions elsewhere. Prefer “The sources linked here do not specify a formatted citation for these series,” or omit a negative claim and give RivRetrieve's own practical recommendation: identify ANA/Hidroweb, station, quantity, consistency level/source selection, dates, and access date. Label any suggested citation as a recommendation, not an ANA mandate. Do not cite catalogue provenance as if it establishes observation licensing.

## Retained historical definitions, not fresh content checks

Read `tests/recordings/br_ana/daily-definitions-report.md`, `hidro-1.4-conventional-dictionary-derived.json`, and `hidro-extraction-manifest.json`.

Authoritative underlying source: Hidro Build1.4.0.81 distribution, “Hidro 1.4 - Novidades do Sistema.pdf”, Appendix A. Source PDF SHA-256 `d098fe733740299c25ef3fc33ac7e96d6b21ff01925150d6b1d74791914e24f8`. Historical source URL: https://www.snirh.gov.br/portal/snirh-1/sistemas/gestao-e-analise-de-dados-hidrologicos/instalador-hidro-build-1-4-0-81.zip . The installer/PDF was not downloaded or executed in this check.

Retained derived dictionary pages 21–24 establish:

- `NivelConsistencia`: `1 = Bruto`, `2 = Consistido`; description “Indica o nível de consistência do registro”. Keep Portuguese words as source states. “Raw” and “checked for consistency” are useful **unofficial translations**, not quality classes. Avoid “as recorded” if it implies untouched instrument values or “reviewed” if it implies a specific undocumented review process.
- `MediaDiaria`: 0 “Não”, 1 “Sim”; indicates a daily mean versus an instantaneous measurement.
- `Data`: measurement month/year. `Cota01..31`: stage for each day in cm. `Vazao01..31`: discharge for each day in m3/s.
- The old Hidro 1.0 dictionary uses different consistency numbers. Do not cite it for current 1/2 mapping.
- Consistency levels remain distinct source records. Source status vocabulary is not a generic quality ranking. These definitions alone do not establish automatic preference, substitution, or equality between levels.

Retained telemetry manual excerpt (`tests/recordings/br_ana/manual-pages11-12.txt`) and maintainer port establish adopted values and measurement timestamps. They do not establish a zone or temporal support. Do not say “ANA never documents a time zone”; say “RivRetrieve reports the time zone and daily temporal support as unknown for these series.” The parent must check exact public output and implementation before publishing behavior claims.

## Access and evidence limits

- Serper web search was unavailable (no configured key); all findings above use direct authoritative HTTP responses or explicitly historical repository evidence.
- Hidroweb presentation content via the public-app API `/hidroweb/rest/api/pagina/1` returned 401 without authentication. No authentication attempted. A guessed `/hidroweb/rest/api/documento/acesso-api` route also returned 401 and supplies no access-policy evidence. The access-page content was successfully obtained independently from its routed public page-description string.
- Ordinary 200 shells are distinguished from actual content checks. No nationwide observations or live public Python snippets were checked in this assignment.
- Public application bundles unexpectedly contained credential-like configuration fields. They were not used and are excluded from this retained record. Only bounded access-guidance prose is retained.
