# csv2sef examples

Each folder holds a transcribed data file and its metadata file. To try one, go into
its folder and run, for example:

    csv2sef check   Hebron_Pressure_1883-09_1883-12.csv Hebron_metadata.csv
    csv2sef convert Hebron_Pressure_1883-09_1883-12.csv Hebron_metadata.csv -o sef_output

`check` shows how each column will be read without writing anything; `convert` writes
the SEF files (in `sef_output/SEF/`), a clean csv, an SI-unit csv and a log.

## YorkFactoryHBC - York Factory, Hudson Bay, January-July 1773

The simplest example: temperature twice a day, wind direction and daily weather remarks.
The same observations are given in both layouts csv2sef reads:

* `YorkFactory-HBC_1773_wide.csv` - one row per day; each column header is
  `variable time [unit]`, e.g. `ta 09:00 [F]`. The remarks column has no time (`ww [text]`),
  so it is read as a daily value.
* `YorkFactory-HBC_1773_long.csv` - one value per line: date and time, variable code,
  value, unit (`midnight_means_daily = yes` in the metadata: 00:00 marks the daily remarks).

Both use `YorkFactoryHBC_metadata.csv` and give the same SEF values. The remarks in the
long file are shorter: it is a database export, which cut each remark at 50 characters, so
a few weather codes (halos, aurora) are only found in the wide file.

Note the readings of -57 F from 30 January to
3 February: the remarks say the mercury had sunk into the bulb. They are kept, and flagged
as out of range.

## Hebron - Moravian mission, Labrador, September-December 1883

Pressure in millimetres of mercury three times a day (`p 08:00 [mmHg]`), with `-999.9`
for missing values. The metadata shows:

* the barometer corrections written into the SEF header:
  `variable.p, header_meta=PTC=Y|PGC=N` (reduced to 0 C, not to standard gravity);
* a corrected position, with the value from the original transcription kept in the notes.

Note the dates are in `year, day, month` order: the column names, not their order, tell
csv2sef which is which.

## HalifaxCitadel - Halifax Citadel Hill, November 1863-February 1865

A fuller register: air, wet- and dry-bulb temperatures, minimum, pressure with attached
thermometer, wind force in words and direction, weather and daily remarks. It shows
station-specific lookup tables for wind words and weather terms
(`wind_words_halifax.csv`, `weather_terms_halifax.csv`, named in the metadata), and
settings such as `tn_night_after` and `daily_timestamp`.
