# csv2sef
csv2sef - convert transcribed historical weather observations (csv / Excel)
into the Station Exchange Format (SEF 1.0.0).

Authors: Hervé Hacot, Victoria Slonosky, Henry Balen (Open Data Rescue)

Please cite:
    Slonosky, V., Black, R., Podolsky, L., Wang, X. & Cheng, V. (2026).
    Transcribing historical Canadian weather data. Scientific Data 13, 678.
    https://doi.org/10.1038/s41597-025-06036-y

## Installation

### From source

If using this repository, ensure that you have uv installed

1. clone the repo
2. run `uv sync`
3. build using `uv build`
4. run csv2sef using
```
uv run csv2sef
```

### From PyPi package

Ensure you are using Python 3.14 or greater.

1. Install using pip
```
pip install csv2sef
```
2. run typing the command `csv2sef`

NOTE: you could use uv instead of pip if you like

## Development

Create a branch based on this reposistory. You can submit a PR for changes
top be merged into a release.

## Precision of converted values

Some historical observations are estimates on descriptive scales. Their SI equivalents
are given as whole numbers, so as not to suggest more precision than the original has:

* **Wind force scales** follow Table 4 of Slonosky et al. (2026). Smithsonian 0-10 =
  0 1 2 5 10 15 20 25 35 40 45 m/s; Beaufort 0-12 = 0 1 2 5 7 10 12 15 20 25 30 35 40 m/s
  (the same m/s for the forces Table 4 pairs together; whole numbers, to the nearest
  5 m/s above 10 m/s). Above force 3 these are up to 5 m/s higher than the mid-points of
  the modern WMO Beaufort ranges, and Beaufort 12 is open-ended. Wind given in words
  ("fresh breeze") uses the Beaufort values. Measured wind (miles per hour, knots, wind
  pressure) keeps its decimals.
* **Cloud cover** in tenths is converted to whole oktas (tenths x 0.8, rounded).
* **Cloud types** follow Table 5 of the paper; cirrus-type clouds are always given a
  high-cloud code, whichever column they are written in.
* **Trace precipitation** ("trace", "slight", "inappreciable", "a little") is 0.13 mm
  (0.005 in, Table 8 of the paper), flagged `trace`. Change it with `trace_mm` in the metadata.
* **Vapour pressure written without its decimal point** (e.g. `189` in inches of mercury)
  is divided by 1000 (0.189 inHg) and flagged `missing decimal`. (The paper's text says
  100; 1000 is the rule actually applied.)

The original value is kept in the Meta column of every SEF line (`orig=...`).

