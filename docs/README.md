# Developer documentation

- [`adr/`](adr/) records accepted architecture decisions. Catalogue origin semantics are in
  [ADR 0012](adr/0012-a-catalogue-column-declares-its-origin.md), committed-native builds are in
  [ADR 0013](adr/0013-the-catalogue-is-built-from-a-committed-native-table.md), and observation
  recordings are in [ADR 0024](adr/0024-an-observation-fixture-is-a-recording.md).
- [`catalogue-provenance.md`](catalogue-provenance.md) records shared catalogue evidence and
  maintenance conventions.
- [`development-conventions.md`](development-conventions.md) records active documentation and
  provider-safety conventions that do not define architecture.
- [`provider_ports/`](provider_ports/) records provider-specific sources, mappings, limitations, and
  provenance rationale.
- [`design/`](design/) contains broader design analyses.
- [`milestones/`](milestones/) contains historical delivery records.

Domain terms remain in [`../CONTEXT.md`](../CONTEXT.md).

## Provider evidence index

| Provider | Port notes | Structured provenance | Origin declarations |
|---|---|---|---|
| `ba_fhmzbih` | [notes](provider_ports/ba_fhmzbih.md) | [record](../src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/ba_fhmzbih/origins.py) |
| `br_ana` | [notes](provider_ports/br_ana.md) | [record](../src/rivretrieve/_internal/providers/br_ana/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/br_ana/origins.py) |
| `ca_eccc` | [notes](provider_ports/ca_eccc.md) | [record](../src/rivretrieve/_internal/providers/ca_eccc/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/ca_eccc/origins.py) |
| `ch_foen` | [notes](provider_ports/ch_foen.md) | [record](../src/rivretrieve/_internal/providers/ch_foen/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/ch_foen/origins.py) |
| `cz_chmi` | [notes](provider_ports/cz_chmi.md) | [record](../src/rivretrieve/_internal/providers/cz_chmi/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/cz_chmi/origins.py) |
| `fr_hubeau` | [notes](provider_ports/fr_hubeau.md) | [record](../src/rivretrieve/_internal/providers/fr_hubeau/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/fr_hubeau/origins.py) |
| `jp_mlit` | [notes](provider_ports/jp_mlit.md) | [record](../src/rivretrieve/_internal/providers/jp_mlit/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/jp_mlit/origins.py) |
| `lt_lhmt` | [notes](provider_ports/lt_lhmt.md) | [record](../src/rivretrieve/_internal/providers/lt_lhmt/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/lt_lhmt/origins.py) |
| `no_nve` | [notes](provider_ports/no_nve.md) | [withholding record](../src/rivretrieve/_internal/providers/no_nve/catalogue/provenance.json) | Not yet declared |
| `pl_imgw` | [notes](provider_ports/pl_imgw.md) | [record](../src/rivretrieve/_internal/providers/pl_imgw/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/pl_imgw/origins.py) |
| `th_thaiwater` | [notes](provider_ports/th_thaiwater.md) | [record](../src/rivretrieve/_internal/providers/th_thaiwater/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/th_thaiwater/origins.py) |
| `usgs_nwis` | [notes](provider_ports/usgs_nwis.md) | [record](../src/rivretrieve/_internal/providers/usgs_nwis/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/usgs_nwis/origins.py) |
| `za_dws` | [notes](provider_ports/za_dws.md) | [record](../src/rivretrieve/_internal/providers/za_dws/catalogue/provenance.json) | [origins](../src/rivretrieve/_internal/providers/za_dws/origins.py) |
