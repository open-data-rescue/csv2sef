# -*- coding: utf-8 -*-
"""Range checks (in SI units, by region) and cross-variable checks."""
import datetime as dt
from collections import defaultdict

from . import tables
from .convert import Context


def range_check(records, region, log):
    limits = tables.ranges(region)
    for r in records:
        q = r["quantity"]
        x = r["iso_value"]
        if not q or q not in limits or not isinstance(x, (int, float)):
            continue
        lim = limits[q]
        flag = None
        if (lim["out_min"] is not None and x < lim["out_min"]) or \
           (lim["out_max"] is not None and x > lim["out_max"]):
            flag = "out of range"
        elif lim["low"] is not None and x < lim["low"]:
            flag = "low value"
        elif lim["high"] is not None and x > lim["high"]:
            flag = "high value"
        if flag:
            r["flag"] = "; ".join(filter(None, [r["flag"], flag]))
            log.write(Context(r["row"], r["column"], r["date"], r["var"]), "RANGE",
                      f"{r['orig_value']} -> {x} {r['iso_unit']}: {flag} ({region} limits)")


def cross_checks(records, log, tn_night_after=False):
    by_key = defaultdict(dict)
    for r in records:
        if isinstance(r["iso_value"], (int, float)):
            by_key[(r["date"], r["hour"], r["minute"])][r["var"]] = r

    def note(rec, msg, flag=None):
        log.write(Context(rec["row"], rec["column"], rec["date"], rec["var"]), "CROSS", msg)
        if flag:
            rec["flag"] = "; ".join(filter(None, [rec["flag"], flag]))

    for (date, h, mi), v in by_key.items():
        if h is None:
            continue
        if "tb" in v and "tdb" in v and v["tb"]["iso_value"] > v["tdb"]["iso_value"] + 0.3:
            note(v["tb"], f"Wet bulb {v['tb']['orig_value']} > dry bulb {v['tdb']['orig_value']}",
                 "wet bulb > dry bulb")
        if "ta" in v and "tdb" in v and abs(v["ta"]["iso_value"] - v["tdb"]["iso_value"]) > 3:
            note(v["ta"], f"Air temperature {v['ta']['orig_value']} differs from dry bulb "
                          f"{v['tdb']['orig_value']}")

    day_ta = defaultdict(list)
    for (date, h, mi), v in by_key.items():
        if h is not None and "ta" in v:
            day_ta[date].append(v["ta"])
    for (date, h, mi), v in by_key.items():
        if h is not None:
            continue
        for mn, mx in (("Tn", "Tx"),):
            if mn in v and mx in v and v[mn]["iso_value"] > v[mx]["iso_value"]:
                note(v[mn], f"Minimum {v[mn]['orig_value']} > maximum {v[mx]['orig_value']}")
        if "Tn" in v and day_ta.get(date):
            if tn_night_after:
                nxt = date + dt.timedelta(days=1)
                cands = [r for r in day_ta[date] if r["hour"] >= 12] + \
                        [r for r in day_ta.get(nxt, []) if r["hour"] < 12]
            else:
                cands = day_ta[date]
            if cands:
                low = min(cands, key=lambda r: r["iso_value"])
                if v["Tn"]["iso_value"] > low["iso_value"] + 0.5:
                    note(v["Tn"], f"Minimum {v['Tn']['orig_value']} > {low['column']} "
                                  f"{low['orig_value']} on {low['date']}")
        if "Tx" in v and day_ta.get(date):
            high = max(day_ta[date], key=lambda r: r["iso_value"])
            if v["Tx"]["iso_value"] < high["iso_value"] - 0.5:
                note(v["Tx"], f"Maximum {v['Tx']['orig_value']} < {high['column']} {high['orig_value']}")
