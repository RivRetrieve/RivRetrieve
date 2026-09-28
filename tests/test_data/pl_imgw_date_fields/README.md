# IMGW daily date fields

`codz_1992_07.zip` contains exact publisher bytes acquired on September 25, 2026.
Its metadata records the URL, transfer time, checksum, member and logical row count.
Row 16248 has an empty tenth cell. Its published hydrological year `1992`,
month index `07` and day `16` identify May 16, 1992.

`hydrologia_info_ogolne.txt` defines the hydrological year as November 1 of the
previous calendar year through October 31. Month indices run from November
(`01`) to October (`12`). It describes the calendar-month field as additional
to that index: “oprócz powyższego wskaźnika”. `CODZ_publiczne_format.txt`
identifies the ten daily fields. Both files retain the publisher's CP1250 bytes;
their metadata records the original acquisitions.

Tests retain the empty source cell. The calendar timestamp uses the published
hydrological date, not adjacent records or the archive filename. Synthetic
boundary and failure cases are identified separately in the tests.
