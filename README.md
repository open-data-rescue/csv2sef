# csv2sef
csv2sef - convert transcribed historical weather observations (csv / Excel)
into the Station Exchange Format (SEF 1.0.0).

Authors: Hervé Hacot, Victoria Slonosky (Open Data Rescue)

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
