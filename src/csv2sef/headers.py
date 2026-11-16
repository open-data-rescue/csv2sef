# -*- coding: utf-8 -*-
"""
Parsing of data-column headers.

    <variable> [<time>] [[<unit>]]

    ta 07:00 [F]              air temperature at 07:00, degrees Fahrenheit
    p 7am (inHg)              barometer at 07:00, inches of mercury
    Tn [F]                    daily (overnight) minimum
    ww daily                  daily weather remarks
    Thermometer Air AM        descriptive name (variable_aliases.csv) + time word

The variable may be a code from variables.csv or a descriptive name listed in
variable_aliases.csv (or added in the metadata with alias.<name> = <code>).

Times: HH:MM, H:MM, HHMM, 7am / 2 pm, sunrise (06:00), noon / meridian (12:00),
midnight (00:00). 'daily', 'day', '24h', 'mean', 'total' or no time = daily value.
Words such as AM, PM, morning, evening, night are kept as an approximate time label:
the SEF Hour/Minute are then NA unless an exact time is given in the metadata
(column.<header> = time=HH:MM).
"""
import re

NAMED_TIMES = {"sunrise": (6, 0), "noon": (12, 0), "meridian": (12, 0), "midnight": (0, 0)}
DAILY_WORDS = {"daily", "day", "24h", "24hr", "24hrs", "mean", "total", "overnight"}
TIME_WORDS = {"am", "a.m.", "pm", "p.m.", "morning", "forenoon", "afternoon", "evening",
              "night", "sunset", "matin", "soir", "midi", "après-midi", "apres-midi", "nuit"}


def normalise(h):
    """Collapse spaces, drop BOM / non-breaking spaces and surrounding quotes."""
    h = re.sub(r"\s+", " ", (h or "").replace("﻿", "").replace("\xa0", " ")).strip()
    while len(h) >= 2 and h[0] == h[-1] and h[0] in "'\"":
        h = h[1:-1].strip()
    return h


def split_unit(h):
    """'ta 07:00 [F]' -> ('ta 07:00', 'F')"""
    h = normalise(h)
    m = re.search(r"[\[\(]([^\]\)]*)[\]\)]\s*$", h)
    if m:
        return h[:m.start()].strip(), (m.group(1).strip() or None)
    return h, None


def parse_time(tok):
    t = tok.strip().lower().replace(" ", "").replace(".", "")
    if t in NAMED_TIMES:
        return NAMED_TIMES[t]
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?(?::\d{2})?(am|pm|h)?", t)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 24 or mi > 59:
        return None
    return h, mi


def parse_when(rest):
    """Text after the variable -> (time, label, problem).
    time None and label None = daily value; label = approximate time word."""
    tok = (rest or "").strip()
    if not tok or tok.lower() in DAILY_WORDS:
        return None, None, None
    t = parse_time(tok)
    if t is not None:
        return t, None, None
    if tok.lower() in TIME_WORDS:
        return None, tok, None
    return None, None, f"could not read time '{tok}'"


class Header:
    """Simple parse of a coded header: first word = variable code."""

    def __init__(self, raw):
        self.raw = raw
        text, self.unit_token = split_unit(raw)
        self.var, _, rest = text.partition(" ")
        self.time, self.label, self.problem = parse_when(rest)


def parse_header(raw):
    return Header(raw)
