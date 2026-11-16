# -*- coding: utf-8 -*-
"""
Station metadata and settings.

Preferred format: a two-column csv (key,value) that can be edited in a spreadsheet.
Create one with `csv2sef template`. JSON files (new or legacy config_<station>.json)
are also accepted.

Site keys      name, id, lat, lon, alt, source, link, project, country, observer,
               utc_offset (hours, local time minus UTC, e.g. -5; blank = nearest
               whole-hour time zone from the longitude), data_policy, notes
Settings       convert_to_utc (yes/no), daily_timestamp (next_midnight/date),
               keep_na (yes/no), range_region (global/canada), trace_mm,
               tn_night_after (yes/no), sheet, wind_words_file, weather_terms_file
Per variable   unit.<code>      e.g. unit.w = words
               variable.<code>  e.g. variable.p = header_meta=PTC=N|PGC=N
               column.<header>  e.g. column.ww 00:00 = period=day
               unit_change      e.g. w; mph; 1859-10-01; 1859-11-30   (repeatable)
               alias.<name>     e.g. alias.Thermometer Air = ta  (descriptive header name)
               ignore.<header>  e.g. ignore.Observer_ID = yes
Notation       caves_temperature_c (default 12.8: 'co' = Caves de l'Observatoire, Paris),
               below_scale_c (e.g. -34: value given to 'mercury in bulb'; '<=N' read in C),
               unmapped_weather_to_remarks (yes/no, default yes)
Long layout    midnight_means_daily (yes/no): a 00:00 time in a date-time column marks a
               daily value (as in database exports)
"""
import csv
import json
import os
import re

TEMPLATE = [
    ("# csv2sef station metadata", ""),
    ("# Site", ""),
    ("name", ""),
    ("id", ""),
    ("lat", ""),
    ("lon", ""),
    ("alt", ""),
    ("source", ""),
    ("link", ""),
    ("project", ""),
    ("country", ""),
    ("observer", ""),
    ("utc_offset", ""),
    ("data_policy", "CC-BY 4.0"),
    ("notes", ""),
    ("# Settings (defaults shown)", ""),
    ("convert_to_utc", "yes"),
    ("daily_timestamp", "next_midnight"),
    ("keep_na", "yes"),
    ("range_region", "global"),
    ("trace_mm", "0.2"),
    ("midnight_means_daily", "no"),
    ("unmapped_weather_to_remarks", "yes"),
    ("caves_temperature_c", "12.8"),
    ("below_scale_c", ""),
    ("tn_night_after", "no"),
    ("sheet", ""),
    ("wind_words_file", ""),
    ("weather_terms_file", ""),
    ("# Optional: alias.<column name> = <variable code>; ignore.<column> = yes; column.<header> = time=HH:MM", ""),
    ("# Units of variables whose header has no [unit]: unit.<variable>", ""),
]

DEFAULT_SETTINGS = {
    "convert_to_utc": "yes", "daily_timestamp": "next_midnight", "keep_na": "yes",
    "range_region": "global", "trace_mm": "0.2", "tn_night_after": "no",
}
SITE_KEYS = {"name", "id", "lat", "lon", "alt", "source", "link", "project", "country",
             "observer", "utc_offset", "data_policy", "notes", "org", "timezone"}


def truthy(v):
    return str(v).strip().lower() in ("yes", "y", "true", "1")


def _parse_kv(value):
    """'stat=mean; period=day' -> dict"""
    out = {}
    for item in value.split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class Metadata:
    def __init__(self):
        self.site = {}
        self.settings = dict(DEFAULT_SETTINGS)
        self.units = {}              # variable -> unit token
        self.variables = {}          # variable -> overrides
        self.columns = {}            # header -> overrides
        self.unit_changes = []       # dicts: var, unit, from, to
        self.aliases = {}            # descriptive column name -> variable code
        self.ignore = set()          # column headers to ignore
        self.wind_words = {}         # inline (JSON) wind words
        self.weather_terms = []      # inline (JSON) weather terms
        self.base_dir = "."
        self.notes = []              # messages about how the file was read

    # ------------------------------------------------------------------
    def get(self, key, default=None):
        v = self.settings.get(key, default)
        return default if v in ("", None) else v

    def file_setting(self, key):
        v = self.get(key)
        if not v:
            return []
        return [p if os.path.isabs(p) else os.path.join(self.base_dir, p)
                for p in (s.strip() for s in str(v).split(";")) if p]

    # ------------------------------------------------------------------
    def finalise(self):
        s = self.site
        missing = [k for k in ("name", "lat", "lon") if not str(s.get(k, "")).strip()]
        if missing:
            raise ValueError(f"Metadata is missing required site fields: {', '.join(missing)}")
        s["lat"] = float(s["lat"])
        lon = float(s["lon"])
        if lon > 180:
            lon -= 360
            self.notes.append("Longitude given as 0-360 east; converted to -180..180")
        s["lon"] = round(lon, 4)
        s["alt"] = s.get("alt") if str(s.get("alt", "")).strip() else "NA"
        if not str(s.get("id", "")).strip():
            s["id"] = re.sub(r"[^A-Za-z0-9._-]", "", s["name"].title().replace(" ", ""))
            self.notes.append(f"No station id given; using '{s['id']}'")
        else:
            s["id"] = re.sub(r"[^A-Za-z0-9._-]", "", str(s["id"]))
        s.setdefault("source", "")
        s.setdefault("link", "")
        if str(s.get("utc_offset", "")).strip() == "":
            # nearest whole-hour time zone (negative west of Greenwich)
            s["utc_offset"] = float(round(s["lon"] / 15.0))
            s["utc_offset_note"] = "nearest time zone to longitude"
            self.notes.append(f"No utc_offset given; using nearest time zone {s['utc_offset']:+g} h "
                              f"(longitude / 15 = {s['lon'] / 15:+.2f}, rounded)")
        else:
            s["utc_offset"] = float(s["utc_offset"])
        return self


# ----------------------------------------------------------------------
def load(path):
    md = Metadata()
    md.base_dir = os.path.dirname(os.path.abspath(path))
    if path.lower().endswith(".json"):
        _load_json(path, md)
    else:
        _load_csv(path, md)
    return md.finalise()


def _load_csv(path, md):
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            key = row[0].strip()
            if key.lower() == "key":
                continue                                  # header row
            value = row[1].strip() if len(row) > 1 else ""   # 3rd column = comment
            kl = key.lower()
            if kl in SITE_KEYS:
                md.site[kl] = value
            elif kl.startswith("unit."):
                md.units[key[5:].strip()] = value
            elif kl.startswith("variable."):
                md.variables[key[9:].strip()] = _parse_kv(value)
            elif kl.startswith("alias."):
                md.aliases[key[6:].strip()] = value
            elif kl.startswith("ignore."):
                if truthy(value or "yes"):
                    md.ignore.add(" ".join(key[7:].split()).lower())
            elif kl.startswith("column."):
                md.columns[" ".join(key[7:].split())] = _parse_kv(value)
            elif kl == "unit_change":
                parts = [p.strip() for p in value.split(";")]
                if len(parts) >= 2:
                    md.unit_changes.append({"var": parts[0], "unit": parts[1],
                                            "from": parts[2] if len(parts) > 2 else "",
                                            "to": parts[3] if len(parts) > 3 else ""})
            else:
                md.settings[kl] = value


def _load_json(path, md):
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    site = {k: v for k, v in j.get("site", {}).items() if not k.startswith("_")}
    legacy = "fields" in j or "types" in j
    # utcOffset in the legacy configs = hours ADDED to local time to get UTC (Halifax: 4)
    if "utcOffset" in site and "utc_offset" not in site:
        off = float(site.pop("utcOffset"))
        try:
            lon = float(site.get("lon"))
            lon = lon - 360 if lon > 180 else lon
        except (TypeError, ValueError):
            lon = 0
        # west of Greenwich local time is behind UTC: a positive legacy value means "add"
        if (lon < 0 and off > 0) or (lon > 0 and off < 0):
            off = -off
        site["utc_offset"] = off
        md.notes.append(f"utcOffset read as local time minus UTC = {off:+g} h")
    for k, v in site.items():
        md.site[k.lower()] = v
    if legacy:
        md.notes.append("Legacy config file: only 'site' and 'unitOverride' are used")
    for ov in j.get("unitOverride", []):
        md.unit_changes.append({"var": ov["type"], "unit": ov["unit"],
                                "from": ov.get("fromDate", ""), "to": ov.get("toDate", "")})
    proc = {k: v for k, v in j.get("processing", {}).items() if not k.startswith("_")}
    for k, v in proc.items():
        if isinstance(v, bool):
            v = "yes" if v else "no"
        md.settings[k] = str(v) if not isinstance(v, list) else v
    if "sef_meta" in site:
        md.site["notes"] = site["sef_meta"]
    for var, ov in j.get("variables", {}).items():
        if var.startswith("_"):
            continue
        ov = {k: v for k, v in ov.items() if not k.startswith("_")}
        if "unit" in ov:
            md.units[var] = ov.pop("unit")
        md.variables[var] = ov
    for col, ov in j.get("columns", {}).items():
        if not col.startswith("_"):
            md.columns[" ".join(col.split())] = {k: v for k, v in ov.items() if not k.startswith("_")}
    md.wind_words = {k.lower(): v for k, v in j.get("wind_words", {}).items() if not k.startswith("_")}
    md.weather_terms = [(k.lower(), v, "exact") for k, v in j.get("weather_terms", {}).items()
                        if not k.startswith("_")]


def write_template(path, variables=None):
    """Write a blank metadata csv. variables: list of (code, suggested unit, description)."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        for k, v in TEMPLATE:
            w.writerow([k, v])
        for code, unit, desc in (variables or []):
            w.writerow([f"unit.{code}", unit, f"# {desc}"])
