# -*- coding: utf-8 -*-
"""
Reading input files (csv, tsv, xlsx) in wide or long layout.

Wide layout (one row per day):
    Year, Month, Day [, Julian day], <var time [unit]>, ...
    or Date (YYYY-MM-DD), <var time [unit]>, ...
Long layout (one row per value): columns Date (or Year/Month/Day), Time (optional),
    Variable, Value and optionally Unit.
"""
import csv
import datetime as dt
import os
import re
from dataclasses import dataclass
from typing import Optional

from .headers import normalise

DATE_NAMES = {"year": "year", "yr": "year", "month": "month", "mo": "month", "day": "day",
              "date": "date", "observationdate": "date", "observation date": "date",
              "observation_date": "date", "obs_date": "date", "datetime": "date",
              "date time": "date", "localdate": "date"}
JULIAN_WORDS = ("julian", "jday", "doy", "day of year")
# long layout column names
LONG_NAMES = {
    "variable": {"variable", "field_key", "field key", "field", "element", "parameter", "vbl"},
    "value": {"value", "obs_value", "observation", "val"},
    "unit": {"unit", "units", "original unit"},
    "time": {"time", "hour", "obs_time", "local time", "localtime"},
}


def long_columns(headers):
    """name -> index for the long layout (variable, value, unit, time)."""
    low = [h.lower() for h in headers]
    out = {}
    for key, names in LONG_NAMES.items():
        for i, h in enumerate(low):
            if h in names:
                out[key] = i
                break
    return out


@dataclass
class Table:
    headers: list
    rows: list          # list of (line_number, [cells as str])
    layout: str         # "wide" or "long"


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def unquote(v):
    """Remove quotes wrapped around a whole cell: 'clear' -> clear."""
    v = v.strip()
    while len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1].strip()
    return v


def read(path, sheet=None):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise SystemExit("Reading Excel files needs openpyxl: pip install openpyxl")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        raw = [[_cell(c) for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        raw = None
        for enc in ("utf-8-sig", "cp1252"):
            try:
                with open(path, encoding=enc, newline="") as f:
                    text = f.read()
                break
            except UnicodeDecodeError:
                continue
        delim = "\t" if ext in (".tsv", ".tab") else ","
        if ext not in (".tsv", ".tab"):
            first = text.splitlines()[0] if text else ""
            if first.count(";") > first.count(","):
                delim = ";"
            elif first.count("\t") > first.count(","):
                delim = "\t"
        raw = list(csv.reader(text.splitlines(), delimiter=delim))
    # drop leading empty lines
    while raw and not any(c.strip() for c in raw[0]):
        raw.pop(0)
    headers = [normalise(h) for h in raw[0]]
    rows = [(i + 2, [unquote(c) for c in r] + [""] * (len(headers) - len(r)))
            for i, r in enumerate(raw[1:]) if any(c.strip() for c in r)]
    lc = long_columns(headers)
    layout = "long" if ("variable" in lc and "value" in lc) else "wide"
    return Table(headers, rows, layout)


def date_columns(headers):
    """Return (dict name->index, julian index or None)."""
    cols, julian = {}, None
    for i, h in enumerate(headers):
        hl = h.lower()
        if hl in DATE_NAMES and DATE_NAMES[hl] not in cols:
            cols[DATE_NAMES[hl]] = i
        elif any(w in hl for w in JULIAN_WORDS) or hl == "jd" or (hl == "day" and "day" in cols):
            julian = i
    return cols, julian


def parse_date(row, cols):
    """-> datetime.date or raises ValueError"""
    return parse_datetime(row, cols)[0]


def parse_datetime(row, cols):
    """-> (date, time string or None). A Date column may hold 'YYYY-MM-DD HH:MM[:SS]'."""
    if "date" in cols:
        s = row[cols["date"]].strip()
        m = re.match(r"(\d{3,4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}:\d{2})(?::\d{2})?)?\s*$", s)
        if not m:
            raise ValueError(f"date '{s}' not in YYYY-MM-DD form")
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(4)
    return dt.date(int(float(row[cols["year"]])), int(float(row[cols["month"]])),
                   int(float(row[cols["day"]]))), None
