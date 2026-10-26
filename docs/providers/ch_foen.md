# Switzerland: FOEN

[Documentation index](../README.md) · [Usage](../usage.md)

The Federal Office for the Environment (FOEN) publishes Switzerland's national
hydrological observations. `ch_foen` provides offline station and product discovery
and retrieves observations from the official BAFU API. Access needs no credentials.

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
Use `rr.fetch` with a selected series and time bounds to retrieve observations.
See [usage](../usage.md) for retrieval and cache policies. Archive variants and the
recent raw feed remain separate series. Recent retention and exact averaging
durations are unknown; caching cannot recover unseen expired observations.

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

The official catalogue states “Freie Nutzung. Quellenangabe ist Pflicht.”
This permits free use and requires source attribution. FOEN suggests the citation:
“Hydrology Division, Federal Office for the Environment FOEN (reference date).”
