# ba_fhmzbih — station list with established coverage

One row per station in the surveyed population. Generated from
`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; every station
appears, none is omitted.

`yes (n)` = the download carried *n* populated measurement cells.
`blank (n rows, 0 values)` = the download carried *n* timestamped rows with every measurement
cell published empty, **while still declaring the parameter and its unit**. That establishes what
this download contained; it is *not* a statement that the station cannot measure the parameter.
`empty` = no data rows at all, parameter and unit still declared.
`404` = the route serves no workbook; an access failure, never evidence of absence.

Counts are populated measurement cells, not the publisher's `#Rows` header. The header counts
timestamped rows, including rows whose measurement cell is empty, so it overstates availability.

**Baseline** marks the 60 stations in the committed `native.parquet` (the publisher's layer-20
membership). The other 39 are published hydrological stations that the layer-20 capture excluded
— see `UNRESOLVED.md` §3; they are not merged into the baseline.

| Station | Name | River | Site | Baseline | Q | H | WT |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `1010` | HS Svilaj | Sava | 1 | yes | **yes** (17,209) | **yes** (17,209) | empty |
| `1011` | CS Svilaj | Kanal/Svilaj | 1 | — | blank (16,796 rows, 0 values) | **yes** (17,207) | empty |
| `1012` | CS Zorice | Kanal/Zorice | 1 | — | blank (16,424 rows, 0 values) | **yes** (16,965) | empty |
| `1020` | HS Grebnice | Sava | 1 | yes | **yes** (8,508) | **yes** (8,508) | **yes** (7,209) |
| `1030` | HS Orašje | Sava | 1 | — | **yes** (2,161) | **yes** (2,161) | blank (5,440 rows, 0 values) |
| `1031` | CS Tolisa - Demerovac | Kanal/Demerovac | 1 | — | blank (14,777 rows, 0 values) | **yes** (15,565) | empty |
| `1032` | CS Tolisa - Briježnica | Kanal/Briježnica | 1 | — | blank (14,774 rows, 0 values) | **yes** (15,566) | empty |
| `1033` | CS Tolisa - Tolisa | Kanal/Tolisa | 1 | — | blank (14,775 rows, 0 values) | **yes** (15,569) | empty |
| `1110` | HS Srebrenik | Tinja | 1 | — | blank (1 rows, 0 values) | **yes** (8,688) | empty |
| `1114` | HS Krušnica | Krušnica | 2 | yes | **yes** (7,498) | **yes** (7,498) | empty |
| `2010` | HS Martin Brod | Una | 2 | yes | **yes** (8,212) | **yes** (8,212) | empty |
| `2020` | HS Kulen Vakuf | Una | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2030` | HS Kralje | Una | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2031` | HS Bihać | Una | 2 | — | blank (8,570 rows, 0 values) | **yes** (8,693) | **yes** (8,693) |
| `2035` | HS Ripač | Una | 2 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `2040` | HS Kostela | Una | 2 | — | blank (8,535 rows, 0 values) | **yes** (8,701) | **yes** (8,690) |
| `2050` | HS Bosanska Krupa | Una | 2 | yes | **yes** (6,865) | **yes** (6,865) | empty |
| `2060` | HS Bosanska Otoka | Una | 2 | yes | **yes** (8,702) | **yes** (8,702) | **yes** (8,702) |
| `2101-B` | HS Bistrica | Bistrica | 3 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `2103` | HS Veseočica | Veseočica | 3 | yes | **yes** (8,054) | **yes** (7,287) | empty |
| `2110` | HS Drvar | Unac | 2 | yes | **yes** (8,701) | **yes** (8,701) | empty |
| `2120` | HS Rmanj Manastir | Unac | 2 | yes | **yes** (8,701) | **yes** (8,701) | **yes** (8,701) |
| `2210` | HS Klokot | Klokot | 2 | yes | **yes** (8,702) | **yes** (8,702) | empty |
| `2310` | HS Ključ | Sana | 2 | yes | **yes** (7,750) | **yes** (7,773) | empty |
| `2320` | HS Sanski Most | Sana | 2 | yes | **yes** (8,702) | **yes** (8,702) | **yes** (8,702) |
| `3010` | HS Gornji Vakuf | Vrbas | 3 | yes | **yes** (8,687) | **yes** (8,687) | empty |
| `3020` | HS Daljan | Vrbas | 3 | yes | **yes** (8,687) | **yes** (8,687) | empty |
| `3030` | HS Kozluk | Vrbas | 3 | yes | **yes** (8,674) | **yes** (8,674) | empty |
| `3040` | HS Bugojno | Vrbas | 3 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `4010` | HS Vrelo Bosne | Bosna | 4 | yes | **yes** (7,861) | **yes** (7,861) | empty |
| `4020` | HS Rimski Most | Bosna | 4 | yes | **yes** (8,086) | **yes** (7,978) | empty |
| `4023` | HS Butile n/B | Bosna | 4 | — | blank (164 rows, 0 values) | **yes** (7,463) | empty |
| `4024` | HS Ljubnići | Bosna | 4 | yes | **yes** (8,346) | **yes** (8,347) | empty |
| `4030` | HS Visoko n/B | Bosna | 4 | yes | **yes** (8,611) | **yes** (8,611) | empty |
| `4042` | HS Kakanj n/B | Bosna | 4 | yes | **yes** (8,664) | **yes** (8,666) | empty |
| `4050` | HS Raspotočje | Bosna | 4 | yes | **yes** (8,692) | **yes** (8,692) | empty |
| `4055` | HS Žepče | Bosna | 4 | yes | **yes** (8,563) | **yes** (8,563) | empty |
| `4060` | HS Zavidovići n/B | Bosna | 4 | yes | **yes** (8,700) | **yes** (8,699) | empty |
| `4061` | HS Donji Ulišnjak | Bosna | 4 | yes | **yes** (8,344) | **yes** (8,344) | empty |
| `4062` | HS Maglaj Grad | Bosna | 4 | yes | **yes** (34,754) | **yes** (34,754) | empty |
| `4070` | HS Maglaj | Bosna | 4 | yes | **yes** (8,688) | **yes** (8,688) | **yes** (8,686) |
| `4071` | HS Kosova | Bosna | 4 | — | blank (8,456 rows, 0 values) | **yes** (8,688) | empty |
| `4080` | HS Šamac | Bosna | 4 | — | blank (8,456 rows, 0 values) | **yes** (8,671) | empty |
| `4109` | HS Trnovo | Željeznica | 4 | — | blank (8,197 rows, 0 values) | **yes** (8,439) | 404 |
| `4110` | HS Ilidža | Željeznica | 4 | yes | **yes** (5,189) | **yes** (5,189) | **yes** (1,827) |
| `4111` | HS Podteljig | Crna Rijeka | 4 | yes | **yes** (8,458) | **yes** (8,458) | empty |
| `4114` | HS Butmir | Tilava | 4 | — | blank (8,286 rows, 0 values) | **yes** (8,687) | empty |
| `4121` | HS Blažuj | Zujevina | 4 | yes | **yes** (7,966) | **yes** (7,966) | empty |
| `4130` | HS Doglodi | Dobrinja | 4 | yes | **yes** (7,596) | **yes** (8,159) | empty |
| `4142` | HS Vodoprivreda | Miljacka | 4 | yes | **yes** (8,704) | **yes** (8,704) | empty |
| `4145` | HS Butile n/M | Miljacka | 4 | — | blank (8,594 rows, 0 values) | **yes** (7,811) | empty |
| `4150` | HS Semizovac | Ljubina | 4 | yes | **yes** (8,686) | **yes** (8,686) | empty |
| `4161` | HS Ilijaš | Misoča | 4 | — | blank (8,313 rows, 0 values) | **yes** (8,591) | empty |
| `4170` | HS Podlugovi | Stavnja | 4 | yes | **yes** (8,204) | **yes** (8,204) | empty |
| `4220` | HS Visoko n/F | Fojnička rijeka | 4 | yes | **yes** (8,689) | **yes** (8,689) | empty |
| `4225` | HS Kreševka - Kiseljak | Kreševka | 4 | — | blank (8,458 rows, 0 values) | **yes** (8,689) | empty |
| `4228` | HS Bakovići-Željeznica | Bosna | 4 | — | 404 | 404 | 404 |
| `4230` | HS Obre | Trstionica | 4 | — | **yes** (8,484) | **yes** (8,498) | empty |
| `4240` | HS Kakanj n/Zg | Zgošća | 4 | yes | **yes** (8,692) | **yes** (8,692) | empty |
| `4310` | HS Travnik | Lašva | 4 | yes | **yes** (8,689) | **yes** (8,689) | empty |
| `4320` | HS Merdani | Lašva | 4 | — | blank (8,431 rows, 0 values) | **yes** (8,691) | empty |
| `4340` | HS Stipovići | Gostović | 4 | yes | **yes** (8,500) | **yes** (8,500) | empty |
| `4410` | HS Olovo | Krivaja | 4 | yes | **yes** (8,682) | **yes** (8,682) | empty |
| `4411` | HS Bioštica | Bioštica | 4 | yes | **yes** (8,690) | **yes** (8,690) | empty |
| `4412` | HS Olovske Luke | Stupčanica | 4 | yes | **yes** (8,688) | **yes** (8,688) | empty |
| `4420` | HS Maoča | Krivaja | 4 | yes | **yes** (8,260) | **yes** (8,260) | empty |
| `4430` | HS Zavidovići n/K | Krivaja | 4 | yes | **yes** (8,689) | **yes** (8,689) | **yes** (8,690) |
| `4450` | HS Liješnica | Lješnica | 4 | yes | **yes** (8,597) | **yes** (8,597) | empty |
| `4510` | HS Kaloševići | Usora | 4 | yes | **yes** (8,587) | **yes** (8,587) | empty |
| `4610` | HS Strašanj | Spreča | 4 | yes | **yes** (7,001) | **yes** (8,679) | empty |
| `4620` | HS Modrac | Spreča | 4 | yes | **yes** (7,996) | **yes** (8,688) | empty |
| `4630` | HS Karanovac | Spreča | 4 | yes | **yes** (8,671) | **yes** (8,671) | empty |
| `4911` | HS Vidara - akumulacija | Jezero Vidara | 1 | — | blank (337 rows, 0 values) | **yes** (8,650) | empty |
| `4931` | HS Hazna - akumulacija | Jezero Hazna | 1 | — | blank (629 rows, 0 values) | **yes** (8,698) | empty |
| `5010` | HS Goražde | Drina | 5 | yes | **yes** (17,382) | **yes** (17,382) | **yes** (17,379) |
| `5101` | HS Prača | Prača | 5 | yes | **yes** (8,686) | **yes** (8,686) | **yes** (8,685) |
| `5102` | HS Kolina | Kolunska rijeka | 5 | — | blank (34,340 rows, 0 values) | **yes** (34,755) | empty |
| `5103` | HS Kladanj | Drinjača | 5 | — | blank (8,602 rows, 0 values) | **yes** (8,703) | empty |
| `8001` | HS Modrac - akumulacija - JP Spreca d.d. Tuzla | Spreča | 4 | — | blank (8,145 rows, 0 values) | **yes** (8,623) | empty |
| `8002` | HS Banovići - JP Spreča d.d. Tuzla | Litva | 4 | — | blank (7,052 rows, 0 values) | **yes** (8,691) | empty |
| `8003` | HS Gračanica - JP Spreča d.d. Tuzla | Sokoluša | 4 | — | blank (8,322 rows, 0 values) | **yes** (8,630) | empty |
| `8004` | HS Kalesija - JP Spreča d.d. Tuzla | Gribaja | 4 | — | blank (6,957 rows, 0 values) | **yes** (8,684) | empty |
| `8006` | HS Modrac-Jala-JP Spreča d.d. Tuzla | Jala | 4 | — | blank (7,469 rows, 0 values) | **yes** (8,362) | empty |
| `8007` | HS Simin Han - JP Spreča d.d. Tuzla | Litva | 4 | — | blank (7,306 rows, 0 values) | **yes** (8,684) | empty |
| `8008` | HS Solina - JP Spreča d.d. Tuzla | Solina | 4 | — | blank (8,250 rows, 0 values) | **yes** (8,682) | empty |
| `8009` | HS Živinice - JP Spreča d.d. Tuzla | Oskova | 4 | — | blank (7,939 rows, 0 values) | **yes** (8,684) | empty |
| `9001` | HS Tržačka Raštela | Korana | 1 | — | blank (1 rows, 0 values) | **yes** (8,697) | empty |
| `9017` | HS Hrustovo | Sanica | 2 | yes | **yes** (8,670) | **yes** (8,670) | **yes** (8,668) |
| `9018` | HS Sanica | Sanica | 2 | yes | **yes** (8,518) | **yes** (8,518) | **yes** (8,518) |
| `9019` | HS Bliha | Bliha | 2 | yes | **yes** (8,677) | **yes** (8,677) | **yes** (8,677) |
| `9020` | HS Dabar | Dabar | 2 | — | blank (1 rows, 0 values) | **yes** (7,647) | empty |
| `9025` | HS Tržac | Mutnica | 1 | — | 404 | 404 | 404 |
| `9026` | HS Velika Kladuša | Kladušnica | 1 | — | blank (8,592 rows, 0 values) | **yes** (8,702) | **yes** (8,702) |
| `9030` | HS Fojnica | Dragača | 4 | yes | **yes** (8,688) | **yes** (8,688) | empty |
| `9043` | HS Turija | Turija | 4 | — | blank (1 rows, 0 values) | **yes** (8,689) | empty |
| `9044` | HS Živinice | Gostelja | 4 | yes | **yes** (8,686) | **yes** (8,686) | empty |
| `9045` | HS Donja Višća | Oskova | 4 | yes | **yes** (8,681) | **yes** (8,681) | empty |
| `9102` | HS Osjek | Bosna | 4 | — | empty | empty | empty |
| `9130` | HS Tešanjka | Usora | 4 | — | blank (1 rows, 0 values) | **yes** (8,691) | empty |

**99 stations · 297 station × product pairs · 173 series carrying measurements.**

| Product | measurements | timestamped, no values | no data rows | access failed |
| --- | --- | --- | --- | --- |
| `discharge_reported` | 62 | 34 | 1 | 2 |
| `stage_reported` | 96 | 0 | 1 | 2 |
| `water_temperature_reported` | 15 | 1 | 80 | 3 |
