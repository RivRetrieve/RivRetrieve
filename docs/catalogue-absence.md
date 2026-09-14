# Catalogue absence vocabulary and upstream proposal

This document defines RivRetrieve's local `rr:absence` property and drafts a proposal for
MLCommons. The proposal has not been filed. The local meaning is defined in
[`CONTEXT.md`](../CONTEXT.md); the examples are grounded in the packaged catalogue
descriptors, which `rivretrieve.describe(provider)` returns unchanged as parsed JSON-LD.

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
descriptors provide the complete examples and the literal evidence URLs. France's baseline station and station-product rows now have acquisition bindings;
unknown availability remains explicit rather than being encoded as missing acquisition. Brazil describes withheld provider, product, station and station-product
facts without claiming certification or inventing a catalogue publication date.

## Why propose this upstream?

[Croissant 1.0](https://docs.mlcommons.org/croissant/docs/croissant-spec.html) provides
file descriptions and field extraction relationships. Our use case also needs a machine
to distinguish deliberate lack of a source fact from an unestablished acquisition record.
Neither a null value nor a free-text dataset description makes that distinction at the
field where a consumer encounters it.

[MLCommons issue #1012](https://github.com/mlcommons/croissant/issues/1012) asks how to
describe known dataset biases or imbalances, using a gender imbalance as its example.
This proposal concerns the evidence behind an absent field or excluded rows. It does not
classify bias, infer representativeness, or claim that a publisher never supplies a fact
merely because RivRetrieve did not acquire it.

The proposed upstream capability is an explicit field-level absence with two distinct
states and a corresponding record-set-level exclusion count. Names in an upstream
vocabulary would be decided by MLCommons. RivRetrieve's `rr:` property remains local;
this draft does not claim that MLCommons has accepted it.

## Local evidence for the proposal

Every provider ships one descriptor beside its four catalogue tables:

| Providers | Examples to inspect |
|---|---|
| [ba_fhmzbih](../src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/croissant.json), [ch_foen](../src/rivretrieve/_internal/providers/ch_foen/catalogue/croissant.json), [cz_chmi](../src/rivretrieve/_internal/providers/cz_chmi/catalogue/croissant.json), [jp_mlit](../src/rivretrieve/_internal/providers/jp_mlit/catalogue/croissant.json), [no_nve](../src/rivretrieve/_internal/providers/no_nve/catalogue/croissant.json), [th_thaiwater](../src/rivretrieve/_internal/providers/th_thaiwater/catalogue/croissant.json), [za_dws](../src/rivretrieve/_internal/providers/za_dws/catalogue/croissant.json) | Evidenced not-published coordinate reference systems. |
| [pl_imgw](../src/rivretrieve/_internal/providers/pl_imgw/catalogue/croissant.json) | Withheld coordinate reference system; coordinates trace to the recovered GRDC CSV, while station identity also uses IMGW roster membership. |
| [fr_hubeau](../src/rivretrieve/_internal/providers/fr_hubeau/catalogue/croissant.json) | Complete baseline acquisition bindings with available and unknown availability. |
| [br_ana](../src/rivretrieve/_internal/providers/br_ana/catalogue/croissant.json) | A catalogue whose source facts remain withheld, while its verified licence can still be stated. |
| [ca_eccc](../src/rivretrieve/_internal/providers/ca_eccc/catalogue/croissant.json), [lt_lhmt](../src/rivretrieve/_internal/providers/lt_lhmt/catalogue/croissant.json), [usgs_nwis](../src/rivretrieve/_internal/providers/usgs_nwis/catalogue/croissant.json) | Source lineage and verbatim credit alongside explicit absences where recorded. |

The examples live under
[`src/rivretrieve/_internal/providers/`](../src/rivretrieve/_internal/providers/).
Their lineage originates in each provider's `provenance.json` and origin declarations;
the descriptor does not grant additional certification. Public native tables retain
commit-pinned repository identities and stay outside the wheel. Private material retains
only its digest identity and permitted verification facts, with no private download link.

Extraction and historical lineage use different relationships. A field's `subjectOf`
describes its provenance as a schema.org `CreativeWork`; `isBasedOn` identifies its
recorded acquisition inputs. A separate `citation` reference can identify corroborating
evidence, leaving the source material's requested credit text unchanged. For Poland,
the private workbook corroborates the recovered CSV; it is not established as the
historical acquisition that produced it. That limitation travels with the description.

Before filing, the maintainer can link a public released revision of these thirteen
descriptors, their reference-validator results, and the relevant provenance records. The
upstream discussion should settle how an absence value is represented in JSON-LD, how
consumers distinguish unavailable source facts from the columns carrying their markers, and
whether exclusion counts belong directly on a record set. Filing and upstream vocabulary
changes remain separate maintainer decisions.
