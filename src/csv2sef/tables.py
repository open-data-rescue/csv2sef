# -*- coding: utf-8 -*-
"""Lookup tables shipped in csv2sef/data/ (editable csv files), plus user tables."""
import csv
import os
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def read_table(path):
    """Read a csv lookup table; lines starting with '#' are comments."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    return [{k.strip(): (v or "").strip() for k, v in row.items() if k}
            for row in csv.DictReader(lines)]


def _data(name):
    return read_table(os.path.join(DATA_DIR, name))


@lru_cache(maxsize=None)
def variables():
    """code -> dict(description, unit, stat, period, quantity, sef_vbl)"""
    return {r["code"]: r for r in _data("variables.csv")}


@lru_cache(maxsize=None)
def unit_aliases():
    """lower-case alias -> canonical unit code"""
    out = {}
    for r in _data("units.csv"):
        out[r["alias"].lower()] = r["unit"]
        out.setdefault(r["unit"].lower(), r["unit"])
    return out


@lru_cache(maxsize=None)
def unit_descriptions():
    out = {}
    for r in _data("units.csv"):
        out.setdefault(r["unit"], r["description"])
    return out


@lru_cache(maxsize=None)
def variable_aliases():
    """normalised alias -> code (longest first)"""
    out = {norm_name(r["alias"]): r["code"] for r in _data("variable_aliases.csv")}
    return dict(sorted(out.items(), key=lambda kv: -len(kv[0])))


def norm_name(s):
    import re
    s = s.replace("_", " ").replace("'", "").replace('"', "").lower()
    return re.sub(r"\s+", " ", s).strip()


def canonical_unit(token):
    """'°F' -> 'F', 'in Hg' -> 'inHg'; None if unknown."""
    if token is None:
        return None
    t = " ".join(token.replace("\xa0", " ").split()).lower()
    if t in ("", "na", "n/a", "none", "-"):
        return None
    return unit_aliases().get(t)


def wind_words(extra_files=()):
    """term (lower case) -> Beaufort number or 'unknown'. User files take precedence."""
    out = {}
    rows = []
    for path in extra_files:
        rows += read_table(path)
    rows += _data("wind_words.csv")
    for r in rows:
        term = r["term"].lower()
        if term and term not in out:
            out[term] = r["beaufort"]
    return out


def weather_terms(extra_files=()):
    """Ordered list of (term, code, match). User rows come first."""
    rows = []
    for path in extra_files:
        rows += read_table(path)
    rows += _data("weather_terms.csv")
    return [(r["term"].lower(), r["code"], (r.get("match") or "contains").lower())
            for r in rows if r.get("term")]


def ranges(region="global"):
    """quantity -> dict(out_min, low, high, out_max) as floats/None."""
    def f(x):
        return float(x) if x not in ("", None) else None
    rows = [r for r in _data("ranges.csv") if r["region"].lower() == region.lower()]
    if not rows:
        raise ValueError(f"Unknown range region '{region}' (see data/ranges.csv)")
    return {r["quantity"]: {k: f(r[k]) for k in ("out_min", "low", "high", "out_max")}
            for r in rows}
