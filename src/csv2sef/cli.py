# -*- coding: utf-8 -*-
"""
Command line interface.

    csv2sef check    DATA METADATA          dry run: how each column will be read
    csv2sef convert  DATA METADATA [-o DIR] write clean/ISO csv, log and SEF files
    csv2sef template [DATA] [-o FILE]       write a blank metadata file
    csv2sef validate SEF_FILE ...           check SEF files against SEF 1.0.0
    csv2sef variables                       list known variables and units
"""
import argparse
import importlib.metadata
import os
import sys

# from . import CITATION
from . import metadata as mdmod
from . import pipeline, reader, sef, tables
from .headers import parse_header

# from importlib.metadata

CITATION = ("Slonosky, V., Black, R., Podolsky, L., Wang, X. & Cheng, V. (2026). "
            "Transcribing historical Canadian weather data. Scientific Data 13, 678. "
            "https://doi.org/10.1038/s41597-025-06036-y")


def cmd_check(a):
    print(pipeline.run(a.data, a.metadata, check_only=True, local_time=a.local))


def cmd_convert(a):
    print(pipeline.run(a.data, a.metadata, outdir=a.outdir, local_time=a.local))


def cmd_template(a):
    found = []
    if a.data:
        t = reader.read(a.data)
        cols, julian = reader.date_columns(t.headers)
        known = tables.variables()
        seen = set()
        for i, hd in enumerate(t.headers):
            if i in cols.values() or i == julian or not hd:
                continue
            h = parse_header(hd)
            if h.var in seen:
                continue
            seen.add(h.var)
            if h.unit_token:
                continue                       # unit already in the header
            d = known.get(h.var)
            found.append((h.var, d["unit"] if d else "", d["description"] if d else "UNKNOWN variable"))
    out = a.output or "metadata.csv"
    if os.path.exists(out) and not a.force:
        sys.exit(f"{out} exists; use --force to overwrite")
    mdmod.write_template(out, found)
    print(f"Wrote {out}. Fill in the site details"
          + (" and check the unit.<variable> lines." if found else "."))


def cmd_validate(a):
    bad = 0
    for p in a.files:
        probs = sef.validate(p)
        print(f"{p}: {'OK' if not probs else 'INVALID'}")
        for x in probs[:10]:
            print("   ", x)
        bad += bool(probs)
    sys.exit(1 if bad else 0)


def cmd_variables(a):
    print(f"{'code':11} {'default unit':13} {'stat':8} description")
    for code, d in tables.variables().items():
        print(f"{code:11} {d['unit']:13} {d['stat']:8} {d['description']}")
    print("\nUnits (write in the header in [ ], e.g. 'ta 07:00 [F]'):")
    for u, desc in tables.unit_descriptions().items():
        print(f"  {u:13} {desc}")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="csv2sef",
        description=f"csv2sef {importlib.metadata.metadata(__package__)['Version']}: historical weather csv/Excel -> SEF 1.0.0. "
                    f"Authors: {', '.join(importlib.metadata.metadata(__package__)['Author-email'])}.",
        epilog="Please cite: " + CITATION)
    p.add_argument("--version", action="version", version=f"csv2sef {importlib.metadata.metadata(__package__)['Version']}")
    sub = p.add_subparsers(dest="cmd")

    for name, fn, hlp in (("check", cmd_check, "dry run: show how each column will be read"),
                          ("convert", cmd_convert, "convert and write SEF files")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("data", help="csv, tsv or xlsx file")
        s.add_argument("metadata", help="metadata csv (or json)")
        s.add_argument("--local", action="store_true", help="keep local times (no UTC conversion)")
        if name == "convert":
            s.add_argument("-o", "--outdir", help="output directory")
        s.set_defaults(func=fn)

    s = sub.add_parser("template", help="write a blank metadata file")
    s.add_argument("data", nargs="?", help="optional data file: adds unit lines for its variables")
    s.add_argument("-o", "--output", help="output file (default metadata.csv)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_template)

    s = sub.add_parser("validate", help="validate SEF files")
    s.add_argument("files", nargs="+")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("variables", help="list known variables and units")
    s.set_defaults(func=cmd_variables)

    argv = sys.argv[1:] if argv is None else argv
    # shorthand: csv2sef DATA METADATA  == convert
    if len(argv) >= 2 and argv[0] not in sub.choices and not argv[0].startswith("-"):
        argv = ["convert"] + argv
    a = p.parse_args(argv)
    if not getattr(a, "func", None):
        p.print_help()
        return
    a.func(a)


if __name__ == "__main__":
    main()
