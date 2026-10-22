# Switzerland: FOEN

[Documentation index](../README.md) · [Usage](../usage.md)

The Federal Office for the Environment (FOEN) publishes Switzerland's national
hydrological observations. `ch_foen` provides offline station and product discovery.
Observation retrieval is not available through this provider. Discovery needs no
network access or credentials.

Inspect discharge candidates and station metadata:

```python
import rivretrieve as rr

selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
candidates = rr.series(selection)
metadata = rr.metadata(selection)
```

`candidates` describes the published series known to the catalogue. `metadata`
contains the available station names, water-body names, catchment areas and elevations.
See [station metadata](../station-metadata.md) for field interpretation.
Calling `rr.fetch` raises `ObservationsUnavailableError`; it does not contact
Existenz.ch or another observation service.

The official source provides discharge, water level and water temperature through
historical products and a separate recent raw feed. Historical and recent station
coverage may differ. A station listing does not establish availability for every
quantity or period. The catalogue is an incomplete inventory: an absent association
does not establish that a source series is unavailable. Sampled timestamps do not
establish the start or end of a record.

Source units and raw series names remain distinct. Recent discharge can be published
in litres per second or cubic metres per second; water-level reference labels also
vary. Unknown physical facts do not match filters requiring an established frequency,
statistic or reference. Station numbers retain leading zeros. Missing coordinates
must not be interpreted as another station's location.

## Source information

- [Official water observations](https://data.bafu.admin.ch/dataproduct-water-observations)
- [FOEN hydrological stations](https://www.hydrodaten.admin.ch/en)
- [FOEN terms of use and source citation](https://www.hydrodaten.admin.ch/en/questions#faq-7)

FOEN states that its data can be used freely and recommends citing the source:
“Hydrology Division, Federal Office for the Environment FOEN (reference date).”
