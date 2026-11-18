# -*- coding: utf-8 -*-
"""Known-value tests for every csv2sef conversion.

Reads tests/known_values.csv (one row per test) and converts each input with csv2sef.
Expected values come from published factors and tables, NOT from csv2sef itself.

Run from the csv2sef folder (local layout or GitHub layout with src/):
    python -m unittest tests.test_known_values -v
or, to print a table of every row (also the rows still to fill in):
    python tests/test_known_values.py --report

Columns of known_values.csv
    unit, var, input   what csv2sef is given
    expected           value in SI units; NA = must be missing; blank = not filled in yet
    expected_flag      quality flag csv2sef must give (blank = no flag)
    tolerance          allowed difference for numbers (blank = exact match, for codes/text)
    opts               settings, e.g. caves_temperature_c=12.8;below_scale_c=-34
    status             formula (standard factor, must pass) | to_check (expected value to be confirmed:
                       reported, not failed) | to_fill (no expected value yet)
"""
import csv
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "src"), ROOT):           # GitHub layout (src/) or local layout
    if os.path.isdir(os.path.join(p, "csv2sef")):
        sys.path.insert(0, p)
        break

from csv2sef import tables                                     # noqa: E402
from csv2sef.convert import Context, Logger, process_value     # noqa: E402

TABLE = os.path.join(HERE, "known_values.csv")
BASE_OPTS = {"wind_words": tables.wind_words(),               # trace_mm: csv2sef default, unless a row sets it
             "weather_terms": tables.weather_terms()}


def load_rows():
    with open(TABLE, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f) if r["id"] and not r["id"].startswith("#")]


def run_row(r):
    """Convert one test row -> (flag, iso_value, iso_unit), or ('ERROR: ...', None, None)."""
    opts = dict(BASE_OPTS)
    for item in filter(None, (r.get("opts") or "").split(";")):
        k, v = item.split("=", 1)
        opts[k.strip()] = v.strip()
    ctx = Context(int(r["id"]), r["unit"], dt.date(1860, 1, 1), r["var"])
    try:
        flag, _clean, iso, iu = process_value(r["input"], r["var"], r["unit"], ctx, Logger(), opts)
        return flag, iso, iu
    except Exception as e:                       # a crash is a result to report, not to hide
        return f"ERROR: {type(e).__name__}: {e}", None, None


def check(r, flag, iso):
    """Return a list of problems ([] = pass). Rows with status to_fill are never failures."""
    if r["status"] == "to_fill" or r["expected"] == "":
        return []
    problems = []
    exp = r["expected"]
    if flag and str(flag).startswith("ERROR"):
        return [flag]
    if exp == "NA":
        if iso is not None:
            problems.append(f"expected NA, got {iso!r}")
    elif r["tolerance"] == "":
        if str(iso) != exp:
            problems.append(f"expected {exp!r}, got {iso!r}")
    else:
        try:
            if iso is None or abs(float(iso) - float(exp)) > float(r["tolerance"]) + 1e-9:
                problems.append(f"expected {exp} +/- {r['tolerance']}, got {iso!r}")
        except (TypeError, ValueError):
            problems.append(f"expected {exp}, got non-number {iso!r}")
    if (flag or "") != r["expected_flag"]:
        problems.append(f"flag: expected {r['expected_flag']!r}, got {flag!r}")
    return problems


class TestKnownValues(unittest.TestCase):
    def test_all_rows(self):
        """Rows with status 'formula' must pass. Rows with status 'to_check' (expected value
        still to be confirmed) are reported but do not fail; a crash always fails."""
        to_check = []
        for r in load_rows():
            flag, iso, _ = run_row(r)
            problems = check(r, flag, iso)
            crashed = any(p.startswith("ERROR") for p in problems)
            if problems and r["status"] == "to_check" and not crashed:
                to_check.append(f"{r['id']} {r['unit']} {r['input']!r}: {'; '.join(problems)}")
                continue
            with self.subTest(id=r["id"], unit=r["unit"], input=r["input"]):
                self.assertFalse(problems, "; ".join(problems) + f"  [source: {r['source']}]")
        if to_check:
            print(f"\n{len(to_check)} known value(s) still to be confirmed (status to_check):")
            for line in to_check:
                print("   ", line)


def report(out=None):
    """Print (and optionally write to csv) every row with its result."""
    res = []
    for r in load_rows():
        flag, iso, iu = run_row(r)
        p = check(r, flag, iso)
        verdict = "TO FILL" if (r["status"] == "to_fill" or r["expected"] == "") else ("FAIL" if p else "ok")
        res.append({**r, "got": "" if iso is None else iso, "got_flag": flag or "", "iso_unit": iu or "",
                    "result": verdict, "problem": "; ".join(p)})
    w = max(len(x["input"]) for x in res)
    for x in res:
        print(f"{x['id']} {x['result']:8s} {x['unit']:12s} {x['input']:<{w}}  exp={x['expected']!s:<10} "
              f"got={x['got']!s:<10} {x['got_flag']}  {x['problem']}")
    n = {k: sum(x["result"] == k for x in res) for k in ("ok", "FAIL", "TO FILL")}
    print(f"\n{len(res)} rows: {n['ok']} ok, {n['FAIL']} fail, {n['TO FILL']} to fill")
    if out:
        with open(out, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(res[0]))
            wr.writeheader()
            wr.writerows(res)
        print("written:", out)
    return res


if __name__ == "__main__":
    if "--report" in sys.argv:
        i = sys.argv.index("--report")
        report(sys.argv[i + 1] if len(sys.argv) > i + 1 else None)
    else:
        unittest.main()
