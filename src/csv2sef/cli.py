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
from email.utils import getaddresses
import os
import sys

# from . import CITATION
from . import metadata as mdmod
from . import pipeline, reader, sef, tables
from .headers import parse_header, split_unit

# from importlib.metadata

CITATION = ("Slonosky, V., Black, R., Podolsky, L., Wang, X. & Cheng, V. (2026). "
            "Transcribing historical Canadian weather data. Scientific Data 13, 678. "
            "https://doi.org/10.1038/s41597-025-06036-y")


def cmd_check(a):
    print(pipeline.run(a.data, a.metadata, check_only=True, local_time=a.local))


def cmd_convert(a):
    print(pipeline.run(a.data, a.metadata, outdir=a.outdir, local_time=a.local))


def _long_template_variables(t, known):
    """One-value-per-line files: unit.<variable> lines for variables whose rows have no unit,
    and the barometer variables (for the PTC/PGC line)."""
    lc = reader.long_columns(t.headers)
    md = mdmod.Metadata()
    names, has_unit = [], {}
    for _, row in t.rows:
        name = row[lc["variable"]].strip()
        if not name:
            continue
        if name not in has_unit:
            names.append(name)
            has_unit[name] = True
        if "unit" not in lc or not row[lc["unit"]].strip():
            has_unit[name] = False
    found, pressure, seen = [], [], set()
    for name in names:
        var, _ = pipeline.identify_variable(name, md)
        if var is None:
            if name not in seen:
                seen.add(name)
                found.append((name, None, "UNKNOWN variable"))
            continue
        d = known.get(var) or {}
        if d.get("quantity") == "pressure" and var not in pressure:
            pressure.append(var)
        if has_unit[name] or var in seen:
            continue                           # unit given on every line, or already listed
        seen.add(var)
        found.append((var, d.get("unit", ""), f"{d.get('description', var)} - usual unit, check it "
                                              "(some lines of the data have no unit)"))
    return found, pressure


def cmd_template(a):
    found = []
    pressure = []                              # barometer variables: PTC/PGC lines to fill in
    if a.data:
        t = reader.read(a.data)
        cols, julian = reader.date_columns(t.headers)
        known = tables.variables()
        seen = set()
        if t.layout == "long":
            found, pressure = _long_template_variables(t, known)
        md = mdmod.Metadata()
        for i, hd in enumerate(t.headers if t.layout == "wide" else []):
            if i in cols.values() or i == julian or not hd:
                continue
            text, unit_token = split_unit(hd)
            n = " ".join(text.lower().split())
            if n in pipeline.ID_COLUMNS or n.replace(" ", "_") in pipeline.ID_COLUMNS:
                continue                       # identifier column: skipped by convert too
            var, _ = pipeline.identify_variable(text, md)
            if var is None:
                if text not in seen:
                    seen.add(text)
                    found.append((text, None, "UNKNOWN variable"))
                continue
            d = known.get(var) or {}
            if d.get("quantity") == "pressure" and var not in pressure:
                pressure.append(var)
            if unit_token or var in seen:
                continue                       # unit already in the header, or already listed
            seen.add(var)
            found.append((var, d.get("unit", ""), d.get("description", var)))
    out = a.output or "metadata.csv"
    if os.path.exists(out) and not a.force:
        sys.exit(f"{out} exists; use --force to overwrite")
    mdmod.write_template(out, found, pressure)
    print(f"Wrote {out}. Fill in the site details"
          + (", check the unit.<variable> lines" if any(u is not None for _, u, _ in found) else "")
          + (", give a variable code to each alias. line" if any(u is None for _, u, _ in found) else "")
          + (" and the barometer corrections (PTC/PGC = Y or N)" if pressure else "") + ".")


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


def _version():
    try:
        return importlib.metadata.version(__package__)
    except importlib.metadata.PackageNotFoundError:          # run from the source folder, not installed
        return "(not installed)"


def _authors():
    """Author names from the package metadata: 'Vicky Slonosky, Hervé Hacot'."""
    try:
        raw = importlib.metadata.metadata(__package__).get("Author-email") or ""
    except importlib.metadata.PackageNotFoundError:
        return ""
    names = [name or addr for name, addr in getaddresses([raw]) if name or addr]
    return ", ".join(names)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="csv2sef",
        description=f"csv2sef {_version()}: historical weather csv/Excel -> SEF 1.0.0. "
                    f"Authors: {_authors()}.",
        epilog="Please cite: " + CITATION)
    p.add_argument("--version", action="version", version=f"csv2sef {_version()}")
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
