# Brazil — ANA

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `br_ana` |
| Country | Brazil |
| Published by | Agência Nacional de Águas e Saneamento Básico (ANA) |
| Variables | Discharge, stage |
| Stations in the catalogue | 17,914 |
| Credentials | Required: `ANA_IDENTIFICADOR`, `ANA_SENHA` |
| Terms stated by ANA | Open data, without licences, patents or control mechanisms |
| Agency documentation | [HidroWebService](https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html), [Hidroweb portal](https://www.snirh.gov.br/hidroweb/) |

```python
import rivretrieve as rr

selection = rr.find(provider="br_ana", product="discharge_daily_mean_consistido")
selection = rr.pick(selection, station="15400000")
result = rr.fetch(selection, start="2020-01-01", end="2020-12-31")
```

## Who measures, and who publishes

ANA, the national water and sanitation agency, maintains Brazil's hydrometric network with
operating partners across the country and publishes the record through Hidroweb and its
programming interface, HidroWebService. RivRetrieve reads that interface.

## Credentials

Brazil is one of two providers that require credentials, and ANA issues them on request.

Its [Solicite Acesso API](https://www.snirh.gov.br/hidroweb/acesso-api) page asks you to email
**telemetria@ana.gov.br** with the subject *"Solicitação de acesso à API"*, a few lines explaining
why you need access, and three details for the registration:

- the name of the user or institution;
- a CPF or CNPJ (if you are Brazilian), which becomes your username;
- an email address, to which the password is sent.

ANA reviews the request and may come back for more information. What you receive is an
*Identificador* and a *Senha*, which RivRetrieve reads from the environment:

```bash
export ANA_IDENTIFICADOR="your-identifier"
export ANA_SENHA="your-password"
```

`rr.providers()` shows `ready` once both are set, and `missing ANA_IDENTIFICADOR, ANA_SENHA`
before that. Catalogue browsing works without them; only retrieval needs them.

## Raw and reviewed: bruto and consistido

Brazil publishes each daily series at a **consistency level**, and this is the thing to understand
before using the data. ANA's data model marks a series as level 1, *bruto*, or level 2,
*consistido*: raw as recorded, or reviewed.

RivRetrieve keeps them apart as separate products, so you choose which one you are analysing:

| Product | Consistency level | Unit |
|---|---|---|
| `discharge_daily_mean_bruto` | 1, *bruto* | m³/s |
| `discharge_daily_mean_consistido` | 2, *consistido* | m³/s |
| `stage_daily_mean_bruto` | 1, *bruto* | m |
| `stage_daily_mean_consistido` | 2, *consistido* | m |

RivRetrieve never substitutes one level for the other, never averages them, and offers no generic
daily product that might silently switch between them. If a station has no series at the level you
asked for, you get no rows for it rather than the other level. The two can genuinely differ for
the same day at the same station.

## What you can retrieve

| Product | Source series | Unit published | Unit delivered | Stations listed |
|---|---|---|---|---:|
| `discharge_daily_mean_bruto` | `HidroSerieVazao`, level 1 | m³/s | m³/s | 17,914 |
| `discharge_daily_mean_consistido` | `HidroSerieVazao`, level 2 | m³/s | m³/s | 17,914 |
| `stage_daily_mean_bruto` | `HidroSerieCotas`, level 1 | cm | m | 17,914 |
| `stage_daily_mean_consistido` | `HidroSerieCotas`, level 2 | cm | m | 17,914 |
| `discharge_instantaneous` | Adopted telemetry, `Vazao_Adotada` | m³/s | m³/s | 17,914 |
| `stage_instantaneous` | Adopted telemetry, `Cota_Adotada` | cm | m | 17,914 |

The instantaneous products come from the telemetry network and carry the values ANA has adopted
for each station.

Availability is `unknown` for nearly every station and product. The catalogue records why: being
listed in the fluviometric inventory does not establish that a given station serves a given
product through the interface, and per-station evidence was not collected. Six series at station
`15400000` are the exception, where the retained response did contain measurements.

## Time

All values come back with `time_zone` `unknown`. ANA records the measurement date, and for
telemetry a measurement time, but does not state the zone; nor does it state the interval a daily
mean covers. RivRetrieve does not fill either in.

## Terms

ANA's [open data page](https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos) states:

> Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem
> restrição de licenças, patentes ou mecanismos de controle.

In English, unofficially: open data are made freely available for use by all of society, without
restriction of licences, patents or control mechanisms.

ANA publishes no formatted citation for the data. Credentials are personal and must not be shared,
committed or published, whatever the terms say about the data themselves.

## Sources

| Page | Retrieved |
|---|---|
| [ANA — Dados abertos](https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos) | 2026-09-19 |
| [HidroWebService](https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html) | 2026-09-19 |
| [Hidroweb portal](https://www.snirh.gov.br/hidroweb/) | 2026-09-19 |
| [Hidroweb — Solicite Acesso API](https://www.snirh.gov.br/hidroweb/acesso-api) | 2026-09-19 |

Station counts come from the packaged catalogue. The consistency levels and field definitions
follow ANA's Hidro 1.4 data dictionary, as recorded when the provider was built.
