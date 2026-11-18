# -*- coding: utf-8 -*-
"""Which csv2sef conversions have no test?

Lists:
  1. converters (units) in csv2sef with no row in tests/known_values.csv
  2. unit names/aliases in data/units.csv that point to a unit with no converter
  3. wind_words.csv terms whose lookup does not return the table's own Beaufort number
  4. weather_terms.csv terms that, written alone, do not come out as the table's own code
     (usually an earlier, shorter term in the table catching it first)

Run from the csv2sef folder:   python tools/coverage_report.py
"""
import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "src"), ROOT):
    if os.path.isdir(os.path.join(p, "csv2sef")):
        sys.path.insert(0, p)
        PKG = os.path.join(p, "csv2sef")
        break

from csv2sef import tables                                                 # noqa: E402
from csv2sef.convert import CONVERTERS, Context, Logger, process_value     # noqa: E402

DATA = os.path.join(PKG, "data")
KNOWN = os.path.join(ROOT, "tests", "known_values.csv")
OPTS = {"trace_mm": 0.2, "wind_words": tables.wind_words(), "weather_terms": tables.weather_terms()}
BF_MS = None


def conv(v, var, unit):
    try:
        return process_value(v, var, unit, Context(0, unit, dt.date(1860, 1, 1), var), Logger(), OPTS)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}", None, None, None


def rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if not next(iter(r.values()), "").startswith("#")]


def main():
    problems = 0
    known = rows(KNOWN)
    tested = {}
    for r in known:
        tested.setdefault(r["unit"], []).append(r)

    print("1. Converters and their tests")
    for unit in sorted(CONVERTERS):
        rs = tested.get(unit, [])
        filled = [r for r in rs if r["status"] != "to_fill" and r["expected"] != ""]
        mark = "MISSING" if not filled else ("to check" if all(r["status"] == "to_check" for r in filled) else "ok")
        if mark == "MISSING":
            problems += 1
        print(f"   {mark:9s} {unit:14s} {len(filled)} test(s)" + (f", {len(rs) - len(filled)} to fill" if len(rs) > len(filled) else ""))
    extra = sorted(set(tested) - set(CONVERTERS))
    if extra:
        print("   test rows for units csv2sef does not know:", ", ".join(extra))

    print("\n2. Unit names in units.csv with no converter")
    bad = [r for r in rows(os.path.join(DATA, "units.csv")) if r["unit"] not in CONVERTERS]
    for r in bad:
        print(f"   {r['alias']!r} -> {r['unit']!r}")
    print("   none" if not bad else "")
    problems += len(bad)

    print("\n3. wind_words.csv: does each term give its own Beaufort number?")
    bf_ms = {}
    for b in range(13):
        bf_ms[b] = conv(str(b), "w", "Bf")[2]
    n_bad = 0
    for r in rows(os.path.join(DATA, "wind_words.csv")):
        term, b = r["term"], r["beaufort"].strip().lower()
        flag, _, iso, _ = conv(term, "w", "words")
        if b in ("qualitative", "unknown"):
            ok = flag == b
            want = b
        elif b == "":
            ok, want = flag == "unmapped", "unmapped"
        else:
            want = bf_ms.get(int(float(b)))
            ok = iso == want or (term == "calm" and iso == 0.0)
        if not ok:
            n_bad += 1
            print(f"   {term!r}: table says {r['beaufort']} ({want}), csv2sef gives {iso!r} {flag or ''}")
    print(f"   {n_bad} problem(s)")
    problems += n_bad

    print("\n4. weather_terms.csv: does each term, written alone, give its own code?")
    n_bad = 0
    for term, code, match in OPTS["weather_terms"]:
        flag, _, iso, _ = conv(term, "ww", "mno")
        want = None if code.lower() == "unknown" else " ".join(c for c in code.split() if c.lower() != "unknown")
        if iso != want:
            n_bad += 1
            print(f"   {term!r} ({match}): table code {code!r}, csv2sef gives {iso!r} {flag or ''}")
    print(f"   {n_bad} term(s) shadowed or changed by other rows - check whether that is intended")

    print(f"\n{problems} coverage problem(s) in sections 1-3")
    return problems


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
