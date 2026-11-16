# -*- coding: utf-8 -*-
"""Conversion pipeline: input table + metadata -> clean/ISO csv files and SEF files."""
import csv
import datetime as dt
import importlib.metadata
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional, Tuple

from . import metadata as mdmod
from . import reader, sef, tables
from .checks import cross_checks, range_check
from .convert import Context, Logger, process_value
from .headers import normalise, parse_time, parse_when, split_unit

# columns that identify the record rather than holding observations: ignored quietly
ID_COLUMNS = {"observer", "observer id", "observer_id", "station", "station id", "station_id",
              "stationname", "station name", "timezone", "utcoffset", "utc offset", "utcdate",
              "utc date", "fieldid", "field id", "field_id", "page", "page id", "page_id",
              "image", "image file", "source", "id", "annotationid", "transcriptionid"}


@dataclass
class Column:
    index: int
    header: str
    var: str
    time: Optional[Tuple[int, int]]
    time_label: Optional[str]
    unit: str
    unit_source: str
    stat: str
    period: str
    vbl: str
    quantity: str
    description: str
    header_meta: str = ""
    suffix: str = ""
    problems: list = field(default_factory=list)


# --------------------------------------------------------------------------
def identify_variable(text, md):
    """'ta 07:00' -> ('ta', '07:00'); 'Thermometer Air AM' -> ('ta', 'AM'). None if unknown."""
    known = tables.variables()
    first, _, rest = text.partition(" ")
    for cand in (first, first.strip("'\"")):
        if cand in known or cand in md.variables:
            return cand, rest
    ci = [k for k in known if k.lower() == first.lower()]
    if len(ci) == 1:
        return ci[0], rest
    name = tables.norm_name(text)
    aliases = dict(tables.variable_aliases())
    aliases.update({tables.norm_name(k): v for k, v in md.aliases.items()})   # user's first
    for alias in sorted(aliases, key=len, reverse=True):
        if name == alias or name.startswith(alias + " "):
            # rest = remaining words of the original header
            n_words = len(alias.split())
            words = text.replace("_", " ").split()
            return aliases[alias], " ".join(words[n_words:])
    return None, None


def resolve_column(index, raw_header, md):
    """Work out variable, time, unit and SEF settings for one data column."""
    header = normalise(raw_header)
    text, unit_token = split_unit(header)
    var, rest = identify_variable(text, md)
    if var is None:
        return None, f"unknown variable '{text}' (see `csv2sef variables`; add alias.{text} = <code> " \
                     f"or ignore.{text} = yes to the metadata)"
    known = tables.variables()
    base = dict(known.get(var, {}))
    over = dict(md.variables.get(var, {}))
    for key in (header, text):
        over.update(md.columns.get(key, {}))
    if "variable" in over:                        # column re-assigned in the metadata
        var = over.pop("variable")
        base = dict(known.get(var, {}))
    d = {**base, **over}
    time, label, problem = parse_when(rest)
    problems = [problem] if problem else []

    # unit: header [unit] > metadata column/variable > unit.<var> > variables.csv default
    default_unit = base.get("unit", "")
    unit, source = None, "default"
    for token, src in ((unit_token, "header"), (over.get("unit"), "metadata"),
                       (md.units.get(var), "metadata"), (default_unit, "default")):
        if token and str(token).strip().lower() not in ("na", "n/a", "none", "-"):
            u = tables.canonical_unit(token)
            if u is None:
                problems.append(f"unknown unit '{token}' ({src})")
                continue
            unit, source = u, src
            break
    if unit is None:
        return None, "; ".join(problems) or f"no unit for '{var}'"
    # a weather column marked [text] is still a weather description to be coded
    if unit == "text" and default_unit == "mno":
        unit, source = "mno", source + " (text -> weather codes)"

    # time: metadata column/variable time= overrides the header
    if "time" in over:
        t = str(over["time"]).strip()
        if t.lower() in ("", "none", "daily", "day"):
            time, label = None, None
        else:
            time = parse_time(t)
            label = None if time else t
    if over.get("period") == "day" and "time" not in over:
        time, label = None, None                 # column declared daily in the metadata
    if time is None and label is None:
        period = "day"
    else:
        period = over.get("period") or base.get("period", "0")
    if label:
        problems.append(f"approximate time '{label}': SEF Hour/Minute will be NA "
                        f"(set column.{header} = time=HH:MM in the metadata if known)")
    return Column(index, header, var, time, label, unit, source,
                  d.get("stat", "point"), period, d.get("sef_vbl") or d.get("vbl") or var,
                  d.get("quantity", ""), d.get("description", ""),
                  d.get("header_meta", ""), d.get("suffix", ""), problems), None


def unit_on(md, var, date, unit):
    for ch in md.unit_changes:
        if ch["var"] != var:
            continue
        f = dt.date.fromisoformat(ch["from"]) if ch["from"] else dt.date.min
        t = dt.date.fromisoformat(ch["to"]) if ch["to"] else dt.date.max
        if f <= date <= t:
            return tables.canonical_unit(ch["unit"]) or ch["unit"]
    return unit


# --------------------------------------------------------------------------
def _empty(v):
    return v.strip().lower() in ("", "na", "n/a", "nan", "none")


def observations(table, md, log):
    """Return (list of (line, date, Column, raw value), columns, skipped, ignored, issues)."""
    cols, julian = reader.date_columns(table.headers)
    issues, columns, skipped, ignored = [], [], [], []
    if not ("date" in cols or {"year", "month", "day"} <= set(cols)):
        raise SystemExit("ERROR: no date columns found (need Year, Month, Day or Date)")

    def is_ignored(h):
        n = normalise(h).lower()
        return n in ID_COLUMNS or n.replace(" ", "_") in ID_COLUMNS or n in md.ignore

    if table.layout == "wide":
        date_idx = set(cols.values()) | ({julian} if julian is not None else set())
        for i, hd in enumerate(table.headers):
            if i in date_idx or not hd:
                continue
            if is_ignored(hd):
                ignored.append(hd)
                continue
            c, err = resolve_column(i, hd, md)
            if c:
                columns.append(c)
            else:
                skipped.append((hd, err))
    else:
        lc = reader.long_columns(table.headers)
        used = set(lc.values()) | set(cols.values()) | ({julian} if julian is not None else set())
        ignored = [h for i, h in enumerate(table.headers) if i not in used and h]
        ignored_vars = []
        cache = {}
    midnight_daily = mdmod.truthy(md.get("midnight_means_daily", "no"))

    seen = {}
    out = []
    for n, row in table.rows:
        try:
            date, dtime = reader.parse_datetime(row, cols)
        except (ValueError, KeyError) as e:
            log.write(Context(n, "date", None, ""), "DATE", f"Invalid date ({e}) - row skipped")
            issues.append(f"line {n}: invalid date")
            continue
        if julian is not None and row[julian].strip():
            try:
                if int(float(row[julian])) != date.timetuple().tm_yday:
                    log.write(Context(n, "date", date, ""), "DATE",
                              f"Julian day {row[julian]} does not match date "
                              f"(day of year {date.timetuple().tm_yday})")
                    issues.append(f"line {n}: Julian day {row[julian]} does not match {date}")
            except ValueError:
                pass
        if table.layout == "wide":
            if date in seen:
                log.write(Context(n, "date", date, ""), "DATE", f"Duplicate date (also line {seen[date]})")
                issues.append(f"line {n}: duplicate date {date} (also line {seen[date]})")
            seen[date] = n
            for c in columns:
                out.append((n, date, c, row[c.index]))
        else:
            hd = row[lc["variable"]].strip()
            if is_ignored(hd):
                if hd not in ignored:
                    ignored.append(hd)
                continue
            t = row[lc["time"]].strip() if "time" in lc else (dtime or "")
            if t and not (midnight_daily and t in ("00:00", "0:00", "00:00:00")):
                hd += " " + t
            if "unit" in lc and row[lc["unit"]].strip():
                hd += f" [{row[lc['unit']].strip()}]"
            if hd not in cache:
                c, err = resolve_column(-1, hd, md)
                cache[hd] = c
                if c:
                    columns.append(c)
                else:
                    skipped.append((hd, err))
            c = cache[hd]
            if c:
                val = row[lc["value"]]
                key = (date, c.header)
                if key in seen:                       # second value for the same date/time
                    j = seen[key]
                    prev = out[j][3]
                    if _empty(val):
                        continue                      # keep the earlier value
                    if _empty(prev):
                        out[j] = (n, date, c, val)    # replace an empty earlier value
                        continue
                    if prev.strip() == val.strip():
                        continue                      # identical repeat
                    log.write(Context(n, c.header, date, c.var), "DUPLICATE",
                              f"Different value '{val}' for the same date/time "
                              f"(line {out[j][0]} has '{prev}'); both kept")
                    issues.append(f"line {n}: {c.header} on {date}: '{val}' vs '{prev}' (line {out[j][0]})")
                else:
                    seen[key] = len(out)
                out.append((n, date, c, val))
    return out, columns, skipped, ignored, issues


# --------------------------------------------------------------------------
def build_records(obs, md, log, opts):
    to_utc = mdmod.truthy(md.get("convert_to_utc", "yes"))
    offset = md.site["utc_offset"]
    daily_stamp = md.get("daily_timestamp", "next_midnight")
    to_remarks = mdmod.truthy(md.get("unmapped_weather_to_remarks", "yes"))
    records = []
    for n, date, c, raw in obs:
        unit = unit_on(md, c.var, date, c.unit)
        if c.unit == "text" and _empty(raw):
            continue                                   # empty remark: nothing written
        ctx = Context(n, c.header, date, c.var)
        flag, clean, iso, iu = process_value(raw, c.var, unit, ctx, log, opts)
        local = dt.datetime(date.year, date.month, date.day)
        if c.time is not None:
            local += dt.timedelta(hours=c.time[0], minutes=c.time[1])
            stamp = local - dt.timedelta(hours=offset) if to_utc else local
            hour, minute = stamp.hour, stamp.minute
        elif c.time_label:                             # approximate time: Hour/Minute NA
            stamp, hour, minute = local, None, None
        elif daily_stamp == "next_midnight":
            stamp = local + dt.timedelta(days=1)
            hour, minute = 0, 0
        else:
            stamp, hour, minute = local, None, None
        records.append({
            "row": n, "date": date, "column": c.header, "var": c.var, "vbl": c.vbl,
            "stat": c.stat, "period": c.period, "quantity": c.quantity, "suffix": c.suffix,
            "header_meta": c.header_meta, "local_time": c.time, "time_label": c.time_label, "hour": c.time[0] if c.time else None,
            "minute": c.time[1] if c.time else None, "stamp": stamp,
            "sef_hour": hour, "sef_minute": minute,
            "orig_value": raw.strip(), "orig_unit": unit, "clean_value": clean,
            "iso_value": iso, "iso_unit": iu, "flag": flag,
        })
        if to_remarks and unit == "mno" and flag and "unmapped" in flag:
            rec = dict(records[-1])                    # weather text with no code -> remarks
            rec.update({"var": "remarks", "vbl": "remarks", "stat": "point", "quantity": "",
                        "suffix": "", "header_meta": "", "orig_unit": "text", "clean_value": raw.strip(),
                        "iso_value": raw.strip(), "iso_unit": "text", "flag": None})
            records[-1]["flag"] = flag + "; text in remarks"
            records.append(rec)
    return records


def options(md):
    return {
        "trace_mm": float(md.get("trace_mm", 0.2)),
        "caves_temperature_c": md.get("caves_temperature_c", 12.8),
        "below_scale_c": md.get("below_scale_c", ""),
        "keep_wind_cloud_type": mdmod.truthy(md.get("keep_wind_cloud_type", "no")),
        "wind_words": {**tables.wind_words(md.file_setting("wind_words_file")), **md.wind_words},
        "weather_terms": md.weather_terms + tables.weather_terms(md.file_setting("weather_terms_file")),
    }


# --------------------------------------------------------------------------
def run(data_path, meta_path, outdir=None, check_only=False, local_time=False, quiet=False):
    md = mdmod.load(meta_path)
    if local_time:
        md.settings["convert_to_utc"] = "no"
    site = md.site
    table = reader.read(data_path, md.get("sheet"))
    if outdir is None:
        outdir = os.path.join(os.path.dirname(os.path.abspath(data_path)), f"sef_output_{site['id']}")
    prefix = "_".join(p for p in (site.get("source", ""), site["id"]) if p)
    if not check_only:
        os.makedirs(os.path.join(outdir, "SEF"), exist_ok=True)
    log = Logger(None if check_only else os.path.join(outdir, prefix + ".log"))
    log.info(f"csv2sef {importlib.metadata.metadata(__package__)['Version']}  input: {os.path.basename(data_path)}  "
             f"metadata: {os.path.basename(meta_path)}")
    for note in md.notes:
        log.info(note)

    obs, columns, skipped, ignored, issues = observations(table, md, log)
    opts = options(md)
    records = build_records(obs, md, log, opts)
    range_check(records, md.get("range_region", "global"), log)
    cross_checks(records, log, mdmod.truthy(md.get("tn_night_after", "no")))

    groups = group_records(records)
    report = make_report(data_path, table, md, columns, skipped, ignored, issues, records, groups, log)
    if check_only:
        return report
    write_csvs(records, site, outdir, prefix)
    written = write_sef_files(groups, md, outdir)
    log.info("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(log.counts.items())))
    log.close()
    report += "\n\nOutput: " + outdir + "\n" + "\n".join(
        f"  SEF/{f}: {n} lines, {ok} with values" for f, n, ok in written)
    bad = {f: sef.validate(os.path.join(outdir, "SEF", f)) for f, _, _ in written}
    bad = {f: p for f, p in bad.items() if p}
    report += "\nSEF validation: " + ("all files valid" if not bad else
                                       "; ".join(f"{f}: {p[0]}" for f, p in bad.items()))
    return report


def group_records(records):
    groups = defaultdict(list)
    for r in records:
        if r["iso_unit"] == "text" and r["var"] != "remarks":
            continue
        groups[(r["vbl"], r["stat"], r["period"], r["suffix"])].append(r)
    count = Counter(k[0] for k in groups)
    named = {}
    for (vbl, stat, period, suffix), recs in groups.items():
        if not suffix and count[vbl] > 1:
            suffix = "_daily" if period == "day" else ("" if stat == "point" else f"_{stat}")
        named[(vbl, stat, period, suffix)] = recs
    return named


def write_csvs(records, site, outdir, prefix):
    fields_clean = ["station", "year", "month", "day", "local_time", "column", "variable", "line",
                    "orig_value", "clean_value", "orig_unit", "flag"]
    fields_iso = ["station", "year", "month", "day", "local_time", "column", "variable", "line",
                  "orig_value", "orig_unit", "iso_value", "iso_unit", "flag", "sef_datetime"]
    with open(os.path.join(outdir, prefix + "_clean.csv"), "w", newline="", encoding="utf-8") as fc, \
         open(os.path.join(outdir, prefix + "_iso.csv"), "w", newline="", encoding="utf-8") as fi:
        wc, wi = csv.writer(fc), csv.writer(fi)
        wc.writerow(fields_clean)
        wi.writerow(fields_iso)
        for r in records:
            lt = (f"{r['local_time'][0]:02d}:{r['local_time'][1]:02d}" if r["local_time"]
                  else (r["time_label"] or "daily"))
            base = [site["name"], r["date"].year, r["date"].month, r["date"].day, lt,
                    r["column"], r["var"], r["row"]]
            wc.writerow(base + [r["orig_value"], "" if r["clean_value"] is None else r["clean_value"],
                                r["orig_unit"], r["flag"] or ""])
            st = r["stamp"].strftime("%Y-%m-%d") + (
                "" if r["sef_hour"] is None else f" {r['sef_hour']:02d}:{r['sef_minute']:02d}")
            wi.writerow(base + [r["orig_value"], r["orig_unit"],
                                "" if r["iso_value"] is None else r["iso_value"],
                                r["iso_unit"], r["flag"] or "", st])


def write_sef_files(groups, md, outdir):
    site = md.site
    keep_na = mdmod.truthy(md.get("keep_na", "yes"))
    to_utc = mdmod.truthy(md.get("convert_to_utc", "yes"))
    missing = md.get("sef_missing_value", "NA")
    written = []
    for (vbl, stat, period, suffix), recs in sorted(groups.items()):
        recs = sorted(recs, key=lambda r: (r["stamp"], r["column"]))
        ok = [i for i, r in enumerate(recs) if r["iso_value"] is not None]
        if not ok:
            continue
        recs = recs[ok[0]:ok[-1] + 1]                     # trim leading/trailing missing
        if not keep_na:
            recs = [r for r in recs if r["iso_value"] is not None]
        hmeta = []
        if site.get("data_policy"):
            hmeta.append(f"Data policy={site['data_policy']}")
        if site.get("observer"):
            hmeta.append(f"Observer={site['observer']}")
        if site.get("notes"):
            hmeta.append(site["notes"])
        if recs[0]["header_meta"]:
            hmeta.append(recs[0]["header_meta"])
        if period == "day":
            hmeta.append("Daily values stamped 00:00 local time of the following day"
                         if md.get("daily_timestamp", "next_midnight") == "next_midnight" else
                         "Daily values: Hour and Minute not given")
        else:
            off = site["utc_offset"]
            how = f" ({site['utc_offset_note']})" if site.get("utc_offset_note") else ""
            hmeta.append(f"UTCOffset=YES|Local time offset={off:+g} h{how}" if to_utc
                         else f"UTCOffset=NO (local time; offset {off:+g} h{how})")
        if any(r["orig_unit"] == "De_frz" for r in recs):
            hmeta.append("orig De = Delisle degrees counted from freezing (C = De x 2/3)")
        if any(r["time_label"] for r in recs):
            hmeta.append("Hour and Minute NA where only an approximate time (time=...) is known")
        hmeta.append(f"Converted with csv2sef {importlib.metadata.metadata(__package__)['Version']}")
        rows = []
        for r in recs:
            meta = []
            if r["orig_value"] and r["orig_unit"] not in ("text",):
                ou = r["orig_unit"] if (r["orig_unit"] not in ("mno", "words", "dir", "lct", "uct")
                                        and r["orig_value"][-1:].isdigit()) else ""
                ou = {"De_frz": "De", "%": "%"}.get(ou, ou)
                meta.append(f"orig={r['orig_value']}{ou}")
            if r["flag"]:
                meta.append(f"qc={r['flag']}")
            if r["time_label"]:
                meta.append(f"time={r['time_label']}")
            rows.append({"year": r["stamp"].year, "month": r["stamp"].month, "day": r["stamp"].day,
                         "hour": r["sef_hour"], "minute": r["sef_minute"],
                         "period": period, "value": r["iso_value"], "meta": meta})
        fname = sef.filename(site, vbl, recs[0]["date"], recs[-1]["date"], suffix)
        sef.write(os.path.join(outdir, "SEF", fname), site, vbl, stat, recs[0]["iso_unit"],
                  "|".join(hmeta), rows, missing)
        written.append((fname, len(rows), sum(1 for r in recs if r["iso_value"] is not None)))
    return written


# --------------------------------------------------------------------------
def make_report(data_path, table, md, columns, skipped, ignored, issues, records, groups, log):
    s = md.site
    dates = sorted({r["date"] for r in records})
    L = [f"csv2sef {importlib.metadata.metadata(__package__)['Version']} - {os.path.basename(data_path)}",
         f"Station: {s['name']} (id {s['id']})  lat {s['lat']}  lon {s['lon']}  alt {s['alt']}",
         f"Layout: {table.layout}; {len(table.rows)} data lines" +
         (f"; {dates[0]} to {dates[-1]}" if dates else ""),
         f"Times: {'converted to UTC' if mdmod.truthy(md.get('convert_to_utc', 'yes')) else 'local'}"
         f" (local = UTC {s['utc_offset']:+g} h{', from longitude' if s.get('utc_offset_note') else ''})"]
    L += [f"Note: {n}" for n in md.notes]
    L.append("")
    L.append(f"{'Column':28} {'Variable':9} {'Time':6} {'Unit':12} {'from':9} {'-> SI':8} {'Stat':8} "
             f"{'values':>6} {'flagged':>7}")
    by_col = defaultdict(list)
    for r in records:
        by_col[r["column"]].append(r)
    for c in columns:
        rs = by_col.get(c.header, [])
        nval = sum(1 for r in rs if r["iso_value"] is not None)
        nflag = sum(1 for r in rs if r["flag"] and r["flag"] != "missing")
        t = (f"{c.time[0]:02d}:{c.time[1]:02d}" if c.time else
             (f"~{c.time_label}"[:6] if c.time_label else "daily"))
        iu = rs[0]["iso_unit"] if rs else ""
        L.append(f"{c.header[:28]:28} {c.var:9} {t:6} {c.unit:12} {c.unit_source.split()[0]:9} "
                 f"{iu[:8]:8} {c.stat:8} {nval:6d} {nflag:7d}")
        for p in c.problems:
            L.append(f"    ! {p}")
    for hd, err in skipped:
        L.append(f"{hd[:28]:28} SKIPPED: {err}")
    if ignored:
        L.append("Ignored (identifier columns or ignore.<name> in the metadata): " + ", ".join(ignored))
    flags = Counter()
    for r in records:
        for f in (r["flag"] or "").split("; "):
            if f:
                flags[f] += 1
    L.append("")
    L.append("Flags: " + (", ".join(f"{k} {v}" for k, v in flags.most_common()) or "none"))
    unm = Counter((r["column"], r["orig_value"]) for r in records
                  if r["flag"] and ("unmapped" in r["flag"] or "invalid" in r["flag"]))
    if unm:
        L.append("Values not converted (add them to wind_words.csv / weather_terms.csv or fix the data):")
        for (col, v), k in unm.most_common(15):
            L.append(f"    {col}: '{v}' x{k}")
    if issues:
        L.append(f"Date problems ({len(issues)}):")
        L += ["    " + i for i in issues[:10]]
    L.append("SEF files: " + ", ".join(f"{k[0]}{k[3]}" for k in sorted(groups)))
    return "\n".join(L)
