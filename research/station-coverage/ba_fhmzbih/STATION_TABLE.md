# ba_fhmzbih — station list with established coverage

One row per station in the surveyed population. Generated from
`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; every station
appears, none is omitted.

`yes (n)` = the publisher declares `#Rows = n` observations in the rolling workbook.
`empty` = the publisher declares `#Rows = 0` **while still declaring the parameter and its unit**
for that station — no observations in the rolling year, *not* a statement that the station cannot
measure it. `404` = the route serves no workbook; an access failure, never evidence of absence.

**Baseline** marks the 60 stations in the committed `native.parquet` (the publisher's layer-20
membership). The other 39 are published hydrological stations of the identical object type that
the layer-20 capture excluded — see `UNRESOLVED.md` §3; they are not merged into the baseline.

| Station | Name | River | Site | Baseline | Q | H | WT |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `1010` | HS Svilaj | Sava | 1 | yes | **yes** (17,209) | **yes** (17,209) | empty |
| `1011` | CS Svilaj | Kanal/Svilaj | 1 | — | **yes** (16,795) | **yes** (17,207) | empty |
| `1012` | CS Zorice | Kanal/Zorice | 1 | — | **yes** (16,442) | **yes** (16,983) | empty |
| `1020` | HS Grebnice | Sava | 1 | yes | **yes** (8,517) | **yes** (8,517) | **yes** (7,251) |
| `1030` | HS Orašje | Sava | 1 | — | **yes** (2,090) | **yes** (7,598) | **yes** (5,512) |
| `1031` | CS Tolisa - Demerovac | Kanal/Demerovac | 1 | — | **yes** (14,777) | **yes** (15,565) | empty |
| `1032` | CS Tolisa - Briježnica | Kanal/Briježnica | 1 | — | **yes** (14,774) | **yes** (15,566) | empty |
| `1033` | CS Tolisa - Tolisa | Kanal/Tolisa | 1 | — | **yes** (14,775) | **yes** (15,569) | empty |
| `1110` | HS Srebrenik | Tinja | 1 | — | **yes** (1) | **yes** (8,688) | empty |
| `1114` | HS Krušnica | Krušnica | 2 | yes | **yes** (7,539) | **yes** (7,539) | empty |
| `2010` | HS Martin Brod | Una | 2 | yes | **yes** (8,232) | **yes** (8,580) | empty |
| `2020` | HS Kulen Vakuf | Una | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2030` | HS Kralje | Una | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2031` | HS Bihać | Una | 2 | — | **yes** (8,569) | **yes** (8,695) | **yes** (8,695) |
| `2035` | HS Ripač | Una | 2 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `2040` | HS Kostela | Una | 2 | — | **yes** (8,535) | **yes** (8,701) | **yes** (8,701) |
| `2050` | HS Bosanska Krupa | Una | 2 | yes | **yes** (6,793) | **yes** (6,793) | empty |
| `2060` | HS Bosanska Otoka | Una | 2 | yes | **yes** (8,702) | **yes** (8,702) | **yes** (8,702) |
| `2101-B` | HS Bistrica | Bistrica | 3 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `2103` | HS Veseočica | Veseočica | 3 | yes | **yes** (8,140) | **yes** (7,387) | empty |
| `2110` | HS Drvar | Unac | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2120` | HS Rmanj Manastir | Unac | 2 | yes | **yes** (8,701) | **yes** (8,701) | **yes** (8,701) |
| `2210` | HS Klokot | Klokot | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2310` | HS Ključ | Sana | 2 | yes | **yes** (7,816) | **yes** (7,779) | empty |
| `2320` | HS Sanski Most | Sana | 2 | yes | **yes** (8,702) | **yes** (8,702) | **yes** (8,702) |
| `3010` | HS Gornji Vakuf | Vrbas | 3 | yes | **yes** (8,688) | **yes** (8,687) | empty |
| `3020` | HS Daljan | Vrbas | 3 | yes | **yes** (8,687) | **yes** (8,687) | empty |
| `3030` | HS Kozluk | Vrbas | 3 | yes | **yes** (8,670) | **yes** (8,670) | empty |
| `3040` | HS Bugojno | Vrbas | 3 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `4010` | HS Vrelo Bosne | Bosna | 4 | yes | **yes** (7,830) | **yes** (7,830) | empty |
| `4020` | HS Rimski Most | Bosna | 4 | yes | **yes** (8,086) | **yes** (7,978) | empty |
| `4023` | HS Butile n/B | Bosna | 4 | — | **yes** (164) | **yes** (7,535) | empty |
| `4024` | HS Ljubnići | Bosna | 4 | yes | **yes** (8,346) | **yes** (8,347) | empty |
| `4030` | HS Visoko n/B | Bosna | 4 | yes | **yes** (8,621) | **yes** (8,621) | empty |
| `4042` | HS Kakanj n/B | Bosna | 4 | yes | **yes** (8,666) | **yes** (8,666) | empty |
| `4050` | HS Raspotočje | Bosna | 4 | yes | **yes** (8,692) | **yes** (8,692) | empty |
| `4055` | HS Žepče | Bosna | 4 | yes | **yes** (8,626) | **yes** (8,626) | empty |
| `4060` | HS Zavidovići n/B | Bosna | 4 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `4061` | HS Donji Ulišnjak | Bosna | 4 | yes | **yes** (8,345) | **yes** (8,345) | empty |
| `4062` | HS Maglaj Grad | Bosna | 4 | yes | **yes** (34,757) | **yes** (34,757) | empty |
| `4070` | HS Maglaj | Bosna | 4 | yes | **yes** (8,689) | **yes** (8,689) | **yes** (8,687) |
| `4071` | HS Kosova | Bosna | 4 | — | **yes** (8,456) | **yes** (8,688) | empty |
| `4080` | HS Šamac | Bosna | 4 | — | **yes** (8,456) | **yes** (8,673) | empty |
| `4109` | HS Trnovo | Željeznica | 4 | — | **yes** (8,197) | **yes** (8,439) | 404 |
| `4110` | HS Ilidža | Željeznica | 4 | yes | **yes** (5,189) | **yes** (5,189) | **yes** (1,899) |
| `4111` | HS Podteljig | Crna Rijeka | 4 | yes | **yes** (8,467) | **yes** (8,467) | empty |
| `4114` | HS Butmir | Tilava | 4 | — | **yes** (8,289) | **yes** (8,688) | empty |
| `4121` | HS Blažuj | Zujevina | 4 | yes | **yes** (7,935) | **yes** (7,935) | empty |
| `4130` | HS Doglodi | Dobrinja | 4 | yes | **yes** (8,231) | **yes** (8,231) | empty |
| `4142` | HS Vodoprivreda | Miljacka | 4 | yes | **yes** (8,704) | **yes** (8,704) | empty |
| `4145` | HS Butile n/M | Miljacka | 4 | — | **yes** (8,594) | **yes** (8,701) | empty |
| `4150` | HS Semizovac | Ljubina | 4 | yes | **yes** (8,686) | **yes** (8,686) | empty |
| `4161` | HS Ilijaš | Misoča | 4 | — | **yes** (8,313) | **yes** (8,591) | empty |
| `4170` | HS Podlugovi | Stavnja | 4 | yes | **yes** (8,222) | **yes** (8,222) | empty |
| `4220` | HS Visoko n/F | Fojnička rijeka | 4 | yes | **yes** (8,689) | **yes** (8,689) | empty |
| `4225` | HS Kreševka - Kiseljak | Kreševka | 4 | — | **yes** (8,458) | **yes** (8,689) | empty |
| `4228` | HS Bakovići-Željeznica | Bosna | 4 | — | 404 | 404 | 404 |
| `4230` | HS Obre | Trstionica | 4 | — | **yes** (8,484) | **yes** (8,498) | empty |
| `4240` | HS Kakanj n/Zg | Zgošća | 4 | yes | **yes** (8,692) | **yes** (8,692) | empty |
| `4310` | HS Travnik | Lašva | 4 | yes | **yes** (8,689) | **yes** (8,689) | empty |
| `4320` | HS Merdani | Lašva | 4 | — | **yes** (8,431) | **yes** (8,692) | empty |
| `4340` | HS Stipovići | Gostović | 4 | yes | **yes** (8,500) | **yes** (8,499) | empty |
| `4410` | HS Olovo | Krivaja | 4 | yes | **yes** (8,682) | **yes** (8,682) | empty |
| `4411` | HS Bioštica | Bioštica | 4 | yes | **yes** (8,689) | **yes** (8,689) | empty |
| `4412` | HS Olovske Luke | Stupčanica | 4 | yes | **yes** (8,687) | **yes** (8,687) | empty |
| `4420` | HS Maoča | Krivaja | 4 | yes | **yes** (8,271) | **yes** (8,271) | empty |
| `4430` | HS Zavidovići n/K | Krivaja | 4 | yes | **yes** (8,688) | **yes** (8,688) | **yes** (8,689) |
| `4450` | HS Liješnica | Lješnica | 4 | yes | **yes** (8,669) | **yes** (8,669) | empty |
| `4510` | HS Kaloševići | Usora | 4 | yes | **yes** (8,587) | **yes** (8,587) | empty |
| `4610` | HS Strašanj | Spreča | 4 | yes | **yes** (7,071) | **yes** (8,678) | empty |
| `4620` | HS Modrac | Spreča | 4 | yes | **yes** (8,110) | **yes** (8,688) | empty |
| `4630` | HS Karanovac | Spreča | 4 | yes | **yes** (8,669) | **yes** (8,669) | empty |
| `4911` | HS Vidara - akumulacija | Jezero Vidara | 1 | — | **yes** (338) | **yes** (8,650) | empty |
| `4931` | HS Hazna - akumulacija | Jezero Hazna | 1 | — | **yes** (629) | **yes** (8,698) | empty |
| `5010` | HS Goražde | Drina | 5 | yes | **yes** (17,382) | **yes** (17,382) | **yes** (17,379) |
| `5101` | HS Prača | Prača | 5 | yes | **yes** (8,685) | **yes** (8,685) | **yes** (8,684) |
| `5102` | HS Kolina | Kolunska rijeka | 5 | — | **yes** (34,340) | **yes** (34,755) | empty |
| `5103` | HS Kladanj | Drinjača | 5 | — | **yes** (8,602) | **yes** (8,703) | empty |
| `8001` | HS Modrac - akumulacija - JP Spreca d.d. Tuzla | Spreča | 4 | — | **yes** (8,144) | **yes** (8,623) | empty |
| `8002` | HS Banovići - JP Spreča d.d. Tuzla | Litva | 4 | — | **yes** (7,066) | **yes** (8,693) | empty |
| `8003` | HS Gračanica - JP Spreča d.d. Tuzla | Sokoluša | 4 | — | **yes** (8,322) | **yes** (8,629) | empty |
| `8004` | HS Kalesija - JP Spreča d.d. Tuzla | Gribaja | 4 | — | **yes** (6,955) | **yes** (8,686) | empty |
| `8006` | HS Modrac-Jala-JP Spreča d.d. Tuzla | Jala | 4 | — | **yes** (7,474) | **yes** (8,363) | empty |
| `8007` | HS Simin Han - JP Spreča d.d. Tuzla | Litva | 4 | — | **yes** (7,318) | **yes** (8,685) | empty |
| `8008` | HS Solina - JP Spreča d.d. Tuzla | Solina | 4 | — | **yes** (8,251) | **yes** (8,682) | empty |
| `8009` | HS Živinice - JP Spreča d.d. Tuzla | Oskova | 4 | — | **yes** (7,925) | **yes** (8,684) | empty |
| `9001` | HS Tržačka Raštela | Korana | 1 | — | **yes** (1) | **yes** (8,702) | empty |
| `9017` | HS Hrustovo | Sanica | 2 | yes | **yes** (8,672) | **yes** (8,672) | **yes** (8,672) |
| `9018` | HS Sanica | Sanica | 2 | yes | **yes** (8,517) | **yes** (8,517) | **yes** (8,517) |
| `9019` | HS Bliha | Bliha | 2 | yes | **yes** (8,677) | **yes** (8,677) | **yes** (8,677) |
| `9020` | HS Dabar | Dabar | 2 | — | **yes** (1) | **yes** (7,651) | empty |
| `9025` | HS Tržac | Mutnica | 1 | — | 404 | 404 | 404 |
| `9026` | HS Velika Kladuša | Kladušnica | 1 | — | **yes** (8,592) | **yes** (8,702) | **yes** (8,702) |
| `9030` | HS Fojnica | Dragača | 4 | yes | **yes** (8,688) | **yes** (8,688) | empty |
| `9043` | HS Turija | Turija | 4 | — | **yes** (1) | **yes** (8,689) | empty |
| `9044` | HS Živinice | Gostelja | 4 | yes | **yes** (8,686) | **yes** (8,686) | empty |
| `9045` | HS Donja Višća | Oskova | 4 | yes | **yes** (8,681) | **yes** (8,681) | empty |
| `9102` | HS Osjek | Bosna | 4 | — | empty | empty | empty |
| `9130` | HS Tešanjka | Usora | 4 | — | **yes** (1) | **yes** (8,690) | empty |

**99 stations · 297 station × product pairs · 208 established series.**

| Product | available | declared empty | access failed |
| --- | --- | --- | --- |
| `discharge_reported` | 96 | 1 | 2 |
| `stage_reported` | 96 | 1 | 2 |
| `water_temperature_reported` | 16 | 80 | 3 |
