# Source terms finding — ch_foen

Agency: Federal Office for the Environment FOEN/BAFU
Country: Switzerland
Status: complete

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

**This one has two layers and you must record them separately.** RivRetrieve reaches Swiss
data through `existenz.ch`, which is a private individual's unofficial service, not the
agency. The operator's conditions and BAFU's underlying conditions both apply. Do not merge
them into one answer; put the agency's in the fields and the intermediary's in Notes.

**BAFU / FOEN — the agency:**

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://www.hydrodaten.admin.ch/de/fragen | FAQ — BAFU Hydrologische Daten und Vorhersagen | de | Has an entry headed *Nutzungsbedingungen und Quellenangabe* — terms **and** attribution in one item. **Start here** |
| https://www.bafu.admin.ch/dam/de/sd-web/5NAitqNKub6m/allgemeine_bedingungenfuerdasherunterladenaktuellerhydrologische.pdf | Liefer- und Nutzungsbedingungen hydrologische Daten BAFU | de | **PDF.** Linked from that FAQ entry as the full conditions document — the primary artefact |
| https://www.hydrodaten.admin.ch/de/aktuelle-hydrologische-daten-beziehen | Aktuelle hydrologische Daten beziehen | de | Download page; conditions often restated at point of access |
| https://www.admin.ch/gov/de/start/rechtliches.html | Rechtliches | de | Federal legal page, linked from the hydrodaten footer |

FR/IT/EN variants exist under `/fr/`, `/it/`, `/en/`.

**existenz.ch — the intermediary:**

| URL | Title | Lang | Why a candidate |
|---|---|---|---|
| https://api.existenz.ch/ | Existenz.ch Data APIs | en+de | Conditions live inline on the page; the hydro anchor `#/hydro` states an attribution requirement pointing back to BAFU. There is no dedicated `/terms` page |
| https://www.existenz.ch/ | existenz.ch | de | **Not found** — subdomain links and a contact address only |

## licence

- Page URL: https://www.hydrodaten.admin.ch/de/fragen
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T13:12:57+00:00
- Language: de
- Agency publishes nothing: no

```text
Die Daten können frei genutzt werden. Die Angabe der Quelle wird empfohlen.
```

## citation

- Page URL: https://www.hydrodaten.admin.ch/de/fragen
- Recording: licence-1
- Retrieved (UTC): 2026-08-20T13:12:57+00:00
- Language: de
- Agency publishes nothing: no

```text
Vorschlag für die Quellenangabe: Daten Oberflächengewässer: Abteilung Hydrologie, Bundesamt für Umwelt BAFU (Bezugsdatum).
```

## Notes

Both slots come from one BAFU page: the hydrodaten FAQ entry headed *Nutzungsbedingungen und
Quellenangabe*, which states the terms and the suggested attribution together. Per the folder's
instruction, the **agency's** words are in the slots and the **intermediary's** are kept
separate, below. Neither is interpreted here.

The citation quote stops at the surface-water form, which is what RivRetrieve serves. The same
FAQ entry continues with a second form for groundwater (*Grundwasserdaten: Nationale
Grundwasserbeobachtung NAQUA…*), present in the recording and not quoted because it does not
apply to river gauges.

### We never contact BAFU. Every byte comes through a third party.

`ch_foen` has exactly two endpoints and both are on `api.existenz.ch`:

```
https://api.existenz.ch/apiv1/hydro/locations
https://api.existenz.ch/#hydro
```

There is no request to `hydrodaten.admin.ch`, or to any `admin.ch` host, anywhere in the
provider. The BAFU terms quoted above govern the data's origin; the service RivRetrieve
actually calls is operated by someone else. Both layers are recorded and neither is ranked.

### The intermediary's own statements, recorded as `licence-4`

`api.existenz.ch` is a private, self-described unofficial service. Its conditions sit inline on
the page; there is no dedicated terms page. Four statements bear on our use, verbatim:

```text
These APIs with weather and water data for Switzerland are free for public and non-commercial use, lovingly handcrafted by Christian Studer (Bureau für digitale Existenz).
```

```text
These APIs are unofficial. There is no guarantee of availability or top performance. They are actively monitored though. Additional licencing restrictions may apply by the original data owner (For example MeteoSwiss or the BAFU).
```

```text
BAFU data needs to be credited and linked to the BAFU.
```

```text
For statistical purposes add &app={your app name} and optionally add &version={your app version} to all of your requests.
```

Two observations, recorded as facts and not as conclusions:

- The intermediary states its APIs are for **public and non-commercial use**. The BAFU page
  quoted in the licence slot states the data may be freely used and does not attach that
  condition. The two statements are not the same, and they attach to two different things —
  the data and the service carrying it. Which applies to a given use is not settled here.
- The intermediary asks callers to add `&app=` and optionally `&version=` to every request.
  **RivRetrieve sends neither.** No `app` or `version` parameter appears anywhere in the
  `ch_foen` provider — checked across `config.py`, `origins.py`, `generate_catalogue.py` and
  `bulk.py`.

### The other recordings

| Recording | Page | Note |
|---|---|---|
| `licence-2` | *Liefer- und Nutzungsbedingungen hydrologische Daten BAFU* | **PDF**, 104,316 bytes, linked from the FAQ entry as the fuller conditions document. The checker cannot machine-verify a quote inside a PDF, so nothing from it is quoted — better an unquoted document in evidence than a transcription nobody can check |
| `licence-3` | *Aktuelle hydrologische Daten beziehen* | The download page named by the FAQ |
| `licence-5` | admin.ch *Rechtliches* | Federal legal page linked from the hydrodaten footer; redirects to `https://www.admin.ch/de/rechtliches` |

### Access notes

- All five recorded with `record.py` in one pass. No login, no key, no JavaScript needed.
- `admin.ch` hosts need `SSL_CERT_FILE` pointed at the `certifi` bundle under Python's default
  certificate store, as for `ca_eccc`.
- FR, IT and EN variants of the hydrodaten pages exist under `/fr/`, `/it/`, `/en/`. Only the
  German were recorded. The `api.existenz.ch` page carries English and German inline on the
  same page; the English wording is quoted above.
- The shipped `provider.json` carries `"license": null` and `"citation": null`.
