# Interactive Station Map

Explore **78,175** river-gauge catalogue entries across 14 providers and 13 countries in RivRetrieve.

Use the controls on the top-right to:

- **Filter by provider / country**: Toggle specific agencies and networks on and off.
- **Search by gauge ID**: Instantly filter stations matching your gauge identifier.
- **Inspect stations**: Click any pin or circle to view its coordinates, CRS status, and copy a Python selection snippet for [`rivretrieve.find()`](reference.md#find).

<iframe src="../assets/stations_map.html" width="100%" height="720px" style="border: 1px solid #cbd5e1; border-radius: 8px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); margin-top: 1rem; margin-bottom: 1.5rem;"></iframe>

!!! tip "Full Window View"
    Want more screen real estate? You can also open the [interactive map in a full browser tab](assets/stations_map.html){:target="_blank"}.

---

## Supported Providers on the Map

| Country | Agency | Provider ID | Catalogued Stations |
|---|---|---|---:|
| United States | U.S. Geological Survey (USGS) | `usgs_nwis` | 26,258 |
| Brazil | Agência Nacional de Águas e Saneamento Básico (ANA) | `br_ana` | 17,914 |
| Canada | Environment and Climate Change Canada (ECCC) | `ca_eccc` | 8,057 |
| France | Hub'Eau | `fr_hubeau` | 7,347 |
| France | HydroPortail | `fr_hydroportail` | 6,409 |
| Norway | Norwegian Water Resources and Energy Directorate (NVE) | `no_nve` | 4,902 |
| Poland | Institute of Meteorology and Water Management (IMGW) | `pl_imgw` | 1,301 |
| Japan | Ministry of Land, Infrastructure, Transport and Tourism (MLIT) | `jp_mlit` | 1,023 |
| Czechia | Czech Hydrometeorological Institute (CHMI) | `cz_chmi` | 831 |
| Thailand | Hydro-Informatics Institute (HII), ThaiWater | `th_thaiwater` | 825 |
| Switzerland | Federal Office for the Environment (FOEN) | `ch_foen` | 246 |
| Lithuania | Lithuanian Hydrometeorological Service (LHMT) | `lt_lhmt` | 97 |
| Bosnia and Herzegovina | Agencija za vodno područje rijeke Save (AVP Sava) | `ba_fhmzbih` | 60 |
| South Africa | Department of Water and Sanitation (DWS) | `za_dws` | 2,905 |

Station counts describe packaged catalogue entries, not continuous data coverage or
unique physical sites across providers. South Africa supports catalogue discovery
only. A station on the map need not have observations for a requested quantity or
period. See [provider capabilities](reference.md#shipped-software-capabilities).

Markers use catalogue coordinates. Unknown-CRS coordinates are displayed as if they
used EPSG:4326; that display assumption does not establish their reference system.
Use the map for exploration, not coordinate certification.
