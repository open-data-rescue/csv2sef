# -*- coding: utf-8 -*-
"""
Screening, clean-up and conversion of single transcribed values to SI units.

Ported from transcription_data_processing.py (Open Data Rescue) and Tables 3-9 of
Slonosky et al. (2026). Unit conversions use lmrlib.py (NOAA ICOADS).

    process_value(raw, var, unit, ctx, log, opts) -> (flag, clean_value, iso_value, iso_unit)
"""
import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from math import sqrt

from CDRUtilities import iso_mapping as im
from CDRUtilities import lmrlib as lmr

CM_VARS = {"sd", "swe", "fs"}      # snow depth, water equivalent, fresh snow: written in cm


# --------------------------------------------------------------------------
@dataclass
class Context:
    row: object       # line number in the input file
    column: str
    date: object
    var: str


class Logger:
    """Tab-separated validation log."""

    def __init__(self, path=None):
        self.f = open(path, "w", encoding="utf-8") if path else None
        if self.f:
            self.f.write("date\trow\tcolumn\tcategory\tmessage\n")
        self.counts = Counter()

    def write(self, ctx, category, msg):
        self.counts[category] += 1
        if self.f:
            d = ctx.date.isoformat() if ctx and ctx.date else ""
            self.f.write(f"{d}\t{ctx.row if ctx else ''}\t{ctx.column if ctx else ''}\t{category}\t{msg}\n")

    def info(self, msg):
        if self.f:
            self.f.write(f"\t\t\tINFO\t{msg}\n")

    def close(self):
        if self.f:
            self.f.close()


# --------------------------------------------------------------------------
# Missing / invalid values (Table 7)
# --------------------------------------------------------------------------
MISSING_EXACT = {"", "-", "--", "m", "na", "n/a", "nan", "missing", "none"}
# cloud type and cloud direction: "none" means no clouds (Table 5), not missing
CLOUD_TYPE_DIR_VARS = {"c", "cl", "ch", "cd", "hd"}
MISSING_TERMS = ["not.taken", "not taken", "unknown symbol", "retracted", "-999",
                 "no grass", "no place", "suspended", "abt on duty"]
INSTRUMENT_ERROR_TERMS = ["out of order", "out.of.order", "broken", "unserviceable", "-888",
                          "incorrect", "not reliable", "covered in snow", "covered with snow",
                          "no error", "frozen in position", "instrument error"]
BELOW_SCALE_TERMS = ["mercury in bulb", "mercury in the bulb", "mercury inside bulb",
                     "in the ball", "dans la boule", "frozen mercury", "mercury frozen"]
DITTO_MARKS = {'"', "'", "''", '""', "~", "”", "〃", "do", "do."}
TEXT_UNITS = {"mno", "text", "lct", "uct", "dir", "words", "oz"}
# explicit "empty"/"dot" typed by a transcriber = nothing to observe (legacy behaviour)
EMPTY_TOKEN_VALUE = {"Sm": "0", "Bf": "0", "mph": "0", "kt": "0", "m/s": "0", "km/h": "0",
                     "lbsft": "0", "words": "calm", "cloudvel": "0", "tenths": "0", "okta": "0",
                     "in": "0", "mm": "0", "cm": "0", "dir": "calm", "lct": "0", "uct": "0"}


def pre_screen(value, var, unit, ctx, log):
    v = (value or "").replace("\xa0", " ").strip()
    vl = v.lower()
    if vl in ("empty", "dot"):
        if unit in EMPTY_TOKEN_VALUE and var != "eee":
            return "ok", EMPTY_TOKEN_VALUE[unit], "no entry"
        return "stop", None, "missing"
    if vl in MISSING_EXACT and not (vl == "none" and var in CLOUD_TYPE_DIR_VARS):
        return "stop", None, "missing"
    if unit == "text":
        return "ok", v, None                      # free text is kept verbatim
    if vl == "*":
        log.write(ctx, "INSTRUMENT", "'*' - value not able to be recorded")
        return "stop", None, "instrument error"
    if vl in DITTO_MARKS:
        log.write(ctx, "DITTO", f"Ditto mark '{v}' - value not reconstructed")
        return "stop", None, "ditto"
    if all(ch in "?. " for ch in vl):
        log.write(ctx, "ILLEGIBLE", f"'{v}'")
        return "stop", None, "illegible"
    if unit != "mno" and any(x in vl for x in BELOW_SCALE_TERMS):
        log.write(ctx, "SCALE", f"'{v}': below the thermometer scale")
        return "stop", None, "below scale"     # value set in process_value if below_scale_c
    if unit != "mno" and any(x in vl for x in INSTRUMENT_ERROR_TERMS):
        log.write(ctx, "INSTRUMENT", f"Instrument error: '{v}'")
        return "stop", None, "instrument error"
    if "illegible" in vl and "cirrus" not in vl:
        log.write(ctx, "ILLEGIBLE", f"'{v}'")
        return "stop", None, "illegible"
    if unit not in TEXT_UNITS and any(x in vl for x in MISSING_TERMS):
        return "stop", None, "missing"
    if unit not in TEXT_UNITS and "?" in v:          # e.g. "37.?" -> 37, flagged uncertain
        stripped = v.replace("?", "").strip().rstrip(".")
        if re.search(r"\d", stripped):
            log.write(ctx, "UNCERTAIN", f"'{v}' read as '{stripped}'")
            return "ok", stripped, "uncertain"
        log.write(ctx, "ILLEGIBLE", f"'{v}'")
        return "stop", None, "illegible"
    return "ok", v, None


# --------------------------------------------------------------------------
# Numeric clean-up (Table 8)
# --------------------------------------------------------------------------
def clean_number(value, ctx, log):
    v = value.strip()
    orig = v
    v = v.replace("[", "").replace("]", "")
    if v.startswith("--"):
        v = "-" + v.lstrip("-")
    v = v.replace("- ", "-").replace("+ ", "").lstrip("+")
    if "/" in v:                                    # fractions: "37 1/2", "37.1/2"
        v = v.replace(".", " ").replace(",", " ")
        neg = v.startswith("-")
        res = float(sum(Fraction(s) for s in v.lstrip("-").split()))
        res = -res if neg else res
    else:
        v = v.replace(",", ".").replace(" ", ".")
        while ".." in v:
            v = v.replace("..", ".")
        v = v.rstrip(".")
        res = float(v)
    if v != orig:
        log.write(ctx, "SYNTAX", f"'{orig}' cleaned to {res:g}")
    return res


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


# --------------------------------------------------------------------------
# Converters: (v, var, ctx, log, opts) -> (flag, clean_value, iso_value)
# --------------------------------------------------------------------------
# size of one degree in degrees Celsius, and conversion to Celsius, per temperature unit
DEGREE_C = {"F": 5.0 / 9.0, "C": 1.0, "R": 1.25, "De": 2.0 / 3.0, "De_frz": 2.0 / 3.0}
TO_C = {"F": lambda x: lmr.temp_f2c(x), "C": lambda x: x, "R": lambda x: lmr.temp_r2c(x),
        "De": lambda x: 100.0 - x * 2.0 / 3.0,          # Delisle: 0 = boiling, 150 = freezing
        "De_frz": lambda x: x * 2.0 / 3.0}              # Delisle degrees counted from freezing
SUFFIX_UNIT = {"r": "R", "f": "F", "c": "C", "de": "De"}
NUM = r"(\d+(?:[.,]\d+)?)"


def _num(x):
    return float(x.replace(",", "."))


def temperature(v, unit, ctx, log, opts):
    """Temperature with historical notation -> (flag, clean value, degrees C).

    '16R' / '58F'      value in the unit given by the letter (overrides the column unit)
    '10+co', '2-c'     10 degrees above / 2 below the Caves de l'Observatoire (Paris),
                       taken as caves_temperature_c (default 12.8 C), whatever the scale of the reading; 'co', '=c' = caves
    '<=-34'            at or below -34 (in C if below_scale_c is set, else in the column unit)
    """
    s = v.strip().lower().replace("°", "").replace("º", "").replace(" ", "")
    s = s.replace("(", "").replace(")", "").strip("'\"")       # '+5 (R)', "-28 R'"
    if s.startswith("+"):
        s = s[1:]
    caves = float(opts.get("caves_temperature_c", 12.8))
    s = s.replace("c.o.", "co").replace("c.o", "co")
    CAVES = r"(?:co?|o|0)"            # c, co, c.o, o or 0 after a sign = the caves
    m = re.fullmatch(NUM + r"([+-])(" + CAVES + r")?(r|f|de)?", s)
    if m and (m.group(3) or not m.group(4)):
        x = _num(m.group(1))
        u = SUFFIX_UNIT.get(m.group(4) or "", unit)
        c = caves + (x if m.group(2) == "+" else -x) * DEGREE_C[u]
        flag = "caves notation" if m.group(3) else "caves notation (assumed)"
        log.write(ctx, "NOTATION", f"'{v}' = {m.group(2)}{x:g} {u} from the caves ({caves:g} C) -> {c:.2f} C")
        return flag, v, _r(c)
    if re.fullmatch(r"(?:0?=)?" + CAVES + r"(?:r|f)?", s) and s not in ("0",):
        log.write(ctx, "NOTATION", f"'{v}' = caves temperature {caves:g} C")
        return "caves notation", v, _r(caves)
    m = re.fullmatch(NUM + r"=" + CAVES + r"(r|f|de)?", s)
    if m:
        x = _num(m.group(1))
        if x == 0:
            return "caves notation", v, _r(caves)
        log.write(ctx, "NOTATION", f"'{v}': {x:g} degrees from the caves, sign unclear - not converted")
        return "caves notation, sign unclear", v, None
    m = re.fullmatch(r"(<=?|>=?|≤|≥)(-?\d+(?:[.,]\d+)?)([a-z]*)", s)
    if m:
        x = _num(m.group(2))
        flag = "at or below" if m.group(1) in ("<", "<=", "≤") else "at or above"
        u = SUFFIX_UNIT.get(m.group(3))
        if u is None:
            u = "C" if opts.get("below_scale_c") not in (None, "") else unit
        log.write(ctx, "LIMIT", f"'{v}': {flag} {x:g} {u}")
        return flag, x, _r(TO_C[u](x))
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)(r|f|c|de)", s)
    if m:
        u = SUFFIX_UNIT[m.group(2)]
        x = _num(m.group(1))
        if u != unit:
            log.write(ctx, "UNIT", f"'{v}' read in {u} (column unit {unit})")
        return (f"unit {u}" if u != unit else None), x, _r(TO_C[u](x))
    x = clean_number(v, ctx, log)
    return None, x, _r(TO_C[unit](x))


def c_F(v, var, ctx, log, opts):
    return temperature(v, "F", ctx, log, opts)


def c_C(v, var, ctx, log, opts):
    return temperature(v, "C", ctx, log, opts)


def c_R(v, var, ctx, log, opts):
    return temperature(v, "R", ctx, log, opts)


def c_De(v, var, ctx, log, opts):
    return temperature(v, "De", ctx, log, opts)


def c_De_frz(v, var, ctx, log, opts):
    return temperature(v, "De_frz", ctx, log, opts)


def c_Fdiff(v, var, ctx, log, opts):
    t = clean_number(v, ctx, log)
    return None, t, _r(t * 5.0 / 9.0)


def c_Cdiff(v, var, ctx, log, opts):
    t = clean_number(v, ctx, log)
    return None, t, _r(t)


def _vapour_decimal(v, p, var, ctx, log):
    if var.startswith("e") and var != "eee" and "." not in v and p > 1:
        log.write(ctx, "SYNTAX", f"Vapour pressure '{v}' read as {p / 1000:g}")
        return p / 1000.0, "missing decimal"
    return p, None


def c_inHg(v, var, ctx, log, opts):
    p = clean_number(v, ctx, log)
    p, flag = _vapour_decimal(v, p, var, ctx, log)
    return flag, p, _r(lmr.baro_Eng_in2mb(p))


def c_mmHg(v, var, ctx, log, opts):
    p = clean_number(v, ctx, log)
    p, flag = _vapour_decimal(v, p, var, ctx, log)
    return flag, p, _r(lmr.baro_mm2mb(p))


def c_hPa(v, var, ctx, log, opts):
    p = clean_number(v, ctx, log)
    return None, p, _r(p)


def c_ParisIn(v, var, ctx, log, opts):
    """French inches, optionally with lines: '27 11.5' or '27p 11.5l' = 27 in 11.5 lines."""
    nums = re.findall(r"\d+(?:[.,]\d+)?", v)
    if not nums:
        raise ValueError
    inches = float(nums[0].replace(",", "."))
    if len(nums) > 1:
        inches += float(nums[1].replace(",", ".")) / 12.0
    return None, round(inches, 4), _r(lmr.baro_Fr_in2mb(inches))


def c_ParisLine(v, var, ctx, log, opts):
    lines = clean_number(v, ctx, log)
    return None, lines, _r(lmr.baro_Fr_in2mb(lines / 12.0))


# trace = 0.005 in (0.13 mm), Table 8 of Slonosky et al. (2026); metadata trace_mm changes it
TRACE_MM = 0.13
TRACE_TERMS = ["trace", "slight", "meas", "inapp", "in."]
NIL_TERMS = {"nil", "no rain", "no snow"}
LITTLE_TERMS = {"a little", "little", "some", "a few", "un peu", "peu", "quelque"}


def _precip(v, var, ctx, log, opts, to_mm):
    """Precipitation / snow; returns mm (later scaled to cm for snow)."""
    vl = v.lower().strip()
    if vl in NIL_TERMS:
        return "no entry", 0.0, 0.0
    if any(x in vl for x in TRACE_TERMS) or vl in ("in", "t", "tr"):
        mm = float(opts.get("trace_mm", TRACE_MM))
        return "trace", round(mm / to_mm, 4), _r(mm)
    if vl in LITTLE_TERMS:
        mm = float(opts.get("trace_mm", TRACE_MM))
        log.write(ctx, "QUALITATIVE", f"'{v}': treated as trace")
        return "trace; qualitative", v, _r(mm)
    if not re.search(r"\d", vl):
        # words only ("Rain", "snow"): occurrence noted, amount unknown
        log.write(ctx, "QUALITATIVE", f"'{v}': amount not measured")
        return "qualitative", v, None
    s = re.sub(r"^[RrSs]\s+", "", v)                # leading R (rain) / S (snow) markers
    flag = None
    if "|" in s or " / " in s or "+" in s:
        parts = [p for p in re.split(r"\||\s/\s|\+", s) if p.strip()]
        res = sum(clean_number(p, ctx, log) for p in parts)
        flag = "two values added"
        log.write(ctx, "SUM", f"'{v}' -> {res:g}")
    else:
        res = clean_number(s, ctx, log)
    return flag, res, _r(res * to_mm)


def c_in(v, var, ctx, log, opts):
    return _precip(v, var, ctx, log, opts, 25.4)


def c_mm(v, var, ctx, log, opts):
    return _precip(v, var, ctx, log, opts, 1.0)


def c_cm(v, var, ctx, log, opts):
    return _precip(v, var, ctx, log, opts, 10.0)


def c_mi(v, var, ctx, log, opts):
    d = clean_number(v, ctx, log)
    return None, d, _r(d * 1609.344, 0)


def c_percent(v, var, ctx, log, opts):
    r = clean_number(v, ctx, log)
    if 0 < r <= 1:
        return "multiply by 100", r, _r(r * 100)
    return None, r, _r(r)


def _scale(v, ctx, log, top, name):
    from fractions import Fraction as Fr
    s = int(float(sum(Fr(x) for x in v.replace(",", " ").split())))
    if s < 0 or s > top:
        log.write(ctx, "RANGE", f"{name} {s}: out of range")
        return s, False
    return s, True


def c_Sm(v, var, ctx, log, opts):
    if not re.search(r"\d", v):
        return c_words(v, var, ctx, log, opts)       # descriptive term in a numeric column
    s, ok = _scale(v, ctx, log, 10, "Smithsonian force")
    if not ok:
        return "out of range", s, None
    return None, s, _r(im.convertSmithsonian(s), 1)       # Table 4: nominal mph -> m/s


def c_Bf(v, var, ctx, log, opts):
    if not re.search(r"\d", v):
        return c_words(v, var, ctx, log, opts)
    b, ok = _scale(v, ctx, log, 12, "Beaufort force")
    if not ok:
        return "out of range", b, None
    return None, b, _r(im.convertBeaufort(b), 1)


def c_words(v, var, ctx, log, opts):
    """Descriptive wind force, looked up in wind_words tables."""
    words = opts["wind_words"]
    key = " ".join(v.lower().split())
    if key in ("calm", "0", "c"):
        return None, "calm", 0.0
    bf = words.get(key)
    if bf is None:                                     # longest table term inside the text
        for term in sorted(words, key=len, reverse=True):
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", key):
                bf = words[term]
                log.write(ctx, "KEYWORD", f"Wind force '{v}' matched '{term}'")
                break
    if bf is None or str(bf).strip() == "":
        log.write(ctx, "UNMAPPED", f"Wind force term '{v}' not in wind_words tables")
        return "unmapped", v, None
    if str(bf).lower() == "qualitative":
        log.write(ctx, "QUALITATIVE", f"Wind force term '{v}' kept as qualitative (no scale equivalent)")
        return "qualitative", v, None
    if str(bf).lower() == "unknown":
        log.write(ctx, "UNKNOWN", f"Wind force term '{v}' coded as unknown")
        return "unknown", v, None
    return None, v, _r(im.convertBeaufort(int(float(bf))), 1)


def c_mph(v, var, ctx, log, opts):
    s = clean_number(v, ctx, log)
    return None, s, _r(s * 0.44704)


def c_kt(v, var, ctx, log, opts):
    s = clean_number(v, ctx, log)
    return None, s, _r(lmr.wind_kts2mps(s))


def c_ms(v, var, ctx, log, opts):
    s = clean_number(v, ctx, log)
    return None, s, _r(s)


def c_kmh(v, var, ctx, log, opts):
    s = clean_number(v, ctx, log)
    return None, s, _r(s / 3.6)


def c_lbsft(v, var, ctx, log, opts):
    """Wind pressure lbs/ft2 ('3 15' = 3 lb 15 oz) -> m/s (Equation 1)."""
    parts = v.split()
    w = float(parts[0]) + float(parts[1]) / 16.0 if len(parts) == 2 else clean_number(v, ctx, log)
    if w < 0:
        return "out of range", w, None
    return None, w, _r(sqrt(w / 0.00256) * 0.44704)


OBSCURED = ["fog", "smoke", "haze", "scud", "hidden", "mist"]


def c_tenths(v, var, ctx, log, opts):
    vl = v.lower()
    if any(x in vl for x in OBSCURED):
        return None, v, 9
    if "clear" in vl or vl == "zero":
        return None, 0, 0
    t = clean_number(v, ctx, log)
    if t < 0 or t > 10:
        log.write(ctx, "RANGE", f"Cloud amount {t:g} tenths: out of range")
        return "out of range", t, None
    return None, t, int(round(t * 0.8))      # whole oktas (= WMO table 0,1,2,2,3,4,5,6,6,7,8)


def c_okta(v, var, ctx, log, opts):
    vl = v.lower()
    if any(x in vl for x in OBSCURED):
        return None, v, 9
    t = clean_number(v, ctx, log)
    return None, t, _r(t)


def c_tenths_clear(v, var, ctx, log, opts):
    """'Clearness of sky' in tenths of CLEAR sky -> oktas of covered sky."""
    vl = v.lower()
    if any(x in vl for x in OBSCURED):
        return None, v, 9
    if "clear" in vl:
        return None, 10, 0
    t = clean_number(v, ctx, log)
    if t < 0 or t > 10:
        log.write(ctx, "RANGE", f"Clearness {t:g}: out of range")
        return "out of range", t, None
    return None, t, lmr.cloud_tenthsclear2oktas(int(round(t)))


def c_cloudvel(v, var, ctx, log, opts):
    s = v.split()[-1]
    if s.lower() in ("p", "perceptible"):
        return None, v, 1
    c = clean_number(s, ctx, log)
    if c < 0 or c > 10:
        log.write(ctx, "RANGE", f"Cloud velocity {c:g}: out of range")
        return "out of range", c, None
    return None, c, _r(c, 0)


ABBR_TO_DEG = {abbr.lower(): im.convert_directions[full]
               for full, abbr in im.abbr_directions.items()
               if full in im.convert_directions and im.convert_directions[full] != -999}
ABBR_TO_DEG.update({k.lower(): val for k, val in im.convert_directions.items() if val != -999})
ABBR_TO_DEG.update({"northeast": 45, "northwest": 315, "southeast": 135, "southwest": 225,
                    "nxe": 11.25, "exn": 78.75, "nwbyn": 326.25,
                    # French / German compass letters
                    "o": 270, "no": 315, "so": 225, "ono": 292.5, "oso": 247.5,
                    "nno": 337.5, "sso": 202.5})


# Table 5: "hidden" - fog or thick lower clouds hide the higher clouds, so their direction can't be seen
HIDDEN_WORDS = {"hidden", "obscured", "haze", "hazy", "fog", "foggy", "smoke", "mist"}
NO_CLOUD_WORDS = {"clear", "none", "no clouds", "cloudless"}


def c_dir(v, var, ctx, log, opts):
    raw = v.strip().lower()
    if raw in ("-999", "-999.0", "-999.9", "-9999"):
        return "missing", v, None                       # missing-value code in a direction column
    if raw in ("-888", "-888.0", "-888.8"):
        return "instrument error", v, None
    vl = raw.replace(".", "").replace(" by ", "by")
    if vl in HIDDEN_WORDS:
        return "hidden", v, None                        # clouds hidden: direction can't be seen
    if vl in NO_CLOUD_WORDS and var != "dd":
        return "no clouds", v, "Calm"                   # no clouds: Calm, flagged
    if vl in ("calm", "c", "0", "none", "not perceptible", "imp", "calme"):
        return None, v, "Calm"
    if vl.startswith("var"):
        return None, v, "Variable"
    try:
        d = float(vl)
        if 0 <= d <= 360:
            return None, v, _r(d % 360, 1)
    except ValueError:
        pass
    first = vl.split()[0] if vl.split() else vl
    for key in (vl, vl.replace(" ", "-"), first):
        if key in ABBR_TO_DEG:
            return None, v, ABBR_TO_DEG[key]
    log.write(ctx, "UNMAPPED", f"Direction '{v}' not recognised")
    return "unmapped", v, None


def _cloudtype(v, var, ctx, log, opts, upper):
    if v.strip().lower() in NO_CLOUD_WORDS:
        return None, v, "Ch0" if upper else "Cl0"       # Table 5: None; Clear = 0
    if opts.get("keep_wind_cloud_type"):
        code = im.abbr_cloud.get(v.lower(), "-999")
    else:
        code = im.convertUpperCloud(v) if upper else im.convertLowerCloud(v)
    if code == "-999":
        log.write(ctx, "UNMAPPED", f"Cloud type '{v}' not recognised")
        return "unmapped", v, None
    return None, v, code


def c_lct(v, var, ctx, log, opts):
    return _cloudtype(v, var, ctx, log, opts, False)


def c_uct(v, var, ctx, log, opts):
    return _cloudtype(v, var, ctx, log, opts, True)


def c_mno(v, var, ctx, log, opts):
    """Weather description -> synoptic codes, using the weather_terms tables in order."""
    text = " ".join(v.lower().split())
    codes = []
    for term, code, match in opts["weather_terms"]:
        if match == "exact":
            if text == term:
                codes = [code]
                break
            continue
        pat = (r"(?<!\w)" + re.escape(term) + r"(?!\w)") if match == "word" \
            else (r"(?<!\w)" + re.escape(term) + r"\w*")
        if re.search(pat, text):
            text = re.sub(pat, " ", text)
            for c in code.split():
                if c not in codes:
                    codes.append(c)
    if codes == ["unknown"]:
        log.write(ctx, "UNKNOWN", f"Weather term '{v}' coded as unknown")
        return "unknown", v, None
    codes = [c for c in codes if c.lower() != "unknown"]
    if not codes:
        log.write(ctx, "UNMAPPED", f"Weather '{v}' has no synoptic equivalent")
        return "unmapped", v, None
    return None, v, " ".join(codes)


def c_text(v, var, ctx, log, opts):
    return None, v, v


CONVERTERS = {
    "F": (c_F, "C"), "C": (c_C, "C"), "R": (c_R, "C"), "De": (c_De, "C"), "De_frz": (c_De_frz, "C"), "Fdiff": (c_Fdiff, "C"), "Cdiff": (c_Cdiff, "C"),
    "inHg": (c_inHg, "hPa"), "mmHg": (c_mmHg, "hPa"), "hPa": (c_hPa, "hPa"),
    "ParisIn": (c_ParisIn, "hPa"), "ParisLine": (c_ParisLine, "hPa"),
    "in": (c_in, "mm"), "mm": (c_mm, "mm"), "cm": (c_cm, "mm"), "mi": (c_mi, "m"),
    "%": (c_percent, "%"),
    "Sm": (c_Sm, "m/s"), "Bf": (c_Bf, "m/s"), "words": (c_words, "m/s"), "mph": (c_mph, "m/s"),
    "kt": (c_kt, "m/s"), "m/s": (c_ms, "m/s"), "km/h": (c_kmh, "m/s"), "lbsft": (c_lbsft, "m/s"),
    "tenths": (c_tenths, "okta"), "okta": (c_okta, "okta"), "tenths_clear": (c_tenths_clear, "okta"),
    "cloudvel": (c_cloudvel, "0-10"), "dir": (c_dir, "deg"),
    "lct": (c_lct, "cloud atlas code"), "uct": (c_uct, "cloud atlas code"),
    "mno": (c_mno, "synoptic code"), "text": (c_text, "text"), "oz": (c_text, "scale"),
}


def iso_unit(unit, var):
    u = CONVERTERS[unit][1] if unit in CONVERTERS else unit
    return "cm" if (u == "mm" and var in CM_VARS) else u


def process_value(raw, var, unit, ctx, log, opts):
    """Screen, clean and convert one value -> (flag, clean_value, iso_value, iso_unit)."""
    iu = iso_unit(unit, var)
    status, v, flag = pre_screen(raw, var, unit, ctx, log)
    if status == "stop":
        if flag == "below scale" and iu == "C" and opts.get("below_scale_c") not in (None, ""):
            return "at or below; below scale", None, _r(float(opts["below_scale_c"])), iu
        return flag, None, None, iu
    if unit not in CONVERTERS:
        log.write(ctx, "UNIT", f"No converter for unit '{unit}'")
        return "unknown unit", v, None, iu
    try:
        cflag, clean, iso = CONVERTERS[unit][0](v, var, ctx, log, opts)
    except (ValueError, ZeroDivisionError, IndexError):
        log.write(ctx, "INVALID", f"Invalid data '{raw}'")
        return "invalid", None, None, iu
    if iu == "cm" and isinstance(iso, (int, float)):
        iso = _r(iso / 10.0)
    flags = [f for f in (flag, cflag) if f]
    return ("; ".join(flags) if flags else None), clean, iso, iu
