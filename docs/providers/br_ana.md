# Brazil: ANA

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `br_ana` |
| Country | Brazil |
| Published by | Agência Nacional de Águas e Saneamento Básico (ANA) |
| Quantities | Discharge and stage |
| Stations in the catalogue | 17,914. Availability depends on quantity, source selection and period |
| Credentials | Required for retrieval: `ANA_IDENTIFICADOR`, `ANA_SENHA` |
| Terms stated by ANA | Open data made freely available; see [Terms and citation](#terms-and-citation) |
| Agency documentation | [HidroWebService](https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html), [Hidroweb](https://www.snirh.gov.br/hidroweb/) |

With [credentials configured](#credentials), retrieve three days of published daily mean
discharge at station `15400000`, choosing ANA's `consistido` consistency level:

```python
import rivretrieve as rr

selection = rr.find(
    provider="br_ana",
    station="15400000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
consistido = rr.pick(selection, variant="consistido")

result = rr.fetch(
    consistido, start="2020-01-10", end="2020-01-12", cache="bypass"
)

preview = result.data.select("time", "time_zone", "value", "unit")
print(preview.write_csv(), end="")

print(result.data.height)
print(sorted({(issue.severity, issue.code) for issue in result.issues}))
```

Output:

```text
time,time_zone,value,unit
2020-01-10T00:00:00.000000,unknown,31687.982,m3/s
2020-01-11T00:00:00.000000,unknown,31789.021,m3/s
2020-01-12T00:00:00.000000,unknown,31553.52,m3/s
3
[('info', 'provenance.citation_not_established'), ('info', 'source_status')]
```

The three rows contain source-published daily means in m³/s. Both endpoint dates
are included. RivRetrieve does not calculate these means from telemetry.
`cache="bypass"` requests the source rather than cached observations. The example
prints each distinct issue severity and code, rather than repeating the daily
status notices. `source_status` reports ANA's source metadata without a quality
judgement. The other notice means that RivRetrieve has not established a standard
citation. Neither notice means that this observation request failed.

The time zone is `unknown`; midnight labels do not establish the hours covered by
each mean. Source values can change, so a later request need not reproduce this
output exactly. Run the following examples in the same session. See
[Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

ANA, Brazil's national water and sanitation agency, coordinates the
*Rede Hidrometeorológica Nacional* (unofficially, National Hydrometeorological
Network). Public and private organisations operate its stations under ANA's
supervision. Specialist staff and field observers collect the measurements;
ANA standardizes measurement procedures and equipment.

ANA makes hydrological records available through Hidroweb. RivRetrieve reads
its programming interface, HidroWebService. ANA's role as publisher does not
identify the original producer of every measurement.

## Credentials

Catalogue selection works without credentials. Observation retrieval requires an
ANA identifier and password, issued on request.

ANA's [Solicite Acesso API](https://www.snirh.gov.br/hidroweb/acesso-api) page asks
for an email to **telemetria@ana.gov.br**, with the subject
*"Solicitação de acesso à API"*, a short explanation of the intended use, and:

- the name of the user or institution;
- a CPF or CNPJ, used as the username;
- an email address to receive the password.

ANA reviews the request and may ask for more information. Use the issued
*Identificador* and *Senha* (unofficially, identifier and password). The identifier
is not the account email address.

Set `ANA_IDENTIFICADOR` and `ANA_SENHA` in the process environment or in a private
`.env` file in the directory from which Python runs. Process variables take
precedence, including blank values. Keep credentials out of code, version control,
logs and shared files. See [credential setup](../usage.md#supplied-credentials) for details.

`rr.providers()` reports `ready` when both credentials are present locally. It
does not authenticate with ANA or prove that the credentials are accepted.

## What you can retrieve

| Quantity filter | Source selection / `variant` | Published statistic | Source unit | Returned unit |
|---|---|---|---|---|
| `discharge` | `bruto`, `consistido` | Daily mean | m³/s | m³/s |
| `stage` | `bruto`, `consistido` | Daily mean | cm | m |
| `discharge` | `Vazao_Adotada` | Not established | m³/s | m³/s |
| `stage` | `Cota_Adotada` | Not established | cm | m |

RivRetrieve divides stage values by 100 to convert centimetres to metres.
Discharge is already in m³/s. Water temperature is not supported.

The adopted telemetry fields retain ANA's names. Their measurement timestamps
are established, but their sampling frequency and statistic are not. Do not add
`frequency="daily"` or `statistic="instantaneous"` when selecting these fields:
those filters require established physical facts.

```python
telemetry = rr.pick(
    rr.find(provider="br_ana", station="15400000", quantity="discharge"),
    variant="Vazao_Adotada",
)

print(rr.series(telemetry).select("variant", "frequency", "statistic").rows())
```

Output:

```text
[('Vazao_Adotada', None, None)]
```

This selects a catalogue candidate; it does not retrieve telemetry observations.
The catalogue lists six candidates per station. A station being listed does not
guarantee observations for every quantity, source selection or requested period.
The successful daily example establishes availability only for that station,
selection and period, not continuous history or national coverage.

## Daily consistency levels: bruto and consistido

ANA identifies daily records by *NivelConsistencia*: level 1, *Bruto*, and level 2,
*Consistido*. Unofficially, these mean raw and consistency-checked. They are source
categories, not a quality ranking assigned by RivRetrieve.

Inspect the daily discharge candidates selected above:

```python
print(
    rr.series(selection)
    .select("station_id", "variant", "frequency", "statistic")
    .rows()
)
```

Output:

```text
[('15400000', 'bruto', 'daily', 'mean'), ('15400000', 'consistido', 'daily', 'mean')]
```

`rr.pick(selection, variant="bruto")` selects the other level. Fetching `selection`
without narrowing it requests both and keeps their source identities separate:

```python
both_result = rr.fetch(
    selection, start="2020-01-10", end="2020-01-12", cache="bypass"
)

print(rr.series(both_result).select("variant").rows())
print(both_result.data.height, both_result.data["series_id"].n_unique())
print(sorted({(issue.severity, issue.code) for issue in both_result.issues}))
```

Output:

```text
[('bruto',), ('consistido',)]
3 1
[('info', 'provenance.citation_not_established'), ('info', 'source_status'), ('warning', 'source.unresolved_inventory')]
```

The response supplied three `consistido` observations and no `bruto` observations.
Both identities remain in the series inspection table, but only one has returned
rows. `source.unresolved_inventory` means the response did not establish availability
for the requested `bruto` level. The default issue policy also emits a Python warning
with that explanation. This is a partial result, not evidence that `bruto` is absent
from the station's entire history.

Keep `series_id` when comparing records: station and date alone need not identify
a single value. RivRetrieve neither averages the consistency levels nor selects a
preferred one. An explicit choice does not fall back to the other level. If ANA's
response does not publish the requested level, its availability remains unresolved,
and an issue reports that limitation rather than substituting observations.

## Time and source status

Returned `time` contains source clock labels accompanied by `time_zone="unknown"`.
Read those columns together. RivRetrieve has not established the source time zone
or the interval covered by a daily mean. It does not infer either from station
location or the midnight representation of a daily date.

ANA also supplies status fields for observations. RivRetrieve retains their source
values in informational `source_status` issues without interpreting them as a
quality judgement. These statuses are distinct from the selectable daily consistency
levels. Status notices can refer to the full monthly response, including dates
outside the requested period. They are not per-row quality flags in the returned
observation table.

A blank or null daily value remains a row with `value=null`. An absent source
record remains absent, and a failed request is reported separately in issues.
RivRetrieve does not fill gaps. Check [issues](../usage.md#issues) before interpreting
empty or partial results.

## Terms and citation

ANA's [open data page](https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos) states:

> Os dados abertos são disponibilizados livremente para a utilização de toda a sociedade, sem
> restrição de licenças, patentes ou mecanismos de controle.

In English, unofficially: open data are made freely available for use by all of
society, without restriction of licences, patents or control mechanisms.

This is ANA's institutional open-data statement. No formatted citation for these
observations was identified in the sources checked for this page. RivRetrieve
reports that missing citation as an informational issue. Identify ANA, Hidroweb,
the stations and selections used, and the retrieval date in an attribution suitable
for the study; this is practical guidance, not an ANA-prescribed citation format.
Personal credentials must remain private regardless of the data-use terms.

## Sources

| Source | Check and limitation |
|---|---|
| [ANA: Orientações e manuais](https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais) | Institutional responsibilities and manual links checked 2026-09-22 |
| [ANA: Dados abertos](https://www.gov.br/ana/pt-br/acesso-a-informacao/dados-abertos) | Open-data statement checked 2026-09-22 |
| [Hidroweb: Solicite Acesso API](https://www.snirh.gov.br/hidroweb/acesso-api) | Access instructions checked 2026-09-22 |
| [HidroWebService OpenAPI](https://www.ana.gov.br/hidrowebservice/api-docs) | Service and authentication definitions checked 2026-09-22 |
| Hidro 1.4 dictionary, Appendix A, pages 21–24 | Retained historical definitions of daily means, units and consistency levels; not freshly downloaded |
| HidroWebService manual, pages 11–12 | Retained historical telemetry field definitions; not freshly downloaded |

The station count describes the packaged catalogue. Example observations were
retrieved on 2026-09-22. The [verification record](../verification/brazil-provider/README.md)
retains commands, source evidence and the limits of these checks.
