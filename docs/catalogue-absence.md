# Catalogue absence vocabulary

RivRetrieve's local `rr:absence` property records why catalogue information is unavailable.
The local meaning is defined in [`CONTEXT.md`](../CONTEXT.md). The examples below come
from the packaged catalogue descriptors, which `rivretrieve.describe(provider)` returns
unchanged as parsed JSON-LD.

## Absence

Namespace: `https://github.com/RivRetrieve/RivRetrieve/blob/main/docs/catalogue-absence.md#`.
The property `rr:absence` expands to this document's `#absence` anchor. The URL becomes
publicly readable when the repository becomes public; descriptor readers do not need to
dereference it. This work does not change the repository's visibility.

`rr:absence` describes deliberately unavailable catalogue facts. It is the only local
extension property. Its JSON value has a named `kind` and the evidence for that kind:

| Placement | Kind | Required information | Meaning |
|---|---|---|---|
| Field | `not_published` | `evidence`: the source documentation URL | The source does not publish this fact. |
| Field | `withheld` | `reason`: the recorded reason | RivRetrieve has not established the acquisition record for this fact. |
| Record set | `withheld` | `reason`; `rowCount` for recorded row identities, or `fields` for withheld columns | Recorded rows or named source facts were deliberately excluded. An unknown population is not reported as zero. |

A field's `source` locates the column in the packaged file, including a column of nulls
or a column in an empty table. `rr:absence` can accompany that extraction source: it
explains the unavailable source fact, without claiming that a file location establishes
the fact. A null cell or an empty response does not establish source silence.
A not-published assertion requires the evidence already
accepted by the origin gate; a withheld assertion requires an explicit provenance record.
The current withholding reason is `no_acquisition_record_established`. These are facts
about what is known, with no assessment of the source's quality or its terms of use.

The JSON-LD context declares `rr:absence` as `{"@id": "rr:absence", "@type": "@json"}`.
Its members form a JSON literal, rather than additional RDF vocabulary properties.

For example, the Swiss FOEN station coordinate reference system is not published:

```json
{
  "@id": "stations/crs",
  "source": {"fileObject": {"@id": "stations.parquet"}, "extract": {"column": "crs"}},
  "rr:absence": {
    "kind": "not_published",
    "evidence": "https://api.existenz.ch/#hydro"
  }
}
```

Poland's coordinate reference system has a different reason for being unavailable:

```json
{
  "@id": "stations/crs",
  "source": {"fileObject": {"@id": "stations.parquet"}, "extract": {"column": "crs"}},
  "rr:absence": {
    "kind": "withheld",
    "reason": "no_acquisition_record_established"
  }
}
```

These excerpts show the property shape, not complete Croissant documents. The packaged
descriptors provide the complete examples and the literal evidence URLs. Each French service retains its own station acquisition bindings.
Unchecked station-product pairs remain selectable with unknown availability. Brazil's certified inventory and six internal access routes retain unknown availability where no
exact station/variant observations were acquired. Unestablished CRS, citation and published
record bounds remain explicit absences rather than inferred facts.

## Upstream discussion

[MLCommons Croissant issue #1056](https://github.com/mlcommons/croissant/issues/1056)
raises the need to distinguish reasons for missing information. `rr:absence` remains a
RivRetrieve extension; it is not part of the Croissant standard.
