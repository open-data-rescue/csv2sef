# -*- coding: utf-8 -*-
"""
Writing and validating Station Exchange Format (SEF) 1.0.0 files.

Structure: 12 header lines (SEF, ID, Name, Lat, Lon, Alt, Source, Link, Vbl, Stat,
Units, Meta), a column line (Year Month Day Hour Minute Period Value Meta) and one
tab-separated line per observation. UTF-8, .tsv extension.
"""
import re

SEF_VERSION = "1.0.0"
HEADER_FIELDS = ["SEF", "ID", "Name", "Lat", "Lon", "Alt", "Source", "Link",
                 "Vbl", "Stat", "Units", "Meta"]
COLUMNS = ["Year", "Month", "Day", "Hour", "Minute", "Period", "Value", "Meta"]
TEXT_UNITS = {"text", "synoptic code", "cloud atlas code"}


def clean_text(s):
    return str(s).replace("\t", " ").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def _value(v, missing):
    if v is None:
        return missing
    if isinstance(v, float):
        return f"{v:g}" if (abs(v) >= 1e-3 or v == 0) else f"{v:.4f}"
    return clean_text(v)


def write(path, site, vbl, stat, units, header_meta, rows, missing="NA"):
    """rows: dicts with year, month, day, hour, minute, period, value, meta (list of str)."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        head = [SEF_VERSION, site["id"], clean_text(site["name"]), site["lat"], site["lon"],
                site["alt"], clean_text(site.get("source", "")), clean_text(site.get("link", "")),
                vbl, stat, units, header_meta]
        for k, v in zip(HEADER_FIELDS, head):
            f.write(f"{k}\t{v}\n")
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            na = lambda x: "NA" if x is None else str(x)
            f.write("\t".join([str(r["year"]), str(r["month"]), str(r["day"]), na(r["hour"]),
                               na(r["minute"]), str(r["period"]), _value(r["value"], missing),
                               "|".join(clean_text(m) for m in r["meta"])]) + "\n")


def filename(site, vbl, start, end, suffix=""):
    """<source>_<id>_<YYYY-MM>_<YYYY-MM>_<vbl>.tsv (as in dataresqc::write_sef)."""
    src = re.sub(r"[^A-Za-z0-9._-]", "", site.get("source", "")) or "NA"
    return f"{src}_{site['id']}_{start:%Y-%m}_{end:%Y-%m}_{vbl}{suffix}.tsv"


def validate(path):
    """Return a list of problems (empty list = valid SEF 1.0.0)."""
    problems = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except UnicodeDecodeError:
        return ["file is not UTF-8"]
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if len(lines) < 13:
        return [f"only {len(lines)} lines; need 12 header lines and a column line"]
    head = {}
    for i, name in enumerate(HEADER_FIELDS):
        parts = lines[i].split("\t")
        if parts[0] != name or len(parts) != 2:
            problems.append(f"line {i + 1}: expected '{name}<TAB>value', got '{lines[i][:40]}'")
        else:
            head[name] = parts[1]
    if head.get("SEF") != SEF_VERSION:
        problems.append(f"SEF version is '{head.get('SEF')}', expected {SEF_VERSION}")
    if "ID" in head and not re.fullmatch(r"[A-Za-z0-9._-]+", head["ID"]):
        problems.append("ID may only contain letters, digits, '-', '_' and '.'")
    for k, lo, hi in (("Lat", -90, 90), ("Lon", -180, 360)):
        try:
            x = float(head.get(k, "x"))
            if not lo <= x <= hi:
                problems.append(f"{k} {x} out of range")
        except ValueError:
            problems.append(f"{k} '{head.get(k)}' is not a number")
    if head.get("Alt", "NA") not in ("NA", ""):
        try:
            float(head["Alt"])
        except ValueError:
            problems.append(f"Alt '{head['Alt']}' is not a number")
    if lines[12].split("\t") != COLUMNS:
        problems.append("line 13 must be: " + " ".join(COLUMNS))
    textual = head.get("Units", "") in TEXT_UNITS
    for n, line in enumerate(lines[13:], start=14):
        c = line.split("\t")
        if len(c) != 8:
            problems.append(f"line {n}: {len(c)} columns instead of 8")
            continue
        try:
            y, mo = int(c[0]), c[1]
            if mo not in ("", "NA") and not 1 <= int(mo) <= 12:
                raise ValueError
            if c[2] not in ("", "NA") and not 1 <= int(c[2]) <= 31:
                raise ValueError
            if c[3] not in ("", "NA") and not 0 <= int(c[3]) <= 24:
                raise ValueError
            if c[4] not in ("", "NA") and not 0 <= int(c[4]) <= 59:
                raise ValueError
        except ValueError:
            problems.append(f"line {n}: invalid date/time {c[:5]}")
        if not textual and c[6] not in ("", "NA"):
            try:
                float(c[6])
            except ValueError:
                if c[6] not in ("Calm", "Variable"):
                    problems.append(f"line {n}: value '{c[6]}' is not numeric")
        if len(problems) > 50:
            problems.append("... (stopped after 50 problems)")
            break
    return problems
