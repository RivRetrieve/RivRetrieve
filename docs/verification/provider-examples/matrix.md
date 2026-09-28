# All-provider verification matrix

Status below separates deterministic implementation evidence from live examples.
Baseline examples ran at `0b443049d50819978030e29e46011ca2101cb337`, before the
implementation changes. They cannot establish final acceptance. All-provider
acceptance remains incomplete while final examples and reviews are pending.

| Provider | Required behavior | Implementation evidence | Baseline documented examples |
| --- | --- | --- | --- |
| `cz_chmi` | Correct independent annual DQ/HQ acquisition and cache intervals | PR #411 | Displayed output matched |
| `th_thaiwater` | Correct independent 365-day acquisitions | PR #411 | Both snippets matched, including published null discharge |
| `br_ana` | Correct independent monthly daily and backward telemetry acquisitions | PR #411 | All four snippets matched; documented unresolved bruto warning retained |
| `jp_mlit` | Correct independent chunks and dependent HTML/DAT evidence | PR #411 | Both snippets matched, including local reuse |
| `fr_hubeau` | Retain incomplete cursor evidence without completed coverage | PR #411 | Displayed output matched |
| `usgs_nwis` | Isolate 1100-day spans; retain dependent cursor completion | PR #411 | All three snippets matched |
| `ba_fhmzbih` | Preserve rolling snapshot rows without invented interval completeness | PR #410, review fixes pending | Displayed output matched; openpyxl style warning on stderr |
| `ca_eccc` | Refuse older replacement; retain HTTP reasons; reject unsafe paths | PR #409 merged and independently approved | Live national compilation in progress |
| `lt_lhmt` | Preserve independent monthly and shared-product behavior | Shared/monthly tests in PRs #410/#411 | Displayed output matched |
| `no_nve` | Preserve version isolation and mixed refresh | PR #410 | Both snippets matched |
| `ch_foen` | Preserve public singleton isolation; reject unsafe internal batching | PR #410 | All three snippets matched |
| `pl_imgw` | Preserve complete-history atomic certification and rollback | 200-test store suite, PR #409 | Live national download in progress |
| `fr_hydroportail` | Preserve variant isolation and mixed refresh | PR #410 | **Blocked:** both observation requests exhausted timeouts; catalogue snippet matched |
| `za_dws` | Keep explicit catalogue-only observation unavailability | Final suite pending | Not applicable: no provider page or observation snippet |

[Implementation commands and timings](implementation-tests.md) are separate from
[live execution records](README.md). A successful Python process with a failed
source issue is not counted as a successful observation example.
