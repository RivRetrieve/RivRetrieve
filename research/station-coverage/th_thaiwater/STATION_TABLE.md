# th_thaiwater — station list with established coverage

One row per station in the committed 825-station baseline. Generated from
`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; no station is omitted.

`yes (n)` = the graph route published *n* non-null values for that product's field in the tested
window. `empty` = the route answered with a complete time grid carrying no non-null value — the
source states nothing about whether the station can supply the measurement, and this is never
recorded as unsupported.

Availability comes from the graph route, never from catalogue metadata: the snapshot `discharge`
field disagrees with the route for 19 of these 825 stations, and its `waterlevel_m` field is null
for every one of them.

Stations empty over the 7-day window were re-probed over 90 days and the wider window governs;
that recovered 14 of 26. `Live` marks presence in the 2026-09-07 `waterlevel_load` snapshot —
absence there is not evidence of absence of data.

| Station | Name (th) | River | Agency | Basin | Live | Stage | Discharge |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `1` | คลองลาดพร้าว วัดบางบัว | คลองบางบัว | HII | Chao Phraya Basin | yes | **yes** (13,069) | empty |
| `3` | คลองลำปลาทิว ลาดกระบัง | คลองลำปลาทิว | HII | Bang Pakong Basin | yes | **yes** (6,936) | empty |
| `4` | สะพานกรุงเทพ | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (12,963) | empty |
| `5` | คลองมหาสวัสดิ บางกรวย-สวนผัก | คลองมหาสวัสดิ์ | HII | Chao Phraya Basin | yes | **yes** (5,092) | empty |
| `8` | คลองลาดพร้าว ปากคลอง2สายใต้ | คลองหกวา | HII | Bang Pakong Basin | yes | **yes** (13,062) | empty |
| `10` | คลองภาษีเจริญ เพชรเกษม69 | คลองภาษีเจริญ | HII | Chao Phraya Basin | yes | **yes** (13,056) | empty |
| `11` | คลองลาดพร้าว ท้ายปตร.คลอง2 | คลองหกวา | HII | Chao Phraya Basin | yes | **yes** (13,059) | empty |
| `14` | คลองทวีวัฒนา ท้ายปตร.ทวีวัฒนา | คลองทวีวัฒนา | HII | Chao Phraya Basin | — | **yes** (10,084) | empty |
| `21` | คลองจระเข้ใหญ่ บางเสาธง (วัดศรีวารีน้อย) | คลองหัวตะเข้ | HII | Bang Pakong Basin | yes | **yes** (13,045) | empty |
| `24` | คลองพระพิมล (ไทรน้อย) | คลองพระพิมล | HII | Chao Phraya Basin | yes | **yes** (13,068) | empty |
| `26` | สะพานนวลฉวี | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (12,861) | empty |
| `27` | คลองเปรมประชากร หลักหก | คลองเปรมประชากร | HII | Chao Phraya Basin | yes | **yes** (12,845) | empty |
| `29` | คลองระพีพัฒน์แยกตก | คลองระพีพัฒน์แยกตก | HII | Chao Phraya Basin | yes | **yes** (12,986) | empty |
| `36` | คลองระพีพัฒน์แยกใต้ หนองเสือ | คลองลาดผักขวง | HII | Chao Phraya Basin | yes | **yes** (13,064) | empty |
| `37` | คลองหกวา ลำลูกกา คลอง8 | คลองหกวา | HII | Bang Pakong Basin | yes | **yes** (13,058) | empty |
| `39` | พระนครศรีอยุธยา | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,065) | empty |
| `40` | ท่าเรือ | แม่น้ำป่าสัก | HII | Pasak Basin | yes | **yes** (13,055) | empty |
| `44` | นครหลวง | แม่น้ำป่าสัก | HII | Pasak Basin | yes | **yes** (13,067) | empty |
| `47` | คลองบางบาล | คลองบางบาล | HII | Chao Phraya Basin | yes | **yes** (12,990) | empty |
| `48` | คลองบางหลวง | แม่น้ำน้อย | HII | Chao Phraya Basin | yes | **yes** (13,039) | empty |
| `49` | บางปะอิน | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (12,971) | empty |
| `50` | บางปะหัน | แม่น้ำลพบุรี | HII | Chao Phraya Basin | yes | **yes** (13,063) | empty |
| `54` | คลองพระยาบรรลือ | คลองพระยาบรรลือ | HII | Chao Phraya Basin | yes | **yes** (13,070) | empty |
| `57` | เสนา | แม่น้ำน้อย | HII | Chao Phraya Basin | yes | **yes** (13,066) | empty |
| `58` | เมืองอ่างทอง | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,028) | empty |
| `61` | เมืองลพบุรี | แม่น้ำลพบุรี | HII | Chao Phraya Basin | yes | **yes** (13,069) | empty |
| `68` | พรหมบุรี | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,013) | empty |
| `71` | อินทร์บุรี | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,030) | empty |
| `79` | สะพานคง-ศุข ศรีสวัสดิ์ | แม่น้ำท่าจีน | HII | Chao Phraya Basin | yes | **yes** (13,067) | empty |
| `80` | สะพานธรรมจักร(วัดธรรมามูล) | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,070) | empty |
| `83` | ปตร.มโนรมย์ | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (12,938) | empty |
| `89` | สรรพยา | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,057) | empty |
| `115` | เมืองแกลง | แม่น้ำประแสร์ | HII | East Coast Gulf Basin | yes | **yes** (12,679) | empty |
| `118` | หนองบัว | คลองใหญ่ | HII | East Coast Gulf Basin | yes | **yes** (12,962) | empty |
| `120` | เมืองจันทบุรี | คลองจันทบุรี | HII | East Coast Gulf Basin | yes | **yes** (12,418) | empty |
| `128` | แก่งหางแมว | คลองโตนด | HII | East Coast Gulf Basin | yes | **yes** (12,447) | empty |
| `131` | นายายอาม | คลองวังโตนด | HII | East Coast Gulf Basin | yes | **yes** (12,990) | empty |
| `136` | วังกระแจะ | แม่น้ำตราด | HII | East Coast Gulf Basin | yes | **yes** (13,059) | empty |
| `137` | เมืองตราด | แม่น้ำเขาสมิง | HII | East Coast Gulf Basin | yes | **yes** (13,056) | empty |
| `138` | ห้วยแร้ง | คลองห้วยแร้ง | HII | East Coast Gulf Basin | yes | **yes** (12,899) | empty |
| `149` | ปากคลองพระองค์เจ้าฯ (บางน้ำเปรี้ยว) | คลองพระองค์เจ้าไชยานุชิต | HII | Bang Pakong Basin | yes | **yes** (13,050) | empty |
| `151` | บางน้ำเปรี้ยว | แม่น้ำบางปะกง | HII | Bang Pakong Basin | yes | **yes** (12,405) | empty |
| `154` | บางปะกง | แม่น้ำบางปะกง | HII | Bang Pakong Basin | yes | **yes** (13,067) | empty |
| `156` | พนมสารคาม | คลองท่าลาด | HII | Bang Pakong Basin | yes | **yes** (13,061) | empty |
| `160` | เมืองปราจีนบุรี | แม่น้ำบางปะกง | HII | Bang Pakong Basin | yes | **yes** (2,675) | empty |
| `162` | กบินทร์บุรี | แม่น้ำบางปะกง | HII | Bang Pakong Basin | yes | **yes** (12,899) | empty |
| `165` | นาดี | แควหนุมาน | HII | Bang Pakong Basin | yes | **yes** (13,025) | empty |
| `169` | ประจันตคาม (KGT7A) | คลองอินทร์ไตร | HII | Bang Pakong Basin | yes | **yes** (12,474) | empty |
| `170` | ศรีมหาโพธิ (KGT6) | แม่น้ำบางปะกง | HII | Bang Pakong Basin | yes | **yes** (12,263) | empty |
| `175` | สะพานเขานางบวช | แม่น้ำนครนายก | HII | Bang Pakong Basin | yes | **yes** (12,898) | empty |
| `189` | องครักษ์ | แม่น้ำนครนายก | HII | Bang Pakong Basin | yes | **yes** (12,953) | empty |
| `190` | คลองพระปรง | คลองพระปรง | HII | Bang Pakong Basin | yes | **yes** (6,238) | empty |
| `191` | เมืองสระแก้ว | คลองพระสะทึง | HII | Bang Pakong Basin | — | **yes** (9,582) | empty |
| `192` | ตาพระยา | ห้วยยาง | HII | Tonle Sap Basin | yes | **yes** (13,055) | empty |
| `200` | คลองพรหมโหด | ห้วยพรมโหด | HII | Tonle Sap Basin | yes | **yes** (13,059) | empty |
| `218` | ชุมพวง | ลำปลายมาศ | HII | Mun Basin | yes | **yes** (12,808) | empty |
| `228` | เฉลิมพระเกียรติ | แม่น้ำมูล | HII | Mun Basin | yes | **yes** (12,930) | empty |
| `236` | ประโคนชัย | ลำชี | HII | Mun Basin | yes | **yes** (10,105) | empty |
| `238` | สตึก | แม่น้ำมูล | HII | Mun Basin | yes | **yes** (11,427) | empty |
| `245` | เมืองสุรินทร์ | ลำชี | HII | Mun Basin | yes | **yes** (12,824) | empty |
| `255` | เมืองศรีสะเกษ | ห้วยสำราญ | HII | Mun Basin | yes | **yes** (12,852) | empty |
| `262` | ราษีไศล | แม่น้ำมูล | HII | Mun Basin | yes | **yes** (11,636) | empty |
| `269` | เขื่องใน | แม่น้ำชี | HII | Chi Basin Basin | yes | **yes** (13,006) | empty |
| `281` | พิบูลมังสาหาร | แม่น้ำมูล | HII | Mun Basin | yes | **yes** (12,239) | empty |
| `296` | เมืองชัยภูมิ | แม่น้ำชี | HII | Chi Basin Basin | yes | **yes** (13,031) | empty |
| `298` | บ้านเขว้า | แม่น้ำชี | HII | Chi Basin Basin | yes | **yes** (12,931) | empty |
| `315` | สุวรรณคูหา | ห้วยโค่โล่ | HII | Northeast Khong Basin | yes | **yes** (12,968) | empty |
| `319` | สะพานฉลองขอนแก่น 200 ปี | ลำน้ำพอง | HII | Chi Basin Basin | yes | **yes** (9,199) | empty |
| `330` | ชนบท | แม่น้ำชี | HII | Chi Basin Basin | yes | **yes** (12,835) | empty |
| `333` | เมืองขอนแก่น | แม่น้ำชี | HII | Chi Basin Basin | yes | **yes** (12,246) | empty |
| `335` | เมืองอุดรธานี | ห้วยหลวง | HII | Northeast Khong Basin | yes | **yes** (12,307) | empty |
| `342` | เมืองเลย | แม่น้ำเลย | HII | Northeast Khong Basin | yes | **yes** (13,055) | empty |
| `348` | วังสะพุง | แม่น้ำเลย | HII | Northeast Khong Basin | yes | **yes** (12,388) | empty |
| `358` | เมืองมหาสารคาม | แม่น้ำชี | HII | Chi Basin Basin | yes | **yes** (12,964) | empty |
| `380` | ยางตลาด | ลำพาน | HII | Chi Basin Basin | yes | **yes** (10,402) | empty |
| `393` | บ้านม่วง | แม่น้ำสงคราม | HII | Northeast Khong Basin | — | **yes** (2,002) | empty |
| `395` | สะพานนาทม | แม่น้ำสงคราม | HII | Northeast Khong Basin | yes | **yes** (12,881) | empty |
| `396` | สว่างแดนดิน | แม่น้ำสงคราม | HII | Northeast Khong Basin | yes | **yes** (12,504) | empty |
| `405` | ศรีสงคราม | แม่น้ำสงคราม | HII | Northeast Khong Basin | yes | **yes** (12,704) | empty |
| `414` | เชียงดาว | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,067) | empty |
| `418` | แม่แตง | แม่น้ำแม่แตง | HII | Ping Basin | yes | **yes** (13,070) | empty |
| `422` | ฝาง | น้ำฝาง | HII | North Khong Basin | yes | **yes** (13,061) | empty |
| `424` | แม่อาย | แม่น้ำกก | HII | North Khong Basin | yes | **yes** (13,070) | empty |
| `427` | สะพานโยธาอำนวยพัฒนา | น้ำแม่ขาน | HII | Ping Basin | yes | **yes** (12,966) | empty |
| `430` | สันทราย | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,069) | empty |
| `434` | ฮอด | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (12,770) | empty |
| `454` | เกาะคา | แม่น้ำวัง | HII | Wang Basin | yes | **yes** (13,064) | empty |
| `463` | เถิน | แม่น้ำวัง | HII | Wang Basin | yes | **yes** (13,070) | empty |
| `464` | แม่พริก | แม่น้ำวัง | HII | Wang Basin | yes | **yes** (13,070) | empty |
| `472` | เมืองอุตรดิตถ์ | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (12,991) | empty |
| `475` | ตรอน | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,099) | empty |
| `478` | น้ำปาด | น้ำปาด | HII | Nan Basin | yes | **yes** (13,065) | empty |
| `482` | พิชัย | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,099) | empty |
| `483` | คลองผันน้ำยม-น่าน3 | คลองละมุง | HII | Nan Basin | yes | **yes** (13,014) | empty |
| `489` | เมืองแพร่ | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,069) | empty |
| `493` | เด่นชัย | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,065) | empty |
| `499` | หนองม่วงไข่ | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,070) | empty |
| `510` | ท่าวังผา | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,069) | empty |
| `512` | เวียงสา | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,052) | empty |
| `522` | ภูเพียง | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,055) | empty |
| `523` | เมืองน่าน | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,013) | empty |
| `526` | ท้ายกว๊านพะเยา | น้ำแม่ต๋ำ | HII | North Khong Basin | yes | **yes** (13,069) | empty |
| `537` | เมืองเชียงราย | น้ำแม่ลาว | HII | North Khong Basin | yes | **yes** (13,068) | empty |
| `542` | เทิง | แม่น้ำอิง | HII | North Khong Basin | yes | **yes** (13,050) | empty |
| `545` | แม่จัน | น้ำแม่จัน | HII | North Khong Basin | yes | **yes** (13,068) | empty |
| `547` | เชียงแสน | แม่น้ำกก | HII | North Khong Basin | yes | **yes** (13,070) | empty |
| `550` | แม่สรวย | น้ำแม่ลาว | HII | North Khong Basin | yes | **yes** (13,067) | empty |
| `560` | เมืองแม่ฮ่องสอน | แม่น้ำปาย | HII | Salawin Basin | yes | **yes** (13,070) | empty |
| `568` | สะพานเดชาติวงศ์ | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,069) | empty |
| `573` | ชุมแสง | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,067) | empty |
| `577` | เก้าเลี้ยว | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,069) | empty |
| `584` | พยุหะคีรี | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (13,065) | empty |
| `587` | คลองกลาง | คลองตะกวด | HII | Sakae Krang Basin | yes | **yes** (13,061) | empty |
| `592` | สะพานแม่เล่ย์ | คลองห้วยทราย | HII | Sakae Krang Basin | yes | **yes** (13,063) | empty |
| `595` | เมืองอุทัยธานี | แม่น้ำสะแกกรัง | HII | Sakae Krang Basin | yes | **yes** (9,724) | empty |
| `609` | เมืองกำแพงเพชร (P7A) | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,067) | empty |
| `610` | สะพานลานดอกไม้ | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,070) | empty |
| `611` | ท่อทองแดง1 | คลองหนองเต่า | HII | Ping Basin | yes | **yes** (13,069) | empty |
| `616` | ขาณุวรลักษบุรี | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,069) | empty |
| `618` | สะพานแม่วงก์ | แม่น้ำแม่วงก์ | HII | Sakae Krang Basin | yes | **yes** (13,066) | empty |
| `619` | สะพานต้นน้ำ (เกาะแก้ว-ตลิ่งสูง) | แม่น้ำแม่วงก์ | HII | Sakae Krang Basin | yes | **yes** (13,061) | empty |
| `628` | บ้านตาก | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,070) | empty |
| `630` | สามเงา | แม่น้ำวัง | HII | Wang Basin | yes | **yes** (13,070) | empty |
| `638` | เมืองตาก | แม่น้ำปิง | HII | Ping Basin | yes | **yes** (13,070) | empty |
| `640` | เมืองสุโขทัย | แม่น้ำยม | HII | Yom Basin | yes | **yes** (12,621) | empty |
| `645` | กงไกรลาศ | แม่น้ำยม | HII | Yom Basin | yes | **yes** (12,961) | empty |
| `647` | ศรีสัชนาลัย | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,066) | empty |
| `653` | สวรรคโลก | แม่น้ำยม | HII | Yom Basin | yes | **yes** (12,934) | empty |
| `657` | เมืองพิษณุโลก | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,070) | empty |
| `658` | คลองผันน้ำยม-น่าน4 | แม่น้ำน่าน | HII | Yom Basin | yes | **yes** (13,069) | empty |
| `661` | นครไทย | น้ำแควน้อย | HII | Nan Basin | yes | **yes** (13,070) | empty |
| `664` | บางระกำ | แม่น้ำยม | HII | Yom Basin | yes | **yes** (12,954) | empty |
| `665` | ชุมแสงสงคราม | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,069) | empty |
| `667` | บางกระทุ่ม | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,067) | empty |
| `668` | สะพานนครป่าหมากร่วมใจ | คลองโกรงเกรง | HII | Nan Basin | yes | **yes** (13,065) | empty |
| `671` | คลองผันน้ำยม-น่าน2 | คลองเมม | HII | Yom Basin | yes | **yes** (13,066) | empty |
| `675` | วังทอง | แม่น้ำวังทอง | HII | Nan Basin | yes | **yes** (13,065) | empty |
| `676` | แม่น้ำเข็ก (ว้งทอง) | น้ำเข็ก | HII | Nan Basin | yes | **yes** (12,726) | empty |
| `680` | โพธิ์ประทับช้าง | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,064) | empty |
| `683` | ตะพานหิน | แม่น้ำน่าน | HII | Nan Basin | yes | **yes** (13,070) | empty |
| `691` | เมืองเพชรบูรณ์ | แม่น้ำป่าสัก | HII | Pasak Basin | yes | **yes** (13,037) | empty |
| `693` | หล่มสัก | แม่น้ำป่าสัก | HII | Pasak Basin | yes | **yes** (13,069) | empty |
| `700` | หนองไผ่ | แม่น้ำป่าสัก | HII | Pasak Basin | yes | **yes** (13,069) | empty |
| `706` | สวนผึ้ง | แม่น้ำภาชี | HII | Mae Klong Basin | yes | **yes** (13,037) | empty |
| `709` | บ้านโป่ง | แม่น้ำแม่กลอง | HII | Mae Klong Basin | yes | **yes** (13,064) | empty |
| `710` | โพธาราม | แม่น้ำแม่กลอง | HII | Mae Klong Basin | yes | **yes** (13,064) | empty |
| `714` | เมืองกาญจนบุรี | แม่น้ำแควใหญ่ | HII | Mae Klong Basin | yes | **yes** (13,063) | empty |
| `717` | ไทรโยค | แม่น้ำแควน้อย | HII | Mae Klong Basin | yes | **yes** (13,066) | empty |
| `731` | เมืองสุพรรณบุรี | แม่น้ำสุพรรณ | HII | Tha Chin Basin | yes | **yes** (13,059) | empty |
| `734` | ด่านช้าง | ห้วยกระเสียว | HII | Tha Chin Basin | yes | **yes** (13,069) | empty |
| `736` | สองพี่น้อง | คลองสองพี่น้อง | HII | Tha Chin Basin | yes | **yes** (13,067) | empty |
| `737` | วัดท่าเจดีย์ (TTC06) | แม่น้ำท่าจีน | HII | Tha Chin Basin | yes | **yes** (13,070) | empty |
| `738` | สามชุก | แม่น้ำท่าจีน | HII | Tha Chin Basin | yes | **yes** (13,069) | empty |
| `745` | บางเลน | แม่น้ำท่าจีน | HII | Tha Chin Basin | yes | **yes** (13,061) | empty |
| `747` | คลองนราภิรมย์ (บางเลน) | คลองนราภิรมย์ | HII | Chao Phraya Basin | yes | **yes** (13,037) | empty |
| `748` | สะพานนครชัยศรี | แม่น้ำท่าจีน | HII | Tha Chin Basin | yes | **yes** (13,061) | empty |
| `749` | ศาลาดิน | คลองหม่อมเจ้าเฉลิมศรี | HII | Tha Chin Basin | yes | **yes** (7,660) | empty |
| `750` | เมืองสมุทรสาคร | แม่น้ำท่าจีน | HII | Tha Chin Basin | yes | **yes** (13,067) | empty |
| `751` | คลองมหาชัย วัดพันท้ายนรสิงห์ | คลองสนามชัย | HII | Tha Chin Basin | yes | **yes** (13,069) | empty |
| `754` | บ้านแพ้ว | คลองดำเนินสะดวก | HII | Mae Klong Basin | yes | **yes** (13,034) | empty |
| `755` | พระรามสอง | แม่น้ำแม่กลอง | HII | Mae Klong Basin | yes | **yes** (13,068) | empty |
| `758` | เมืองเพชรบุรี | แม่น้ำเพชรบุรี | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,027) | empty |
| `770` | บางตะบูนและบางตะบูนออก | คลองบางตะบูน | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,061) | empty |
| `772` | แก่งกระจาน | ห้วยแม่ประจันต์ | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,060) | empty |
| `784` | ปราณบุรี | แม่น้ำปราณบุรี | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,064) | empty |
| `792` | เชียรใหญ่ | คลองชะอวด | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,037) | empty |
| `794` | ท่าศาลา | คลองกลาย | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,946) | empty |
| `795` | ทุ่งสง | คลองท่าเลา | HII | Peninsula - West Coast Basin | yes | **yes** (13,033) | empty |
| `802` | เมืองพังงา | คลองพังงา | HII | Peninsula - West Coast Basin | yes | **yes** (9,362) | empty |
| `804` | ตลาดเก่าตะกั่วป่า | คลองตะกั่วป่า | HII | Peninsula - West Coast Basin | yes | **yes** (13,035) | empty |
| `812` | ท่าขนอม | แม่น้ำพุมดวง | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,906) | empty |
| `823` | พุนพิน 1 | แม่น้ำตาปี | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,012) | empty |
| `824` | พุนพิน 3 | แม่น้ำตาปี | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,066) | empty |
| `825` | ชุมชนลีเล็ด | คลองลีเล็ด | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,062) | empty |
| `826` | พุนพิน 2 | แม่น้ำพุมดวง | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,952) | empty |
| `828` | วิภาวดี | คลองยัน | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,054) | empty |
| `829` | เมืองระนอง | คลองหาดส้มแป้น | HII | Peninsula - West Coast Basin | yes | **yes** (13,065) | empty |
| `835` | เมืองชุมพร | คลองท่าตะเภา | HII | Peninsula - Upper East Coast Basin | yes | **yes** (88) | empty |
| `841` | หลังสวน | คลองหลังสวน | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,922) | empty |
| `845` | สวี 1 | คลองสวี | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,917) | empty |
| `846` | สวี 2 | คลองสวี | HII | Peninsula - Upper East Coast Basin | yes | **yes** (7,558) | empty |
| `849` | จะนะ | คลองลึก | HII | Thale Sap Songkhla Basin | yes | **yes** (13,024) | empty |
| `850` | นาทวี | คลองนาทวี | HII | Thale Sap Songkhla Basin | yes | **yes** (13,026) | empty |
| `855` | สะเดา | คลองอู่ตะเภา | HII | Thale Sap Songkhla Basin | yes | **yes** (13,056) | empty |
| `858` | บางกล่ำ | คลองบางกล่ำ | HII | Thale Sap Songkhla Basin | yes | **yes** (10,899) | empty |
| `859` | ปากรอ | คลองปากรอ | HII | Thale Sap Songkhla Basin | yes | **yes** (13,059) | empty |
| `860` | คลองหอยโข่ง | คลองอู่ตะเภา | HII | Thale Sap Songkhla Basin | yes | **yes** (12,965) | empty |
| `861` | เมืองสตูล | คลองน้ำพระ | HII | Peninsula - West Coast Basin | yes | **yes** (12,925) | empty |
| `865` | เมืองตรัง | แม่น้ำตรัง | HII | Peninsula - West Coast Basin | yes | **yes** (12,933) | empty |
| `869` | ท่าสะบ้า | แม่น้ำตรัง | HII | Peninsula - West Coast Basin | yes | **yes** (13,007) | empty |
| `870` | คลองนาท่อม | คลองลำ | HII | Thale Sap Songkhla Basin | yes | **yes** (12,550) | empty |
| `901` | เมืองยะลา | เขื่อนปัตตานี | HII | Peninsula - Lower East Coast Basin | yes | **yes** (13,063) | empty |
| `905` | บันนังสตา | แม่น้ำปัตตานี | HII | Peninsula - Lower East Coast Basin | yes | **yes** (13,034) | empty |
| `922` | ศรีสาคร | แม่น้ำสายบุรี | HII | Peninsula - Lower East Coast Basin | yes | **yes** (12,605) | empty |
| `2559` | บริเวณสะพานลันตู | แม่น้ำโก-ลก | RID | Peninsula - Lower East Coast Basin | yes | **yes** (147) | **yes** (147) |
| `2561` | บ้านวังพระเคียน | คลองละงู | RID | Peninsula - West Coast Basin | yes | **yes** (74) | **yes** (74) |
| `2562` | บ้านย่านตาขาว | คลองปะเหลียน | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2563` | บ้านท่าแค | คลองท่าแค | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `2565` | บ้านบางตง | คลองพังงา | RID | Peninsula - West Coast Basin | yes | **yes** (1,549) | empty |
| `2567` | บ้านวังไผ่ | คลองชุมพร | RID | Peninsula - Upper East Coast Basin | yes | **yes** (1,959) | empty |
| `2568` | บ้านศรีบัวทอง | แม่น้ำเขาสมิง | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `2569` | บ้านสองพี่น้อง | แม่น้ำเพชรบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `2571` | บ้านวังเย็น | แม่น้ำแควน้อย | RID | Mae Klong Basin | yes | **yes** (151) | **yes** (151) |
| `2572` | บ้านลุ่มสุ่ม | แม่น้ำแควน้อย | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `2573` | บ้านน้ำโจน | ห้วยแม่น้ำน้อย | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `2575` | ประปายโสธร | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (1,542) | empty |
| `2576` | ต.ตาลเดี่ยว | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (161) | **yes** (161) |
| `2578` | บ้านสบวิน | น้ำแม่วาง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `2579` | บ้านร่องเคาะ | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `2580` | บ้านโป่งปูเฟือง | น้ำแม่ลาว | RID | North Khong Basin | yes | **yes** (159) | **yes** (159) |
| `2581` | บ้านซากอ | แม่น้ำสายบุรี | RID | Peninsula - Lower East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2582` | บ้านตันหยงมัส | คลองตันหยงมัส | RID | Peninsula - Lower East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2583` | บ้านท่าสาบ | แม่น้ำปัตตานี | RID | Peninsula - Lower East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2584` | บ้านฉลุงเหนือ | คลองน้ำพระ | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2585` | บ้านม่วงก็อง | คลองอู่ตะเภา | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `2587` | สะพานเดชานุชิต | แม่น้ำปัตตานี | RID | Peninsula - Lower East Coast Basin | yes | **yes** (1,975) | empty |
| `2589` | บ้านบางศาลา | คลองอู่ตะเภา | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `2590` | บ้านคลองหวะ | คลองหวะ | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `2591` | บ้านหาดใหญ่ใน | คลองอู่ตะเภา | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `2594` | บ้านแม่ขรี | คลองท่าเชียด | RID | Thale Sap Songkhla Basin | yes | **yes** (7) | **yes** (1) |
| `2596` | บ้านท่าจีน | แม่น้ำตรัง | RID | Peninsula - West Coast Basin | yes | **yes** (1,975) | empty |
| `2597` | บ้านคลองลำ | คลองลำ | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `2599` | กรมชลประทานสามเสน | แม่น้ำเจ้าพระยา | RID | Chao Phraya Basin | yes | **yes** (1,583) | empty |
| `2607` | สะพานปรีดี-ธำรง | แม่น้ำป่าสัก | RID | Chao Phraya Basin | yes | **yes** (1,583) | empty |
| `2608` | บ้านบางบาล | คลองบางบาล | RID | Chao Phraya Basin | yes | **yes** (1,583) | empty |
| `2609` | บ้านป้อม | แม่น้ำเจ้าพระยา | RID | Chao Phraya Basin | yes | **yes** (1,583) | empty |
| `2611` | บ้านบางหลวงโดด | แม่น้ำน้อย | RID | Chao Phraya Basin | yes | **yes** (1,583) | empty |
| `2618` | บ้านวังตะเคียนทอง | ลำพระเพลิง | RID | Mun Basin | yes | **yes** (7) | **yes** (7) |
| `2620` | บ้านโนนสาวเอ้ | ลำพระเพลิง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2621` | บ้านท่ามะปรางค์ | คลองลำตะคอง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2623` | สถานีแพดับเพลิง | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (1,583) | empty |
| `2624` | ท้ายเขื่อนพระรามหก | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (1,583) | empty |
| `2626` | บ้านบางแก้ว | แม่น้ำเจ้าพระยา | RID | Chao Phraya Basin | yes | **yes** (161) | **yes** (29) |
| `2632` | บ้านป่า | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (1,583) | empty |
| `2634` | บ้านป่าหมาก | แม่น้ำตรัง | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2635` | หน้าวัดภูผาพิมุข | คลองบ้านแร่ | RID | Thale Sap Songkhla Basin | yes | **yes** (1,975) | empty |
| `2636` | บ้านท่าประดู่ | แม่น้ำตรัง | RID | Peninsula - West Coast Basin | yes | **yes** (129) | **yes** (129) |
| `2638` | บ้านเก็ตโฮ่ | คลองเก็ตโฮ | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (43) |
| `2639` | บ้านนาป่า | คลองท่าดี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2641` | บ้านวังไทร | คลองท่าดี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2643` | บ้านย่านดินแดง | แม่น้ำตาปี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2644` | บ้านท้า่ยนา | คลองกลาย | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (79) |
| `2645` | บ้านหินดาน | คลองตะกั่วป่า | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2647` | บ้านตลาดเก่า | คลองตะกั่วป่า | RID | Peninsula - West Coast Basin | yes | **yes** (1,975) | empty |
| `2648` | บ้านเคียนซา | แม่น้ำตาปี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2650` | ถนนลูกเสือ | คลองหลังสวน | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2651` | คลองหาดส้มแป้น | คลองหาดส้มแป้น | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2654` | สะพานเทศบาล 2 | คลองท่าตะเภา | RID | Peninsula - Upper East Coast Basin | yes | **yes** (1,975) | empty |
| `2655` | บ้านวังครก | คลองท่าตะเภา | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `2656` | บ้านท่าแซะ | คลองท่าแซะ | RID | Peninsula - Upper East Coast Basin | — | **yes** (45) | **yes** (45) |
| `2658` | บ้านหนองหญ้าปล้อง | คลองหนองหญ้าปล้อง | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `2659` | บ้านกลาง | คลองทับสะแก | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (120) |
| `2661` | บ้านเขาสมิง | แม่น้ำเขาสมิง | RID | East Coast Gulf Basin | yes | **yes** (2,071) | empty |
| `2662` | สะพานวัดจันทนาราม | คลองจันทบุรี | RID | East Coast Gulf Basin | yes | **yes** (2,089) | empty |
| `2663` | บ้านฉมัน | คลองฉมัน | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `2664` | บ้านปึก | คลองจันทบุรี | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `2665` | บ้านโป่งโรงเซ็น | คลองทับนคร | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `2666` | บ้านโพรงเข้ | ห้วยผาก | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (1,922) | empty |
| `2668` | บ้านซำฆ้อ | คลองโพล้ | RID | East Coast Gulf Basin | yes | **yes** (88) | empty |
| `2669` | บ้านเขาวังไทร | แม่น้ำประแสร์ | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `2671` | ตลาดท่ายาง | แม่น้ำเพชรบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `2672` | บ้านขุนซ่อง | คลองโตนด | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `2675` | บ้านเขาฉกรรจ์ | คลองพระสะทึง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `2676` | ที่ว่าการอ.นครชัยศรี | แม่น้ำท่าจีน | RID | Tha Chin Basin | yes | **yes** (1,980) | empty |
| `2677` | บ้านเนินผาสุก | คลองพระสะทึง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `2679` | บ้านวังขนาย | แม่น้ำแม่กลอง | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `2680` | สะพานต้นน้ำบางปะกง | แม่น้ำบางปะกง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `2682` | บ้านหนองบัว | แม่น้ำแควใหญ่ | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `2683` | สะพานณรงค์ดำริ | แม่น้ำบางปะกง | RID | Bang Pakong Basin | yes | **yes** (2,074) | empty |
| `2686` | บ้านทุ่งนานางหรอก | ลำตะเพิน | RID | Mae Klong Basin | yes | **yes** (1,987) | **yes** (866) |
| `2687` | บ้านเขานางบวช | แม่น้ำนครนายก | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `2688` | บ้านบ้องตี้น้อย | ห้วยบ้องตี้ | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `2689` | บ้านป่าขะ | คลองห้วยถ่าน | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (80) |
| `2694` | บ้านท่าเยี่ยม | ลำพระเพลิง | RID | Mun Basin | yes | **yes** (1,778) | empty |
| `2695` | บ้านวังชมภู | ห้วยขะยุง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2698` | สำนักเทคโนโลยีชีวภัณฑ์สัตว์ | คลองลำตะคอง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2700` | บ้านโนนสะอาด | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2707` | บ้านคำสำราญ | ลำโดมใหญ่ | RID | Mun Basin | yes | **yes** (151) | **yes** (151) |
| `2712` | ท้ายเขื่อนป่าสักชลสิทธิ์ | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (161) | **yes** (161) |
| `2713` | บ้านลาดบัวขาว | ลำตะคอง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2714` | ศูนย์วิจัยและพัฒนาประมงน้ำจืดสุรินทร์ | ห้วยเสนง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2723` | บ้านบางพุทรา | แม่น้ำเจ้าพระยา | RID | Chao Phraya Basin | yes | **yes** (161) | **yes** (29) |
| `2725` | บ้านด่านกะตา | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (138) | **yes** (91) |
| `2726` | ตำบลในเมือง | ลำตะคองเก่า | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2729` | บ้านโนนสีไคล | ห้วยขะยุง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2731` | บ้านเขวา | ห้วยสำราญ | RID | Mun Basin | yes | **yes** (1,778) | empty |
| `2737` | ชุมชนสะพานขาว | ห้วยสำราญ | RID | Mun Basin | yes | **yes** (1,778) | empty |
| `2739` | บ้านสีถาน | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2740` | บ้านหลุมดิน | ลำชี | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2744` | ท้ายเขื่อนเจ้าพระยา | แม่น้ำเจ้าพระยา | RID | Chao Phraya Basin | yes | **yes** (161) | **yes** (161) |
| `2750` | บ้านซึม | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2752` | สะพานเสรีประชาธิปไตย | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2755` | บ้านโพธิ์ตาก | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2760` | บ้านสตึก | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2763` | บ้านพงสวาย | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2764` | บ้านเมืองคง | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2770` | บ้านหาดทนง | แม่น้ำสะแกกรัง | RID | Sakae Krang Basin | yes | **yes** (1,583) | empty |
| `2773` | บ้านวังปลัด | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2777` | บ้านดอนใหญ่ | น้ำตากแดด | RID | Sakae Krang Basin | yes | **yes** (1,583) | empty |
| `2780` | บ้านท่าบอแบง | ลำเซบก | RID | Mun Basin | yes | **yes** (123) | **yes** (123) |
| `2781` | บ้านบุ่งอ้ายเจี้ยม | ห้วยทับเสลา | RID | Sakae Krang Basin | yes | **yes** (1,583) | empty |
| `2782` | บ้านฟ้าหยาด | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2795` | ค่ายจิรประวัติ | แม่น้ำเจ้าพระยา | RID | Chao Phraya Basin | yes | **yes** (161) | **yes** (161) |
| `2797` | บ้านค่าย | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2799` | บ้านบ่อวัง | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (161) | **yes** (161) |
| `2808` | บ้านแก่งโก | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2809` | บ้านโนนเชือก | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2811` | บ้านศาลเจ้าไก่ต่อ | แม่น้ำวังม้า | RID | Sakae Krang Basin | yes | **yes** (1,571) | empty |
| `2814` | บ้านนิคม | ลำโพง | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2820` | บ้านเชียงเพ็ง | ลำเซบาย | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `2821` | วัดเกยไชยเหนือ | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `2828` | บ้านหนองอ้อ | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2830` | บ้านปางมะค่า | แม่น้ำแม่วงก์ | RID | Sakae Krang Basin | yes | **yes** (1,583) | empty |
| `2832` | บ้านท่างิ้ว | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `2836` | บ้านตาดโตน | ห้วยตาดโตน | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2845` | บ้านท่าสะแบง | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2847` | บ้านแสนตอ | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `2851` | หน้าอำเภอโพทะเล | แม่น้ำยม | RID | Yom Basin | yes | **yes** (2,025) | **yes** (4) |
| `2852` | บ้านท่านางเลื่อน | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2855` | บ้านสามเรือน | คลองขลุง | RID | Ping Basin | yes | **yes** (159) | **yes** (159) |
| `2857` | บ้านม่วงลาด | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2860` | หน้าวัดศรีภิรมย์ | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `2863` | บ้านดินดำ | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2867` | บ้านกุดก่วง | ลำน้ำยัง | RID | Chi Basin Basin | yes | **yes** (159) | **yes** (159) |
| `2869` | บ้านวังโป่ง | คลองวังโปง | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `2872` | บ้านวังหิน | ลำปาว | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2874` | บ้านกุดกว้าง | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2875` | บ้านดอนขนวน | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2881` | ต.ในเมือง | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (161) | **yes** (161) |
| `2888` | บ้านแก่งยาว | ลำน้ำยัง | RID | Chi Basin Basin | yes | **yes** (154) | **yes** (154) |
| `2895` | บ้านราชช้างขวัญ | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `2900` | ต.ในเมือง | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (156) |
| `2905` | บ้านยาง | ห้วยหิน | RID | Chi Basin Basin | yes | **yes** (7) | **yes** (7) |
| `2906` | สามง่าม | แม่น้ำยม | RID | Yom Basin | yes | **yes** (2,026) | empty |
| `2914` | คลองวังเจ้า | คลองวังเจ้า | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `2915` | บ้านทานตะวัน | น้ำเข็ก | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `2918` | บ้านหนองม่วง | ลำปาว | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2920` | บ้านโนนหัน | ลำเชิญ | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2924` | บ้านท่าเม่า | ลำน้ำพอง | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2925` | บ้านหนองริวหนัง | ห้วยลำหนองแสน | RID | Chi Basin Basin | yes | **yes** (8) | **yes** (8) |
| `2941` | บางระกำ | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `2948` | เนินยางใต้ | ห้วยสังเคียบ | RID | Chi Basin Basin | yes | **yes** (7) | **yes** (7) |
| `2953` | สะพานสุพรรณกัลยา  | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `2957` | บ้านดงสวรรค์ | ห้วยมูล | RID | Chi Basin Basin | yes | **yes** (8) | **yes** (8) |
| `2963` | บ้านท่าแค | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `2964` | บ้านโพน | ห้วยสังกะ | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2972` | บ้านกง | แม่น้ำยม | RID | Yom Basin | yes | **yes** (1,997) | empty |
| `2975` | บ้านท่าไฮ | ห้วยลำปาว | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2976` | บ้านท่างาม | ลำพันชาด | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `2985` | ต.ตาดกลอย | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (161) | **yes** (161) |
| `2986` | ต.ธานี | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `2993` | ท้ายเขื่อนนเรศวร | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3000` | บ้านตองโขบ | ลำน้ำพุง | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3002` | บ้านข้องโป้ | ลำพะเนียง | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `3003` | บ้านหนองกระท้าว | น้ำแควน้อย | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3014` | บ้านแก่งบง | แม่น้ำเลย | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3017` | บ้านคลองตาล | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3018` | บ้านวังหมัน | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3025` | บ้านย่านรี | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3029` | บ้านท่าสะแก | น้ำภาค | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3032` | บ้านหนองวัวซอ | ห้วยหลวง | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (159) |
| `3041` | บ้านวังขอนไม้ | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3044` | บ้านนาหลัก | แม่น้ำเลย | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3047` | บ้านท่าไผ่ | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3049` | ห้วยแม่มอก | ห้วยแม่มอก | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3059` | บ้านแม่เชียงราย | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3065` | บ้านเด่นสำโรง | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3076` | บ้านโนนตูม | ห้วยหลวง | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3082` | บ้านฟากเลย | แม่น้ำเลย | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3085` | บ้านโคกคำไหล | แม่น้ำสงคราม | RID | Northeast Khong Basin | yes | **yes** (139) | **yes** (139) |
| `3095` | ต.ในเมือง | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3102` | บ้านดอนชัย | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3107` | บ้านหาดไผ่ | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3112` | บ้านหลวง | น้ำแม่ตื่น | RID | Ping Basin | yes | **yes** (37) | **yes** (7) |
| `3113` | ห้วยแม่สิน | ห้วยแม่สิน | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3117` | บ้านท่าห้วยหลัว | แม่น้ำสงคราม | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3122` | บ้านท่ากกแดง | แม่น้ำสงคราม | RID | Northeast Khong Basin | yes | **yes** (160) | **yes** (160) |
| `3127` | บ้านวังชิ้น | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3134` | บ้านฟากท่า | น้ำปาด | RID | Nan Basin | yes | **yes** (2,024) | empty |
| `3146` | บ้านน้ำโค้ง | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3149` | บ้านแม่อีไฮ | น้ำแม่ลี้ | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3152` | บ้านวังพร้าว | แม่น้ำจาง | RID | Wang Basin | yes | **yes** (155) | **yes** (155) |
| `3154` | บ้านเกาะคา | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (1,410) | empty |
| `3156` | สะพานท่าข้าม | น้ำแม่แจ่ม | RID | Ping Basin | yes | **yes** (155) | **yes** (155) |
| `3157` | บ้านแม่หล่าย | น้ำแม่หล่าย | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3163` | บ้านแม่คำมีตำหนักธรรม | น้ำแม่คำมี | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3164` | บ้านสบสอย | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (1,522) | empty |
| `3168` | สะพานเสตุวารี | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3171` | บ้านท่าล้อ | น้ำแม่ตุ๋ย | RID | Wang Basin | yes | **yes** (155) | **yes** (155) |
| `3172` | บ้านท่าเดื่อ | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (155) | **yes** (155) |
| `3174` | บ้านหล่ายแก้ว | น้ำแม่ลี้ | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3186` | บ้านสบแม่สะป๊วด | น้ำแม่ทา | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3205` | บ้านห้วยสัก | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3212` | บ้านโป่ง | น้ำแม่กวง | RID | Ping Basin | yes | **yes** (160) | **yes** (160) |
| `3213` | บ้านโป่ง | น้ำแม่หวด | RID | Yom Basin | yes | **yes** (7) | **yes** (7) |
| `3215` | บ้านหนองนาว | ห้วยเก้า | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3217` | บ้านหลวงเหนือ | น้ำแม่งาว | RID | Yom Basin | yes | **yes** (160) | **yes** (160) |
| `3219` | หน้าสำนักงานป่าไม้ | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3220` | บ้านป่าซาง | น้ำแม่ทา | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3221` | สะพานท่าลี่ | แม่น้ำน้ำว้า | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3222` | บ้านพันตน | น้ำแม่วาง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3223` | บ้านโห้ง | เหมืองฮอ | RID | Ping Basin | yes | **yes** (155) | **yes** (155) |
| `3224` | บ้านไฮ | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `3226` | สะพานนวรัฐ | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3233` | บ้านมาง | น้ำปี้ | RID | Yom Basin | yes | **yes** (149) | **yes** (149) |
| `3237` | บ้านโป่งดิน | ห้วยแม่วะ | RID | Ping Basin | yes | **yes** (155) | **yes** (155) |
| `3240` | บ้านริมใต้ | น้ำเหมือง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3243` | บ้านทุ่งหนอง | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `3244` | บ้านแม่หวาน | น้ำแม่กวง | RID | Ping Basin | yes | **yes** (155) | **yes** (155) |
| `3245` | บ้านน้ำยาว | น้ำยาว | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3246` | บ้านผาขวาง | แม่น้ำน่าน | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3247` | บ้านแม่แต | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3251` | บ้านแม่แตง | แม่น้ำแม่แตง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3253` | บ้านช่อแล | เหมืองสายล่าง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3267` | บ้านปางสา | น้ำยาว | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3269` | บ้านสหกรณ์ร่มเกล้า | น้ำแม่งัด | RID | Ping Basin | yes | **yes** (7) | **yes** (7) |
| `3271` | บ้านเชียงดาว | ห้วยแม่มาด | RID | Ping Basin | yes | **yes** (160) | **yes** (160) |
| `3281` | บ้านเมืองมาย | ห้วยแม่คิ | RID | Wang Basin | yes | **yes** (152) | **yes** (152) |
| `3283` | บ้านกลาง | น้ำแม่ขาน | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3285` | บ้านสลวงนอก | น้ำแม่ริม | RID | Ping Basin | yes | **yes** (7) | **yes** (7) |
| `3286` | บ้านเมืองกึ๊ด | แม่น้ำแม่แตง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `3288` | บ้านสันปู่เลย | น้ำแม่ขอด | RID | Ping Basin | yes | **yes** (155) | **yes** (155) |
| `3292` | บ้านท่างาม | น้ำแควน้อย | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3294` | บ้านท่าโป่งแดง | แม่น้ำปาย | RID | Salawin Basin | yes | **yes** (20) | **yes** (20) |
| `3295` | บ้านวังนกแอ่น | น้ำเข็ก | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `3296` | บ้านเจดีย์งาม | ร่องค้าน | RID | North Khong Basin | yes | **yes** (7) | **yes** (7) |
| `3298` | บ้านดอนสลี | น้ำแม่ลาว | RID | North Khong Basin | yes | **yes** (7) | **yes** (7) |
| `3299` | บ้านกระเหรี่ยงทุ่งพร้าว | น้ำแม่สรวย | RID | North Khong Basin | yes | **yes** (7) | **yes** (7) |
| `3303` | บ้านหัวสะพาน | น้ำแม่จัน | RID | North Khong Basin | yes | **yes** (159) | **yes** (159) |
| `3304` | บ้านแม่คำหลักเจ็ด | แม่น้ำคำ | RID | North Khong Basin | yes | **yes** (159) | **yes** (159) |
| `3441` | น้ำพรม อ.เกษตรสมบูรณ์ | น้ำพรม | EGAT | Chi Basin Basin | yes | **yes** (168) | **yes** (168) |
| `3459` | ลำเชิญ อ.ชุมแพ (ท้ายฝายโครงการชลประทานน้ำเชิญ) | ห้วยพรม | EGAT | Chi Basin Basin | yes | **yes** (85) | **yes** (85) |
| `3476` | แม่น้ำมูล วัดปากโดม | แม่น้ำมูล | EGAT | Mun Basin | yes | **yes** (1,963) | empty |
| `3509` | น้ำพอง อ.สีชมพู | ลำน้ำพอง | EGAT | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `3510` | ลำพะเนียง อ.เมือง | ลำพะเนียง | EGAT | Chi Basin Basin | yes | **yes** (168) | **yes** (168) |
| `3519` | น้ำพอง บ้านผานกเค้า (E.29) | น้ำพอง | EGAT | Chi Basin Basin | yes | **yes** (168) | **yes** (168) |
| `3523` | ลำน้ำพอง (เหนือฝายหนองหวาย) | ลำน้ำพอง | EGAT | Chi Basin Basin | yes | **yes** (2,184) | empty |
| `3524` | ลำน้ำพอง โรงเรียนลำน้ำพอง | ลำน้ำพอง | EGAT | Chi Basin Basin | yes | **yes** (168) | **yes** (168) |
| `3525` | แม่น้ำชี บ้านหินกอง | แม่น้ำชี | EGAT | Chi Basin Basin | yes | **yes** (168) | **yes** (168) |
| `3526` | แม่น้ำชี ฝายมหาสารคาม(เหนือ) | แม่น้ำชี | EGAT | Chi Basin Basin | yes | **yes** (2,184) | empty |
| `3529` | แม่น้ำมูล อ.ราษีไศล (M.5) | แม่น้ำมูล | EGAT | Mun Basin | yes | **yes** (2,184) | empty |
| `3531` | แม่น้ำมูล ท้ายแก่งสะพือ (M.11B) | แม่น้ำมูล | EGAT | Mun Basin | yes | **yes** (2,184) | empty |
| `3533` | ลำโดมใหญ่ บ้านนาเยีย | ลำโดมใหญ่ | EGAT | Mun Basin | yes | **yes** (2,184) | empty |
| `3542` | แม่น้ำมูล บ้านคันไร่ | แม่น้ำมูล | EGAT | Mun Basin | yes | **yes** (1,250) | empty |
| `3543` | แม่น้ำมูล เมืองอุบลราชธานี (M.7) | แม่น้ำมูล | EGAT | Mun Basin | yes | **yes** (2,184) | empty |
| `3544` | หน้าเขื่อนปากมูล | แม่น้ำมูล | EGAT | Mun Basin | yes | **yes** (2,184) | empty |
| `12349` | ควนกาหลง | คลองลำโลน | HII | Peninsula - West Coast Basin | yes | **yes** (13,018) | empty |
| `12350` | รัษฎา | แม่น้ำตรัง | HII | Peninsula - West Coast Basin | yes | **yes** (13,052) | empty |
| `12474` | มะนัง | คลองละงู | HII | Peninsula - West Coast Basin | yes | **yes** (13,047) | empty |
| `12475` | ปะเหลียน | คลองปะเหลียน | HII | Peninsula - West Coast Basin | yes | **yes** (5,365) | empty |
| `12476` | ลิ่นถิ่น | แม่น้ำแควน้อย | HII | Mae Klong Basin | yes | **yes** (13,066) | empty |
| `12477` | หัวหิน | ห้วยมงคล | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,034) | empty |
| `12478` | ท่ายาง | แม่น้ำเพชรบุรี | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,055) | empty |
| `12479` | คลองขนาน | คลองบางสะพาน | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (10,601) | empty |
| `12480` | คลองนางน้อย | คลองนางน้อย | HII | Peninsula - West Coast Basin | yes | **yes** (11,818) | empty |
| `12481` | ละงู | คลองละงู | HII | Peninsula - West Coast Basin | yes | **yes** (13,051) | empty |
| `12483` | ถ้ำพรรณรา | แม่น้ำตาปี | HII | Peninsula - Upper East Coast Basin | yes | **yes** (8,404) | empty |
| `12484` | พระแสง | คลองอิปัน | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,836) | empty |
| `12485` | ทุ่งใหญ่ | คลองสินปุน | HII | Peninsula - Upper East Coast Basin | — | **yes** (9,429) | empty |
| `13892` | ฝายคลองท่าเลา | คลองท่าเลา | HII | Peninsula - West Coast Basin | yes | **yes** (4,157) | empty |
| `13906` | วังวิเศษ | คลองยวนปลา | HII | Peninsula - West Coast Basin | yes | **yes** (12,931) | empty |
| `385579` | ฝ่ายส่งน้ำและบำรุงรักษาที่ 2 | น้ำแม่ดู | HII | Ping Basin | yes | **yes** (13,068) | empty |
| `385582` | สะพานข้ามลำปะเทีย | ลำปะเทีย | HII | Mun Basin | yes | **yes** (4,443) | empty |
| `385586` | สะพานมิตรภาพรับร่อ-หินแก้ว | คลองรับรอ | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,060) | empty |
| `471583` | คลองช่องสะเดา | คลองช่องสะเดา | HII | Chao Phraya Basin | yes | **yes** (13,041) | empty |
| `479230` | สะพานแม่ฟ้าหลวง | แม่น้ำกก | HII | North Khong Basin | yes | **yes** (13,065) | empty |
| `479231` | คลองแม่พุง | น้ำแม่พุง | HII | North Khong Basin | yes | **yes** (13,061) | empty |
| `479232` | สะพานอิงอุดม | แม่น้ำอิง | HII | North Khong Basin | yes | **yes** (13,070) | empty |
| `479233` | คลองปาว | ลำปาว | HII | Chi Basin Basin | yes | **yes** (13,037) | empty |
| `479234` | ห้วยยัง | ลำพะยัง | HII | Chi Basin Basin | yes | **yes** (13,060) | empty |
| `479235` | ลำน้ำอูน | ลำน้ำอูน | HII | Northeast Khong Basin | yes | **yes** (13,034) | empty |
| `479236` | บ้านโพธิ์ชัยทอง | ลำน้ำยาม | HII | Northeast Khong Basin | yes | **yes** (12,796) | empty |
| `479237` | ลำน้ำยัง | ลำน้ำยัง | HII | Chi Basin Basin | — | **yes** (2,403) | empty |
| `479238` | ลำน้ำพุง | ลำน้ำพุง | HII | Northeast Khong Basin | yes | **yes** (13,004) | empty |
| `479240` | ลำน้ำก่ำ | ลำน้ำกำ | HII | Northeast Khong Basin | — | **yes** (8,539) | empty |
| `479241` | ลำเซบาย | ลำเซบาย | HII | Mun Basin | yes | **yes** (13,058) | empty |
| `504679` | สะพานวงแหวนรอบ 3 | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `504708` | บ้านสบแปะ | แม่น้ำปิง | RID | Ping Basin | yes | **yes** (161) | **yes** (161) |
| `504897` | บางระกำ | แม่น้ำยม | RID | Yom Basin | yes | **yes** (161) | **yes** (161) |
| `504940` | บ้านเขื่องใน | แม่น้ำชี | RID | Chi Basin Basin | — | **yes** (63) | **yes** (63) |
| `504945` | บ้านโคกกรวด | คลองมอญ | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `504962` | บ้านป่าก่อ | ลำเซบาย | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `504982` | บ้านพูลทรัพย์ | แม่น้ำป่าสัก | RID | Pasak Basin | yes | **yes** (161) | **yes** (161) |
| `504990` | บ้านทาม | แม่น้ำบางปะกง | RID | Bang Pakong Basin | yes | **yes** (2,091) | empty |
| `504994` | บ้านโนนสุขภูมิ | คลองพระปรง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `504997` | บ้านท่าบุญมี | คลองท่าบุญมี | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `504999` | บ้านนาแขม | แควหนุมาน | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `505003` | สะพานหน้าจวนผู้ว่าฯ | แม่น้ำนครนายก | RID | Bang Pakong Basin | yes | **yes** (2,091) | empty |
| `505011` | บ้านเขาโบสถ์ | คลองกระเฉด | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `505018` | บ้านปากแซง | แม่น้ำแควน้อย | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `505025` | สะพานข้ามแม่น้ำแม่กลองหน้าศาลากลางจ.กาญจนบุรี | แม่น้ำแม่กลอง | RID | Mae Klong Basin | yes | **yes** (1,987) | empty |
| `505027` | บ้านสาระเห็ด | แม่น้ำเพชรบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `505029` | สะพานบ้านลาด | แม่น้ำเพชรบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `505030` | ข้างจวนผู้ว่าฯ | แม่น้ำเพชรบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (1,987) | empty |
| `505037` | สะพานรถยนต์ ร.ร.อนุบาลบางสะพาน | คลองบางกระจอง | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (1,973) | empty |
| `505038` | บ้านวัดพระรูป | แม่น้ำสุพรรณ | RID | Tha Chin Basin | yes | **yes** (1,974) | empty |
| `505039` | บ้านบางการ้อง | แม่น้ำท่าจีน | RID | Tha Chin Basin | yes | **yes** (1,540) | empty |
| `505041` | ร.ร.บ้านสามพราน | แม่น้ำท่าจีน | RID | Tha Chin Basin | yes | **yes** (1,987) | empty |
| `505050` | บ้านบูเก๊ะตา | แม่น้ำโก-ลก | RID | Peninsula - Lower East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `505052` | บ้านมูโน๊ะ | แม่น้ำโก-ลก | RID | Peninsula - Lower East Coast Basin | yes | **yes** (1,975) | empty |
| `505056` | บ้านท่าข้าม | แม่น้ำตาปี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (1,975) | empty |
| `505069` | บ้านปะเหลียนใน | คลองปะเหลียน | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `505072` | ชุมชนประชาบำรุง | คลองละงู | RID | Peninsula - West Coast Basin | yes | **yes** (1,975) | empty |
| `508035` | บ้านผานกเค้า | น้ำพอง | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `516210` | ลำน้ำขว้าง (ฝายจ้าว) | น้ำขว้าง | FiN | Nan Basin | — | **yes** (10,179) | empty |
| `516213` | ลำน้ำกูน | น้ำคูณ | FiN | Nan Basin | yes | **yes** (12,918) | empty |
| `516216` | สะพานน้ำมวบ (บ้านภูแยง) | น้ำมวบ | FiN | Nan Basin | yes | **yes** (12,907) | empty |
| `516218` | บ้านตอง | น้ำมวบ | FiN | Nan Basin | yes | **yes** (12,764) | empty |
| `527828` | บ้านชมพู | คลองชมพู | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `528052` | วัดบางไผ่นารถ | แม่น้ำท่าจีน | RID | Tha Chin Basin | yes | **yes** (1,830) | empty |
| `529399` | สะพานลำน้ำยาม | ลำน้ำยาม | FiN | Northeast Khong Basin | yes | **yes** (12,900) | empty |
| `558654` | น้ำพรม บ้านกุดเลาะ     | น้ำพรม | EGAT | Chi Basin Basin | yes | **yes** (2,184) | empty |
| `558658` | เขื่อนน้ำพุง บ้านคำเพิ่ม  | ห้วยน้ำพุง | EGAT | Northeast Khong Basin | yes | **yes** (2,184) | empty |
| `558661` | วัดศิริมังคละเต่างอย  | ลำน้ำพุง | EGAT | Northeast Khong Basin | yes | **yes** (2,180) | empty |
| `562796` | สะพานบ้าน กม.29 อ.เบตง จ.ยะลา | แม่น้ำปัตตานี | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (168) | **yes** (168) |
| `562799` | สะพานท้ายเขื่อนบางลาง อ.บันนังสตา จ.ยะลา | แม่น้ำปัตตานี | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (168) | **yes** (168) |
| `562800` | สะพานหัวสะพาน อ.บันนังสตา จ.ยะลา | แม่น้ำปัตตานี | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (2,184) | empty |
| `562802` | อาคารสูบน้ำดิบ กปภ. อ.ยะหา จ.ยะลา | คลองเล็ก | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (2,184) | empty |
| `562803` | สะพานเมืองปัตตานี อ.เมือง จ.ปัตตานี | แม่น้ำปัตตานี | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (2,184) | empty |
| `562804` | ฝายละแอ อ.บันนังสตา จ.ยะลา | คลองละแอ | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (2,184) | empty |
| `562808` | เขื่อนบางลาง อ.บันนังสตา จ.ยะลา | แม่น้ำปัตตานี | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (2,184) | empty |
| `575565` | สวนศรีนครเขื่อนขันธ์ | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | — | **yes** (5,063) | empty |
| `575566` | ปตร.วัดบางกระเจ้านอก | คลองบางกะเจ้า | HII | Chao Phraya Basin | yes | **yes** (12,608) | empty |
| `575567` | ปตร. คลองลัดบางยอ 1 | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (11,819) | empty |
| `575568` | ปตร. คลองลัดบางยอ 2 | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | yes | **yes** (11,463) | empty |
| `575569` | ปตร. คลองตาสด | แม่น้ำเจ้าพระยา | HII | Chao Phraya Basin | — | **yes** (9,969) | empty |
| `595071` | สะพานน้ำแม่สา | น้ำแม่สา | FiN | Ping Basin | yes | **yes** (13,041) | empty |
| `595072` | สะพานห้วยแม่ตาช้าง | ห้วยแม่ท่าช้าง | FiN | Ping Basin | yes | **yes** (10,511) | empty |
| `632505` | บ้านแก่งบัวคำ | น้ำแควน้อย | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `632511` | ต.น้ำปาด | น้ำปาด | RID | Nan Basin | yes | **yes** (161) | **yes** (161) |
| `638734` | คลองแม่รำพัน 1 | คลองแม่รำพัน | FiN | Yom Basin | yes | **yes** (12,767) | empty |
| `642740` | สะพานห้วยแม่สาว | น้ำแม่สาว | FiN | North Khong Basin | yes | **yes** (13,033) | empty |
| `642750` | สะพานแม่น้ำน่าน บ้านเปียงก่อ | น้ำราง | FiN | Nan Basin | yes | **yes** (13,020) | empty |
| `642753` | สะพานน้ำขว้าง บ้านร้องแง | น้ำขว้าง | FiN | Nan Basin | yes | **yes** (13,016) | empty |
| `648042` | สะพานน้ำยาว บ้านสองแคว | น้ำยาว | FiN | Nan Basin | yes | **yes** (13,062) | empty |
| `670714` | ลำน้ำกวงสะพานศรีดอนชัย | น้ำแม่กวง | FiN | Ping Basin | yes | **yes** (13,021) | empty |
| `670715` | ลำน้ำสานบ้านทุ่งยาวเหนือ | น้ำแม่สาร | FiN | Ping Basin | yes | **yes** (13,029) | empty |
| `685637` | สะพานน้ำกอน บ้านพญาแก้ว | น้ำกอน | FiN | Nan Basin | yes | **yes** (13,023) | empty |
| `685638` | สะพานแม่น้ำว้า บ้านบ่อหยวก | น้ำว้า | FiN | Nan Basin | — | **yes** (8,486) | empty |
| `685643` | สะพานห้วยน้ำสาย | น้ำสบสาย | FiN | Nan Basin | yes | **yes** (12,802) | empty |
| `685650` | สะพานน้ำว้า บ้านน้ำว้า | แม่น้ำน้ำว้า | FiN | Nan Basin | yes | **yes** (11,628) | empty |
| `685653` | สะพานห้วยแม่ถาบ้านปาหุ่ง | ห้วยแม่ถา | FiN | Nan Basin | yes | **yes** (12,970) | empty |
| `685658` | สะพานน้ำมวบ บ้านน้ำมวบ | น้ำมวบ | FiN | Nan Basin | yes | **yes** (12,628) | empty |
| `685678` | สะพานแม่ตื่น | แม่น้ำตื่น | FiN | Ping Basin | yes | **yes** (4,129) | empty |
| `700551` | เขื่อนท่าทุ่งนา | อ่างเก็บน้ำท่าทุ่งนา | EGAT | Mae Klong Basin | yes | **yes** (2,163) | empty |
| `700552` | บ้านหนองบัว (K.35A) | แม่น้ำแควใหญ่ | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700553` | วัดไชยชุมพลชนะสงคราม (วัดใต้) | แม่น้ำแม่กลอง | EGAT | Mae Klong Basin | yes | **yes** (2,161) | empty |
| `700555` | วัดหนองปรือ | ลำตะเพิน | EGAT | Mae Klong Basin | yes | **yes** (161) | **yes** (161) |
| `700556` | โรงเรียนบ้านทุ่งนานางหรอก | ลำตะเพิน | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700559` | หน่วยพิทักษ์ป่าเขาบันได | ห้วยแม่ดี | EGAT | Mae Klong Basin | yes | **yes** (2,161) | empty |
| `700584` | อ.ทองผาภูมิ | แม่น้ำแควน้อย | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700585` | บ้านหินดาด | แม่น้ำแควน้อย | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700586` | บ้านลิ่นถิ่น (K.54) | แม่น้ำแควน้อย | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700587` | บ้านปากแซง (K.58) | แม่น้ำแควน้อย | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700588` | บ้านลุ่มสุ่ม (K.10) | แม่น้ำแควน้อย | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700589` | บ้านวังเย็น (K.37) | แม่น้ำแควน้อย | EGAT | Mae Klong Basin | yes | **yes** (162) | **yes** (162) |
| `700591` | สะพานมิตรภาพชุมพล | แม่น้ำภาชี | EGAT | Mae Klong Basin | yes | **yes** (168) | **yes** (168) |
| `700592` | วัดหินแท่น (K.62) | ลำภาชี | EGAT | Mae Klong Basin | — | **yes** (710) | **yes** (710) |
| `709863` | สะพานท่าสาป อ.เมือง จ.ยะลา | แม่น้ำปัตตานี | EGAT | Peninsula - Lower East Coast Basin | yes | **yes** (168) | **yes** (168) |
| `726653` | บ้านเสาธง | คลองเสาธง | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `726656` | บ้านควนกลาง (1) | แม่น้ำตาปี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `726667` | บ้านอาพาธ | คลองอิปัน | RID | Peninsula - Upper East Coast Basin | yes | **yes** (7) | **yes** (7) |
| `726673` | บ้านนาสีทอง | คลองรัตภูมิ | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `726680` | บ้านหูแร่ | คลองวาด | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `726684` | บ้านบริดอ | แม่น้ำปัตตานี | RID | Peninsula - Lower East Coast Basin | yes | **yes** (1,957) | empty |
| `726686` | บ้านท่านา | คลองกะปง | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `740532` | สะพานลำน้ำเลย | แม่น้ำเลย | HII | Northeast Khong Basin | yes | **yes** (13,044) | empty |
| `740533` | สะพานห้วยน้ำฮวย | ห้วยน้ำฮวย | HII | Northeast Khong Basin | yes | **yes** (1,152) | empty |
| `740537` | สะพานห้วยมุก | ห้วยมุก | HII | Northeast Khong Basin | yes | **yes** (12,861) | empty |
| `740538` | สะพานบังอี่ | ห้วยบังอี | HII | Northeast Khong Basin | yes | **yes** (5,892) | empty |
| `740540` | สะพานข้ามน้ำมูล | แม่น้ำมูล | HII | Mun Basin | yes | **yes** (11,063) | empty |
| `740720` | คลองสรอย วัดแม่ขมวก | ห้วยแม่สรอย | FiN | Yom Basin | yes | **yes** (12,945) | empty |
| `740723` | สะพานวัดมงคลร่วมใจ (บ้านวังสาร) | คลองวังน้ำใส | FiN | Nan Basin | yes | **yes** (12,970) | empty |
| `740726` | สะพานบางไตประชาบริรักษ์ | คลองยัน | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (13,005) | empty |
| `740727` | สะพานคลองพาย | ห้วยแวัะ | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (12,915) | empty |
| `740729` | สะพานทางเข้าชุมชนบ้านปากซวด | คลองบางครก | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (12,912) | empty |
| `740730` | สะพานบ้านสวนปราง | คลองสระ | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (12,872) | empty |
| `740731` | สะพานข้ามคลองหวาด | คลองหวาด | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (12,990) | empty |
| `740736` | สะพานข้ามคลองวังเคียน | คลองวังเคียน | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (12,865) | empty |
| `740737` | สะพานห้วยน้ำใส | คลองไม้เสียบ | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (13,013) | empty |
| `740738` | สะพานข้ามคลองห้วยกรวด | คลองห้วยกรวด | FiN | Thale Sap Songkhla Basin | yes | **yes** (12,639) | empty |
| `740739` | สะพานบ้านแหลมโตนด | คลองคุ้ง | FiN | Thale Sap Songkhla Basin | yes | **yes** (6,247) | empty |
| `740740` | สะพานท่าสำเภา | คลองปากประ | FiN | Thale Sap Songkhla Basin | yes | **yes** (13,022) | empty |
| `740742` | คลองสุหงาบารู หมู่ที่ 4 | คลองสุหงาบารู | FiN | Peninsula - Lower East Coast Basin | yes | **yes** (12,951) | empty |
| `740746` | สะพานข้ามแม่น้ำปัตตานี | แม่น้ำปัตตานี | FiN | Peninsula - Lower East Coast Basin | yes | **yes** (13,013) | empty |
| `745748` | สะพานห้วยบังบาต | ห้วยบางบาตร | HII | Northeast Khong Basin | yes | **yes** (12,975) | empty |
| `786010` | บ้านดอนยาง | ลำน้ำยัง | RID | Chi Basin Basin | — | **yes** (1,500) | empty |
| `832057` | บ้านหนองไผ่ | ลำภาชี | RID | Mae Klong Basin | yes | **yes** (1,974) | **yes** (1) |
| `832059` | บ้านยางสูง | ลำตะเพิน | RID | Mae Klong Basin | yes | **yes** (1,985) | empty |
| `832066` | สะพานค่ายหลวง | แม่น้ำแม่กลอง | RID | Mae Klong Basin | yes | **yes** (152) | **yes** (152) |
| `832084` | บ้านทุ่งแฝก | แม่น้ำกุยบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `852087` | อโศก | คลองแสนแสบ | HII | Chao Phraya Basin | yes | **yes** (12,931) | empty |
| `999395` | บ้านหาดใน  | คลองรับรอ | RID | Peninsula - Upper East Coast Basin | yes | **yes** (1,975) | empty |
| `999405` | วัดถลุงทอง อำเภอร่อนพิบูลย์  | คลองเสาธง | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1035512` | บ้านคลองหินลับ | ห้วยหินลับ | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `1035516` | บ้านบัว | ลำเชิงไกร | RID | Mun Basin | yes | **yes** (157) | **yes** (88) |
| `1035518` | บ้านหินโคนเก่า | ลำปลายมาศ | RID | Mun Basin | yes | **yes** (805) | **yes** (66) |
| `1035521` | บ้านดอนยาง | ลำเสียว | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `1066916` | บ้านชะอม | แควหนุมาน | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `1079844` | บ้านโนนค่า | ห้วยดินดำ | RID | Mun Basin | yes | **yes** (1,778) | **yes** (252) |
| `1079932` | ตำบลท่าหลวง | คลองบ้านปากคลองใหญ่ | RID | East Coast Gulf Basin | yes | **yes** (161) | **yes** (161) |
| `1079995` | บ้านไสหาร | แม่น้ำตรัง | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1082427` | บ่อดินขาว | คลองอนุศาสนนันท์ | HII | Chao Phraya Basin | yes | **yes** (5,278) | empty |
| `1085210` | สะพานตาบัว บ้านยาเด๊ะ | คลองอัยดาลอ | HII | Peninsula - Lower East Coast Basin | yes | **yes** (1,980) | empty |
| `1085211` | สะพานกะลูบี บ้านสายปารี | แม่น้ำสายบุรี | HII | Peninsula - Lower East Coast Basin | yes | **yes** (13,023) | empty |
| `1087618` | บ้านปายอยือนิ  | แม่น้ำสายบุรี | RID | Peninsula - Lower East Coast Basin | yes | **yes** (1,975) | empty |
| `1091551` | เขาวง | คลองอนุศาสนนันท์ | HII | Chao Phraya Basin | yes | **yes** (13,027) | empty |
| `1093079` | คลองชะอวด | คลองชะอวด | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,061) | empty |
| `1093312` | บ้านเขาน้อย | แม่น้ำปราณบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (1,888) | empty |
| `1094448` | โรงเรียนวัดโคกโพธิ์สถิตย์ | คลองท่าดี | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,511) | empty |
| `1095455` | สะพานบ้านตรังพัฒนา | คลองหลังสวน | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,067) | empty |
| `1095849` | สะพานหัวเวียง | nan | RID | Chao Phraya Basin | yes | **yes** (1,583) | empty |
| `1095872` | บ้านท่าไม้ลาย | คลองชุมพร | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1095875` | บ้านทุ่งปราบ | คลองหล้าปัง | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (136) |
| `1095876` | บ้านเขาปู่ | คลองใหญ่ | RID | Thale Sap Songkhla Basin | yes | **yes** (148) | **yes** (148) |
| `1095877` | บ้านหัวสะพาน | คลองใหญ่ | RID | Peninsula - Lower East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1095878` | บ้านปรีกี | แม่น้ำปัตตานี | RID | Peninsula - Lower East Coast Basin | yes | **yes** (1,975) | empty |
| `1095879` | บ้านกลาง | แม่น้ำตรัง | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1095881` | บ้านปันจอร์ | คลองดุสน | RID | Peninsula - West Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1095882` | บ้านรมณีย์ | คลองรมณีย์ | RID | Peninsula - West Coast Basin | yes | **yes** (120) | **yes** (120) |
| `1097520` | บ้านช้างแรก | ห้วยหินปิด | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (113) |
| `1098852` | บ้านสัมฤทธิ์ | แม่น้ำมูล | RID | Mun Basin | yes | **yes** (1,753) | **yes** (534) |
| `1098871` | บ้านโนนสมบูรณ์ | ลำสะแทต | RID | Mun Basin | yes | **yes** (1,501) | empty |
| `1098950` | บ้านแก้ง | คลองพระปรง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `1098952` | เขาลูกช้าง | แม่น้ำเพชรบุรี | RID | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (152) | **yes** (152) |
| `1098955` | บ้านทุ่งแฝก | ห้วยยาง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `1098957` | บ้านแก่งดินสอ | แควโขมง | RID | Bang Pakong Basin | yes | **yes** (161) | **yes** (161) |
| `1099005` | บ้านแลง | แม่น้ำวัง | RID | Wang Basin | yes | **yes** (161) | **yes** (161) |
| `1101563` | ห้วยแม่แจ่ม | น้ำแม่แจ่ม | FiN | Ping Basin | yes | **yes** (13,034) | empty |
| `1101565` | สะพานแม่น้ำลาว | น้ำแม่ลาว | FiN | North Khong Basin | yes | **yes** (13,015) | empty |
| `1101566` | คลองกั้ง | ห้วยกั้ง | FiN | Nan Basin | yes | **yes** (12,922) | empty |
| `1101568` | บ้านประดู่ | คลองท่าเลา | FiN | Peninsula - West Coast Basin | yes | **yes** (13,005) | empty |
| `1101569` | บ้านใต้ | คลองท่าโลน | FiN | Peninsula - West Coast Basin | yes | **yes** (8,720) | empty |
| `1101572` | บ้านคลองวาย หมู่ที่ 7 | คลองบางจิก | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (13,029) | empty |
| `1101573` | บ้านคลองใส หมู่ที่ 8 | คลองวาย | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (12,967) | empty |
| `1101574` | บ้านคลองมุย หมู่ที่ 13 | คลองมุย | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (4,017) | empty |
| `1105332` | ปตร กุฎิ (ทุ่งป่าโมก) | แม่น้ำน้อย | HII | Chao Phraya Basin | yes | **yes** (13,027) | empty |
| `1106448` | ปตร.ปลายคลองบางซอ (ทุ่งเจ้าเจ็ด) | แม่น้ำสุพรรณ | HII | Tha Chin Basin | yes | **yes** (13,056) | empty |
| `1106449` | ปตร.ลาดชะโด (ทุ่งผักไห่) | คลองบางคี่ | HII | Chao Phraya Basin | yes | **yes** (12,921) | empty |
| `1106450` | ปตร.ลาดชิด (ทุ่งผักไห่) | ลำรางยายสุข | HII | Chao Phraya Basin | yes | **yes** (13,036) | empty |
| `1106454` | สถานีสูบน้ำปากคลองสายห้วยแก้ว (ทุ่งซ้ายคลองชัยนาท) | คลองท่าตะโก | HII | Chao Phraya Basin | yes | **yes** (13,028) | empty |
| `1106455` | สถานีสูบน้ำปากคลองสระตาแวว (ทุ่งซ้ายคลองชัยนาท) | คลองโพนทอง | HII | Chao Phraya Basin | yes | **yes** (11,936) | empty |
| `1106456` | ทรบ. ปากคลองห้าวา (ทุ่งท่าวุ้ง) | คลองบางคะลาย | HII | Chao Phraya Basin | yes | **yes** (12,153) | empty |
| `1106457` | สถานีสูบน้ำคลองระบายชัยนาท-ป่าสัก 2 (ทุ่งเชียงราก) | คลองบางโฉมศรี | HII | Chao Phraya Basin | yes | **yes** (12,988) | empty |
| `1107582` | เสนา (ทุ่งบางบาล-บ้านแพน) | แม่น้ำน้อย | HII | Chao Phraya Basin | yes | **yes** (13,028) | empty |
| `1109490` | สะพานท่าน้ำ | คลองกระบี่ใหญ่ | HII | Peninsula - West Coast Basin | yes | **yes** (12,957) | empty |
| `1109491` | สะพานข้ามคลองกระบี่ใหญ่ 1 | คลองกระบี่ใหญ่ | HII | Peninsula - West Coast Basin | yes | **yes** (12,691) | empty |
| `1109492` | สะพานคลองอิปัน | คลองปันโตน | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,004) | empty |
| `1109493` | สะพานข้ามคลองตะโก | คลองตะโก | HII | Peninsula - Upper East Coast Basin | yes | **yes** (6,193) | empty |
| `1109494` | สะพานหนองจิก-วังปลา | คลองตะโก | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,006) | empty |
| `1109495` | ปตร.ธรณิศนฤมิต-เหนือน้ำ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (12,278) | empty |
| `1109496` | ปตร.ธรณิศนฤมิต-ท้ายน้ำ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (11,519) | empty |
| `1109497` | ปตร. ห้วยแคน-เหนือน้ำ | ห้วยแคน | HII | Northeast Khong Basin | yes | **yes** (11,551) | empty |
| `1109498` | ปตร. ห้วยแคน-ท้ายน้ำ | ห้วยแคน | HII | Northeast Khong Basin | yes | **yes** (13,011) | empty |
| `1109499` | สะพานบ้านแก่งโพธิ์ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (9,297) | empty |
| `1109500` | ปตร.บ้านนาคู่-เหนือน้ำ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (9,798) | empty |
| `1109501` | ปตร. บ้านนาคู่-ท้ายน้ำ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (12,065) | empty |
| `1109502` | สะพานมิตรภาพท่าลาดปากบัง | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (13,029) | empty |
| `1109504` | ปตร. บ้านนาขาม-ท้ายน้ำ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (12,802) | empty |
| `1109505` | สะพานน้ำก่ำ บ้านหนองแคน | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (12,992) | empty |
| `1109506` | ปตร.บ้านนาบัว-เหนือน้ำ | ลำน้ำกำ | HII | Northeast Khong Basin | yes | **yes** (13,011) | empty |
| `1109508` | ปตร.บ้านตับเต่า-เหนือน้ำ | ลำน้ำบัง | HII | Northeast Khong Basin | yes | **yes** (12,998) | empty |
| `1109509` | ปตร. บ้านตับเต่า-ท้ายน้ำ | ลำน้ำบัง | HII | Northeast Khong Basin | yes | **yes** (10,650) | empty |
| `1109511` | คลองสามบาท บ้านกุดพิมาน | ห้วยสามบาท | HII | Mun Basin | yes | **yes** (12,915) | empty |
| `1109512` | สะพานข้ามคลองท่าแพ | คลองเปิก | HII | Peninsula - West Coast Basin | yes | **yes** (13,001) | empty |
| `1109513` | สะพานข้ามคลองบางม่วง | ทะเลหลวง | HII | Thale Sap Songkhla Basin | yes | **yes** (13,010) | empty |
| `1109514` | สะพานข้ามคลองลำปำ | คลองลำปำ | HII | Thale Sap Songkhla Basin | yes | **yes** (13,014) | empty |
| `1109516` | สะพานข้ามคลองกะเปอร์ | คลองกะเปอร์ | HII | Peninsula - West Coast Basin | yes | **yes** (12,597) | empty |
| `1109519` | สะพานข้ามคลองเดียก | ห้วยเดียก | HII | Northeast Khong Basin | yes | **yes** (13,016) | empty |
| `1109522` | สะพานข้ามคลองโมง | ห้วยโมง | HII | Northeast Khong Basin | yes | **yes** (12,865) | empty |
| `1109523` | สะพานข้ามห้วยสมอ | ห้วยทราย | HII | Northeast Khong Basin | yes | **yes** (13,029) | empty |
| `1109524` | สะพานข้ามคลองเทพา | คลองเทพา | HII | Thale Sap Songkhla Basin | yes | **yes** (12,995) | empty |
| `1109525` | สะพานเทพาสันติสุข | คลองเทพา | HII | Thale Sap Songkhla Basin | yes | **yes** (13,010) | empty |
| `1109526` | สะพานข้ามคลองอู่ตะเภา | คลองอู่ตะเภา | HII | Thale Sap Songkhla Basin | yes | **yes** (12,997) | empty |
| `1109527` | สะพานสวนเฉลิมพระเกียรติ 72 พรรษามหาราชินี | ทะเลสาบสงขลา | HII | Thale Sap Songkhla Basin | yes | **yes** (13,003) | empty |
| `1109528` | สะพานข้ามคลองระโนด | คลองระโนด | HII | Thale Sap Songkhla Basin | yes | **yes** (13,050) | empty |
| `1109529` | สะพานข้ามแม่น้ำยมสายเก่า-ตำบลไกรใน | คลองวังทอง | HII | Yom Basin | yes | **yes** (13,002) | empty |
| `1109530` | สะพานข้ามแม่น้ำยมสายเก่า-วัดปากน้ำ | คลองแม่น้ำเก่า | HII | Yom Basin | yes | **yes** (12,971) | empty |
| `1109531` | สะพานคลองแม่น้ำเก่า | คลองแม่น้ำเก่า | HII | Yom Basin | yes | **yes** (13,026) | empty |
| `1109533` | สะพานข้ามคลองไชยา | คลองไชยา | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,032) | empty |
| `1109534` | สะพานข้ามคลองปากหมาก | คลองปากหมาก | HII | Peninsula - Upper East Coast Basin | yes | **yes** (12,733) | empty |
| `1109535` | สะพานข้ามคลองท่าชนะ | คลองท่าชนะ | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,011) | empty |
| `1109536` | สะพานถนนสายเอเซีย 4265 | คลองโสด | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,005) | empty |
| `1113280` | บ้านผาจุก | แม่น้ำน่าน | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1113282` | บ้านหาดสองแคว (N.60) | แม่น้ำน่าน | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1113284` | อ.น้ำปาด (N.33) | น้ำปาด | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1113287` | อ.วัดโบสถ์ (N.22A) | น้ำแควน้อย | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1113288` | บ้านแสนตอ | น้ำแควน้อย | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1113290` | อ.ท่าวังผา (N.64) | แม่น้ำน่าน | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1113291` | อ.เมืองน่าน (N.1) | แม่น้ำน่าน | EGAT | Nan Basin | yes | **yes** (2,079) | empty |
| `1113292` | อ.เวียงสา (N.13A) น้ำน่าน | แม่น้ำน่าน | EGAT | Nan Basin | yes | **yes** (2,106) | empty |
| `1113295` | อ.เวียงสา (N.75)  น้ำว้า | แม่น้ำน้ำว้า | EGAT | Nan Basin | yes | **yes** (2,177) | empty |
| `1116838` | สะพานข้ามห้วยแม่รวม บ้านแม่รวม | น้ำแม่รวม | FiN | Ping Basin | yes | **yes** (12,961) | empty |
| `1116839` | สะพานข้ามแม่น้ำลาว-บ้านป่าสัก | น้ำแม่ลาว | FiN | North Khong Basin | yes | **yes** (13,031) | empty |
| `1116840` | สะพานช้ามแม่น้ำลาว - บ้านโฮ่ง  | น้ำแม่ลาว | FiN | North Khong Basin | yes | **yes** (13,031) | empty |
| `1117430` | สะพานบ้านต๋ำ | ห้วยเคียน | HII | North Khong Basin | yes | **yes** (12,764) | empty |
| `1117431` | สะพานบ้านเจดีย์งาม | แม่น้ำอิง | HII | North Khong Basin | yes | **yes** (13,017) | empty |
| `1117894` | บ้านขนงพระเหนือ | ลำโดมน้อย | RID | Mun Basin | yes | **yes** (157) | **yes** (157) |
| `1119776` | บ้านสมสนุก | ลำพะยัง | RID | Chi Basin Basin | yes | **yes** (160) | **yes** (160) |
| `1119854` | บ้านธวัชดินแดง | แม่น้ำชี | RID | Chi Basin Basin | yes | **yes** (1,656) | empty |
| `1119916` | บ้านบึงศาลา | ลำน้ำกำ | RID | Northeast Khong Basin | — | **yes** (41) | **yes** (41) |
| `1120554` | คลองเบตง (ชุมชนกุนุงจนอง) | คลองตาโล๊ะ | FiN | Peninsula - Lower East Coast Basin | yes | **yes** (13,023) | empty |
| `1120557` | สะพานบ้านคีรีวง คลองท่าดี | คลองท่าดี | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (13,008) | empty |
| `1121199` | สะพานแม่น้ำงาว | แม่น้ำงาว | FiN | North Khong Basin | yes | **yes** (13,018) | empty |
| `1121218` | สะพานน้ำห้วยสำราญ | ห้วยสำราญ | FiN | Mun Basin | — | **yes** (10,555) | empty |
| `1121228` | สะพานน้ำแม่ต๋อม | น้ำแม่ต๋อม | FiN | Ping Basin | yes | **yes** (12,834) | empty |
| `1121229` | สะพานน้ำแม่แจ่ม บ้านแปะ | น้ำแม่แจ่ม | FiN | Ping Basin | yes | **yes** (13,026) | empty |
| `1121234` | สะพานน้ำวัง | แม่น้ำวัง | FiN | Wang Basin | yes | **yes** (13,034) | empty |
| `1121239` | สะพานน้ำงิม | น้ำงิม | FiN | Yom Basin | yes | **yes** (12,057) | empty |
| `1121240` | สะพานน้ำเงิน | น้ำเงิน | FiN | Yom Basin | yes | **yes** (12,912) | empty |
| `1121242` | สะพานคลองตรอน | คลองตรอน | FiN | Nan Basin | yes | **yes** (12,825) | empty |
| `1121243` | สะพานคลองท่าสะแก | น้ำภาค | FiN | Nan Basin | yes | **yes** (12,800) | empty |
| `1121258` | สะพานแม่น้ำแควใหญ่ | แม่น้ำแควใหญ่ | FiN | Mae Klong Basin | yes | **yes** (12,285) | empty |
| `1121265` | สะพานคลองจันทเขลม | คลองจันทบุรี | FiN | East Coast Gulf Basin | yes | **yes** (12,990) | empty |
| `1121266` | สะพานคลองวังโตนด | คลองโตนด | FiN | East Coast Gulf Basin | yes | **yes** (12,550) | empty |
| `1121267` | สะพานคลองสะตอ | คลองสะตอ | FiN | East Coast Gulf Basin | yes | **yes** (3,987) | empty |
| `1124040` | บ้านบองอ  | คลองบองอ | RID | Peninsula - Lower East Coast Basin | yes | **yes** (1,958) | empty |
| `1126506` | สะพานข้ามคลองบ้านท่าวัง | คลองอ้ายโต | HII | Thale Sap Songkhla Basin | yes | **yes** (13,051) | empty |
| `1129758` | ฝายคลองท่าโลน | คลองท่าเลา | FiN | Peninsula - West Coast Basin | yes | **yes** (12,948) | empty |
| `1130124` | สะพานคลองปง (คีรีวง) | คลองท่าดี | FiN | Peninsula - Upper East Coast Basin | yes | **yes** (13,050) | empty |
| `1130137` | น้ำตกโตนแพรทอง | คลองลำสิน | FiN | Thale Sap Songkhla Basin | yes | **yes** (6,147) | empty |
| `1139393` | สะพานข้ามลำน้ำเชิญ (มิตรผลหนองเรือ) | ลำเชิญ | HII | Chi Basin Basin | yes | **yes** (13,052) | empty |
| `1140845` | ศาลเจ้าพ่อพญาอ้น | แม่น้ำยม | HII | Yom Basin | yes | **yes** (4,217) | empty |
| `1161514` | บ้านน้ำจืด | คลองทรายปู | RID | Peninsula - West Coast Basin | yes | **yes** (1,959) | empty |
| `1161516` | บ้านหาดทรายแก้ว  | แม่น้ำตาปี | RID | Peninsula - Upper East Coast Basin | yes | **yes** (148) | **yes** (148) |
| `1197957` | คลองห้วยยาง | ห้วยยาง | HII | Bang Pakong Basin | yes | **yes** (6,350) | empty |
| `1198081` | แม่น้ำสา | แม่น้ำสา | HII | Nan Basin | yes | **yes** (12,974) | empty |
| `1198082` | น้ำสา | แม่น้ำสา | HII | Nan Basin | yes | **yes** (12,418) | empty |
| `1198297` | สะพานแม่น้ำทา | น้ำแม่ทา | HII | Ping Basin | yes | **yes** (12,988) | empty |
| `1198298` | แม่น้ำทา | น้ำแม่ทา | HII | Ping Basin | yes | **yes** (13,001) | empty |
| `1198299` | แม่น้ำลี้ บ้านโฮ่ง | น้ำแม่ลี้ | HII | Ping Basin | yes | **yes** (12,968) | empty |
| `1198300` | ห้วยแม่ลี้ | น้ำแม่ลี้ | HII | Ping Basin | yes | **yes** (12,944) | empty |
| `1198301` | น้ำก้อ | ห้วยน้ำแม่ก้อ | HII | Ping Basin | yes | **yes** (12,400) | empty |
| `1198626` | คลองประณีต บ.ตลุง | คลองประณีต | HII | East Coast Gulf Basin | yes | **yes** (11,370) | empty |
| `1198627` | คลองโสน | คลองโสน | HII | East Coast Gulf Basin | yes | **yes** (12,703) | empty |
| `1198628` | คลองเขาระกำ | คลองบางพระ | HII | East Coast Gulf Basin | yes | **yes** (12,610) | empty |
| `1198760` | สะพานหนองจันทร์ | แม่น้ำยม | HII | Yom Basin | yes | **yes** (13,017) | empty |
| `1198761` | แม่ต้า | น้ำแม่ต้า | HII | Yom Basin | yes | **yes** (12,964) | empty |
| `1225528` | บ้านโจตาดา | nan | FiN | nan | yes | **yes** (12,951) | empty |
| `1225529` | บ้านดอยต่อคำ | nan | FiN | nan | yes | **yes** (12,634) | empty |
| `1225530` | สะพานอูทูนอ่อง บ้านสบสาย | nan | FiN | nan | yes | **yes** (12,522) | empty |
| `1225531` | สะพานมิตรภาพแม่น้ำสายแห่งที่ 1 | nan | FiN | North Khong Basin | yes | **yes** (12,878) | empty |
| `1373272` | สะพานอนุสรณ์ 100 ปีสิงห์หบุรี (สะพานหลวงพ่อแพ 89) | nan | HII | Chao Phraya Basin | yes | **yes** (1,003) | **yes** (1,002) |
| `1373273` | สะพานค่ายบางระจัน | nan | HII | Chao Phraya Basin | yes | **yes** (1,002) | **yes** (1,001) |
| `1373274` | สะพานคลองส่งน้ำชลประทาน บ้านตลาดใหม่ | nan | HII | Chao Phraya Basin | yes | **yes** (998) | **yes** (997) |
| `1373275` | สะพานป่าโมก | nan | HII | Chao Phraya Basin | yes | **yes** (13,017) | empty |
| `1373277` | สะพานคลองส่งน้ำชลประทาน บ้านสร่างโศก | nan | HII | Pasak Basin | yes | **yes** (1,002) | **yes** (1,001) |
| `1373278` | สะพานแมน้ำปาสัก บ้านนาโฉง | nan | HII | Pasak Basin | yes | **yes** (988) | **yes** (987) |
| `1373689` | สะพานคลองปากแตระ ชุมชนทะเลสาบสงขลา | nan | HII | Thale Sap Songkhla Basin | yes | **yes** (13,007) | empty |
| `1373690` |  สะพานข้ามคลองโคน | nan | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (13,035) | empty |
| `1373691` | สะพานนางพระยา-บางหลวง ชุมชนปากนคร | nan | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,053) | empty |
| `1373692` | สะพานคลองปากกิ่ว ชุมชนบ้านหาดสมบูรณ์ | nan | HII | Peninsula - Upper East Coast Basin | yes | **yes** (13,003) | empty |
| `1394793` | สะพานน้ำชี | nan | FiN | Chi Basin Basin | yes | **yes** (12,702) | empty |
| `1394808` | สะพานน้ำลำตะคอง | nan | FiN | Mun Basin | yes | **yes** (12,739) | empty |
| `1394937` | สะพานคลองสนธิ | nan | FiN | Pasak Basin | yes | **yes** (12,750) | empty |
| `1396856` | สะพานคลองลำพญาธาร | nan | FiN | Bang Pakong Basin | yes | **yes** (12,673) | empty |
| `1396858` | สะพานคลองนางรอง | nan | FiN | Bang Pakong Basin | yes | **yes** (11,398) | empty |
| `1396860` | สะพานคลองวังตะไคร้ | nan | FiN | Bang Pakong Basin | yes | **yes** (6,126) | empty |
| `1422294` | แม่น้ำปิงที่ อ.สามเงา (P.12C) | nan | EGAT | Ping Basin | yes | **yes** (1,910) | empty |
| `1422295` | แม่น้ำปิงที่ อ.บ้านตาก | nan | EGAT | Ping Basin | yes | **yes** (2,123) | empty |
| `1422296` | ห้วยตากที่ อ.บ้านตาก | nan | EGAT | Ping Basin | yes | **yes** (673) | empty |
| `1422297` | แม่น้ำปิงที่ อ.เมืองตาก (P.2A) | nan | EGAT | Ping Basin | yes | **yes** (1,998) | empty |
| `1422298` | ห้วยแม่ท้อที่ อ.เมืองตาก | nan | EGAT | Ping Basin | yes | **yes** (986) | empty |
| `1422301` | แม่น้ำปิงที่ อ.คลองขลุง (P.15) | nan | EGAT | Ping Basin | yes | **yes** (2,123) | empty |
| `1422302` | แม่น้ำวังที่ อ.เถิน (W.3A) | nan | EGAT | Wang Basin | yes | **yes** (1,013) | empty |
| `1422303` | แม่น้ำวังที่ อ.สามเงา (W.4A) | nan | EGAT | Wang Basin | yes | **yes** (2,170) | empty |
| `1422304` | แม่น้ำปิงที่ อ.จอมทอง | nan | EGAT | Ping Basin | yes | **yes** (2,170) | empty |
| `1422305` | แม่น้ำปิงที่ อ.ฮอด | nan | EGAT | Ping Basin | yes | **yes** (1,087) | empty |
| `1422307` | ห้วยแม่ตื่นที่ อ.อมก๋อย | nan | EGAT | Ping Basin | yes | **yes** (2,071) | empty |
| `1422361` | สะพานคลองแสง อ.บ้านตาขุน | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,151) | empty |
| `1422364` | สะพานเชี่ยวไทร อ.พนม | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,148) | empty |
| `1422365` | สะพานพุมดวง (วัดตาขุน) อ.บ้านตาขุน | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,150) | empty |
| `1422366` | สะพานท่าขนอน (วัดปราการ)อ.คีรีรัฐนิคม (X.36) | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,149) | empty |
| `1422367` | สะพานสิริกฤตานุกุล์ (บ้านท่านหญิง)อ.วิภาวดี  | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,123) | empty |
| `1422368` | สะพานบ้านปากคู่(วัดนิลาราม)อ.คีรีรัฐนิคม ท. 220903 | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,150) | empty |
| `1422369` | สะพานท่าผาก อ.พุนพิน จ.สุราษฎร์ธานี | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,054) | empty |
| `1422371` | สะพานอิปัน อ.พระแสง (X.37A) | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,147) | empty |
| `1422372` | สะพานเคียนซา (ปาล์มพาราวุ้ด) อ.เคียนซา (X.217) | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,150) | empty |
| `1422373` | สะพานบ้างอ้อ อ.พุนพิน | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,150) | empty |
| `1422374` | สะพานจุลจอมเกล้า อ.พุนพิน (X.5C) | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,150) | empty |
| `1422375` | วัดโชติการาม อ.เมืองสุราษฎร์ธานี | nan | EGAT | Peninsula - Upper East Coast Basin | yes | **yes** (2,150) | empty |
| `1475104` | สะพานน้ำแม่ขาน | nan | FiN | Ping Basin | yes | **yes** (4,072) | empty |
| `1475106` | สะพานน้ำแม่กลาง | nan | FiN | Ping Basin | yes | **yes** (13,022) | empty |
| `1475118` | สะพานน้ำแม่งัด | nan | FiN | Ping Basin | yes | **yes** (13,019) | empty |
| `1475120` | สะพานน้ำแม่แตง | nan | FiN | Ping Basin | yes | **yes** (12,111) | empty |
| `1475122` | สะพานแม่น้ำปิง | nan | FiN | Ping Basin | yes | **yes** (13,034) | empty |
| `1476456` | สะพานน้ำคลองแม่สอย | nan | FiN | Wang Basin | yes | **yes** (10,015) | empty |
| `1476459` | สะพานน้ำแม่ต๋ำ | nan | FiN | Wang Basin | — | **yes** (8,202) | empty |
| `1476461` | สะพานพัฒนามิตรภาพแม่น้ำตุ๋ย | nan | FiN | Wang Basin | yes | **yes** (13,021) | empty |
| `1481108` | สะพานน้ำแม่คะ  | nan | FiN | Yom Basin | yes | **yes** (12,903) | empty |
| `1481122` | สะพานน้ำงาว | nan | FiN | Yom Basin | yes | **yes** (13,026) | empty |
| `1481128` | สะพานบ้านตึก | nan | FiN | Yom Basin | yes | **yes** (13,028) | empty |
| `1481146` | สะพานน้ำแม่จั๊ว | nan | FiN | Yom Basin | yes | **yes** (13,025) | empty |
| `1481153` | สะพานน้ำแม่สิน | nan | FiN | Yom Basin | yes | **yes** (13,012) | empty |
| `1482445` | สะพานน้ำปี้ เชียงม่วน | nan | FiN | Yom Basin | yes | **yes** (13,013) | empty |
| `1483103` | สะพานพญาอาทิตราช | nan | FiN | Ping Basin | yes | **yes** (12,968) | empty |
| `1483111` | สะพานคลองแม่มอญ | nan | FiN | Wang Basin | yes | **yes** (12,902) | empty |
| `1483127` | สะพานพระร่วงข้ามน้ำแควน้อย | nan | FiN | Nan Basin | yes | **yes** (13,001) | empty |
| `1483131` | สะพานน้ำเข็ก | nan | FiN | Nan Basin | yes | **yes** (13,023) | empty |
| `1556820` | สะพานน้ำแม่สรวย | nan | FiN | North Khong Basin | yes | **yes** (3,945) | empty |
| `1556822` | สะพานแม่ระมาด | nan | FiN | Salawin Basin | yes | **yes** (13,034) | empty |
| `1645475` | น้ำแม่งาว | nan | HII | Yom Basin | yes | **yes** (13,069) | empty |
| `1677418` | สะพานข้ามน้ำอิง (I.17) | nan | HII | North Khong Basin | yes | **yes** (12,959) | empty |
| `1677419` | สะพานคลองแม่ต๋ำ | nan | HII | North Khong Basin | yes | **yes** (13,068) | empty |
| `1677420` | สะพานคลองแม่กาหลง (ม.พะเยา) | nan | HII | North Khong Basin | yes | **yes** (13,070) | empty |
| `9822342` | โรงสูบน้ำแรงต่ำแม่ข่าย (แม่สาย) | nan | HII | North Khong Basin | yes | **yes** (9,129) | empty |
| `9930854` | คลองพระราชดำริ ซอยหัวหิน 10 | nan | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (12,552) | empty |
| `9930856` | คลองพระราชดำริ วัดเขาไกรลาศ | nan | HII | Phetchaburi - Prachuap Khiri Khan Basin | yes | **yes** (12,374) | empty |
| `9931002` | บ้านหัวนาหนองจิก | nan | HII | Mun Basin | yes | **yes** (11,682) | empty |
| `9931004` | บ้านกำพี้  | nan | HII | Mun Basin | yes | **yes** (11,809) | empty |
| `9931006` | บ้านน้ำผึ้ง | nan | HII | Mun Basin | yes | **yes** (11,561) | empty |
| `9931008` | บ้านกระยอม  | nan | HII | Mun Basin | yes | **yes** (11,674) | empty |
| `11568367` | โรงสูบน้ำแรงต่ำแม่ข่าย (แม่สาย) | nan | FiN | North Khong Basin | — | **yes** (1,003) | empty |
| `11688546` | คลองน้ำจู | nan | RID | Pasak Basin | yes | empty | empty |
| `11688685` | บ้านสุขสำราญ | nan | RID | Northeast Khong Basin | yes | empty | empty |
| `11688715` | ฝายยางลำน้ำยัง | nan | RID | Chi Basin Basin | yes | empty | empty |
| `11688749` | บ้านเหนือคลอง | nan | RID | Peninsula - West Coast Basin | — | empty | empty |
| `11688817` | สถานีบ้านทุ่งกรวด | nan | RID | Peninsula - Upper East Coast Basin | yes | empty | empty |
| `11688823` | บ้านตาสา | nan | RID | Peninsula - Lower East Coast Basin | — | empty | empty |
| `11688849` | บ้านต้นยาง | nan | RID | North Khong Basin | — | empty | empty |
| `11689002` | บ้านโคกหม้อ | nan | RID | Sakae Krang Basin | — | empty | empty |
| `11689003` | บ้านท่ารวก | nan | RID | Pasak Basin | yes | empty | empty |
| `11689067` | บ้านจะโปรง | nan | RID | Phetchaburi - Prachuap Khiri Khan Basin | — | empty | empty |
| `11689072` | สะพานท่าเกวียน | nan | RID | Phetchaburi - Prachuap Khiri Khan Basin | — | empty | empty |
| `11689150` | เทศบาลเทพกระษัตรี | nan | RID | Peninsula - West Coast Basin | — | empty | empty |

**825 stations · 1650 station × product pairs · 1096 established series.**

| Product | available | empty in tested window | access failed |
| --- | --- | --- | --- |
| `stage_reported` | 813 | 12 | 0 |
| `discharge_reported` | 283 | 542 | 0 |
