# -*- coding: utf-8 -*-
"""Tests: python -m unittest discover -s tests   (from the csv2sef folder)"""
import csv
import datetime as dt
import glob
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from csv2sef import pipeline, sef, tables                       # noqa: E402
from csv2sef import metadata as mdmod                            # noqa: E402
from csv2sef.convert import Context, Logger, process_value       # noqa: E402
from csv2sef.headers import parse_header                         # noqa: E402

EX = os.path.join(ROOT, "examples", "HalifaxCitadel")
OPTS = {"trace_mm": 0.2, "wind_words": tables.wind_words(), "weather_terms": tables.weather_terms()}


def conv(v, var, unit):
    return process_value(v, var, unit, Context(1, "x", dt.date(1860, 1, 1), var), Logger(), OPTS)


def sef_rows(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    return [ln.split("\t") for ln in lines[13:]]


class TestHeaders(unittest.TestCase):
    def test_forms(self):
        h = parse_header("ta 07:00 [F]")
        self.assertEqual((h.var, h.time, h.unit_token), ("ta", (7, 0), "F"))
        h = parse_header("p 2 pm (inHg)")
        self.assertEqual((h.var, h.time, h.unit_token), ("p", (14, 0), "inHg"))
        self.assertIsNone(parse_header("Tn").time)
        self.assertIsNone(parse_header("ww daily").time)
        self.assertEqual(parse_header("tdb\xa0sunrise").time, (6, 0))


class TestConversions(unittest.TestCase):
    def test_values(self):
        self.assertEqual(conv("58.2", "ta", "F")[2], 14.56)
        self.assertEqual(conv("10", "ta", "R")[2], 12.5)
        self.assertEqual(conv("29.71", "p", "inHg")[2], 1006.1)
        self.assertAlmostEqual(conv("28", "p", "ParisIn")[2], 1010.6, delta=0.5)
        self.assertAlmostEqual(conv("27 11", "p", "ParisIn")[2], 1008.0, delta=1.0)
        self.assertEqual(conv("0.5", "rr", "in")[2], 12.7)
        self.assertEqual(conv("inapp", "rr", "in")[0], "trace")
        self.assertEqual(conv("2", "sd", "in")[3], "cm")
        self.assertEqual(conv("fresh breeze", "w", "words")[2], 10)
        self.assertEqual(conv("bonne brise", "w", "words")[2], 10)
        self.assertEqual(conv("10", "w", "kt")[2], 5.14)
        self.assertEqual(conv("NNE", "dd", "dir")[2], 22.5)
        self.assertEqual(conv("rain & fog all day", "ww", "mno")[2], "RA FG")
        self.assertEqual(conv("neige et poudrerie", "ww", "mno")[2], "BLSN SN")
        self.assertEqual(conv("7", "n", "tenths")[2], 6)

    def test_historical_notation(self):
        self.assertEqual(conv("10+c", "ta", "R")[:3], ("caves notation", "10+c", 25.3))   # 12.8 + 12.5
        self.assertEqual(conv("2-co", "ta", "R")[2], 10.3)
        self.assertEqual(conv("=c", "ta", "R")[2], 12.8)
        self.assertEqual(conv("0=0", "ta", "R")[2], 12.8)
        self.assertEqual(conv("9-0", "ta", "De_frz")[2], 6.8)                          # 12.8 - 6
        self.assertEqual(conv("14+", "ta", "De_frz")[:3], ("caves notation (assumed)", "14+", 22.13))
        self.assertEqual(conv("16+0 R", "ta", "De_frz")[2], 32.8)                       # 12.8 + 20
        self.assertEqual(conv("9=0", "ta", "De_frz")[0], "caves notation, sign unclear")
        self.assertEqual(conv("0", "ta", "De_frz")[2], 0.0)
        self.assertEqual(conv("-5", "ta", "R")[2], -6.25)
        self.assertEqual(conv("10+co", "ta", "De_frz")[2], 19.47)                      # 12.8 + 6.67
        self.assertEqual(conv("30", "ta", "De_frz")[2], 20.0)
        self.assertEqual(conv("150", "ta", "De")[2], 0.0)
        self.assertEqual(conv("16R", "ta", "De_frz")[:3], ("unit R", 16.0, 20.0))
        self.assertEqual(conv("<=-34", "ta", "R")[0], "at or below")
        opts = dict(OPTS, below_scale_c="-34")
        ctx = Context(1, "x", dt.date(1748, 1, 1), "ta")
        self.assertEqual(process_value("<=-34", "ta", "De_frz", ctx, Logger(), opts)[2], -34.0)
        self.assertEqual(process_value("mercury in bulb", "ta", "De_frz", ctx, Logger(), opts)[2], -34.0)
        self.assertEqual(conv("mercury in bulb", "ta", "R")[0], "below scale")
        self.assertEqual(conv("a little", "rr", "in")[:3], ("trace; qualitative", "a little", 0.2))
        self.assertEqual(conv("Rain", "rr", "in")[0], "qualitative")
        self.assertEqual(conv("3", "fs", "in")[3], "cm")
        self.assertEqual(conv("point de vent", "w", "Sm")[2], 0.0)

    def test_direction_values(self):
        """Issue #7: missing codes, hidden and clear in direction columns."""
        self.assertEqual(conv("-999", "hd", "dir")[:3], ("missing", "-999", None))
        self.assertEqual(conv("-888", "dd", "dir")[0], "instrument error")
        self.assertEqual(conv("hidden", "hd", "dir")[:3], ("hidden", "hidden", None))
        self.assertEqual(conv("Haze", "hd", "dir")[0], "hidden")
        self.assertEqual(conv("clear", "cd", "dir")[:3], ("no clouds", "clear", "Calm"))
        self.assertEqual(conv("none", "hd", "dir")[:3], ("no clouds", "none", "Calm"))     # cloud columns
        self.assertEqual(conv("none", "cl", "lct")[2], "Cl0")
        self.assertEqual(conv("None", "ch", "uct")[2], "Ch0")
        self.assertEqual(conv("none", "dd", "dir")[0], "missing")                          # other columns
        self.assertEqual(conv("none", "ta", "F")[0], "missing")
        self.assertEqual(conv("none", "n", "tenths")[:3], (None, 0, 0))                  # cloud amount
        self.assertEqual(conv("None", "nh", "okta")[2], 0)
        self.assertEqual(conv("none", "skc", "tenths_clear")[0], "missing")              # clearness: not 0
        self.assertEqual(conv("clear", "dd", "dir")[0], "unmapped")          # wind: not a cloud
        self.assertEqual(conv("north-west", "hd", "dir")[2], 315)
        self.assertEqual(conv("calm", "dd", "dir")[2], "Calm")
    def test_direction_and_force(self):
        """Issue #6: direction and force in one cell ('south 1'), as in Red River 1844-45."""
        self.assertEqual(conv("south 1", "w", "Sm")[:2], (None, 1))
        self.assertEqual(conv("north-west 2", "w", "Sm")[1], 2)
        self.assertEqual(conv("South-East 1/2", "w", "Sm")[:2], ("fraction rounded down", 0))
        self.assertEqual(conv("2 1/2", "w", "Bf")[:2], ("fraction rounded down", 2))
        self.assertEqual(conv("redacted", "cv", "cloudvel")[0], "missing")
        self.assertEqual(conv("N 3", "w", "Bf")[1], 3)
        self.assertEqual(conv("south 1", "dd", "dir")[2], 180)            # the direction part, as before
        self.assertEqual(conv("fresh 1", "w", "Sm")[0], "invalid")        # not a direction: unchanged
        self.assertEqual(conv("3", "w", "Sm")[1], 3)

    def test_flags(self):
        self.assertEqual(conv("M", "ta", "F")[0], "missing")
        self.assertEqual(conv("37.?", "ta", "F")[:3], ("uncertain", 37.0, 2.78))
        self.assertEqual(conv("*", "ta", "F")[0], "instrument error")
        self.assertEqual(conv("[45]", "ta", "F")[1], 45.0)


class TestCommandLine(unittest.TestCase):
    def test_help_authors(self):
        """Issue #5: --help lists author names, not the letters of one string."""
        from csv2sef import cli
        authors = cli._authors()
        if not authors:
            self.skipTest("csv2sef not installed (pip install -e .)")
        self.assertIn("Vicky Slonosky", authors)
        self.assertIn("Hervé Hacot", authors)
        self.assertIn("Henry Balen", authors)
        self.assertNotIn("V, i, c", authors)
        self.assertNotIn("@", authors)


class TestHalifax(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        cls.report = pipeline.run(os.path.join(EX, "HalifaxCitadel_1863-1865.csv"),
                                  os.path.join(EX, "HalifaxCitadel_metadata.csv"), outdir=cls.out)
        cls.files = {os.path.basename(p).split("_")[-1][:-4] if "daily" not in p else "ww_daily": p
                     for p in glob.glob(os.path.join(cls.out, "SEF", "*.tsv"))}

    def test_all_valid(self):
        self.assertIn("all files valid", self.report)
        for p in self.files.values():
            self.assertEqual(sef.validate(p), [], p)

    def test_values(self):
        ta = sef_rows(self.files["ta"])
        self.assertEqual(ta[0][:7], ["1863", "11", "1", "11", "0", "0", "14.56"])  # 07:00 local = 11:00 UTC
        w = {tuple(r[:3]): r for r in sef_rows(self.files["w"])}
        self.assertEqual(w[("1865", "1", "1")][6], "12")                 # SB = strong breeze
        self.assertIn("qc=unknown", w[("1865", "2", "14")][7])             # s/o
        tn = sef_rows(self.files["Tn"])
        self.assertEqual(tn[0][:7], ["1863", "11", "2", "0", "0", "day", "2.22"])  # next midnight
        ww = {tuple(r[:3]): r for r in sef_rows(self.files["ww"])}
        self.assertEqual(ww[("1864", "3", "30")][6], "RA")                 # wet


class TestAliases(unittest.TestCase):
    def test_descriptive_headers(self):
        md = mdmod.Metadata()
        c, err = pipeline.resolve_column(0, "Thermometer Air AM", md)
        self.assertEqual((c.var, c.time, c.time_label), ("ta", None, "AM"))
        c, err = pipeline.resolve_column(0, "'Weather'", md)
        self.assertEqual((c.var, c.period, c.unit), ("ww", "day", "mno"))
        c, err = pipeline.resolve_column(0, "Wind_Direction 08:00 [16-point compass]", md)
        self.assertEqual((c.var, c.time, c.unit), ("dd", (8, 0), "dir"))
        md.columns["Thermometer Air AM"] = {"time": "07:30"}
        c, err = pipeline.resolve_column(0, "Thermometer Air AM", md)
        self.assertEqual((c.time, c.time_label, c.period), ((7, 30), None, "0"))


class TestOtherInputs(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.meta = os.path.join(self.d, "m.csv")
        with open(self.meta, "w", newline="") as f:
            csv.writer(f).writerows([["key", "value"], ["name", "Test Station"], ["lat", "46.8"],
                                     ["lon", "-71.2"], ["source", "TEST"], ["unit.ta", "R"]])

    def test_long_layout_and_offset(self):
        data = os.path.join(self.d, "long.csv")
        with open(data, "w", newline="") as f:
            csv.writer(f).writerows([["Date", "Time", "Variable", "Value", "Unit"],
                                     ["1790-01-01", "7am", "ta", "-10", "R"],
                                     ["1790-01-01", "2pm", "p", "28 1", "ParisIn"],
                                     ["1790-01-01", "", "ww", "neige", ""]])
        out = os.path.join(self.d, "out")
        rep = pipeline.run(data, self.meta, outdir=out)
        self.assertIn("all files valid", rep)
        md = mdmod.load(self.meta)
        self.assertEqual(md.site["utc_offset"], -5.0)                      # nearest time zone
        ta = sef_rows(glob.glob(os.path.join(out, "SEF", "*_ta.tsv"))[0])
        self.assertEqual(ta[0][3:7], ["12", "0", "0", "-12.5"])            # 07:00 local = 12:00 UTC

    def test_xlsx_and_metadata_unit(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Year", "Month", "Day", "ta 08:00"])
        ws.append([1800, 2, 1, 4.5])
        data = os.path.join(self.d, "x.xlsx")
        wb.save(data)
        rep = pipeline.run(data, self.meta, outdir=os.path.join(self.d, "o2"))
        self.assertIn("R            metadata", rep)
        self.assertIn("all files valid", rep)

    def test_database_export(self):
        data = os.path.join(self.d, "db.csv")
        with open(data, "w", newline="") as f:
            csv.writer(f).writerows([
                ["StationName", "ObservationDate", "value", "unit", "field_key", "fieldID"],
                ["X", "1750-01-01 08:00:00", "10+c", "R", "Air_Temperature", "9"],
                ["X", "1750-01-01 00:00:00", "NA", "free text", "Weather", "18"],
                ["X", "1750-01-01 00:00:00", "neige", "free text", "Weather", "18"],
                ["X", "1750-01-01 00:00:00", "-1.5", "C", "Minimum_Thermometer", "38"]])
        with open(self.meta, "a", newline="") as f:
            csv.writer(f).writerow(["midnight_means_daily", "yes"])
        out = os.path.join(self.d, "o3")
        rep = pipeline.run(data, self.meta, outdir=out)
        self.assertIn("all files valid", rep)
        self.assertNotIn("Date problems", rep)                          # empty duplicate dropped
        ww = sef_rows(glob.glob(os.path.join(out, "SEF", "*_ww.tsv"))[0])
        self.assertEqual(ww[0][3:7], ["0", "0", "day", "SN"])
        ta = sef_rows(glob.glob(os.path.join(out, "SEF", "*_ta.tsv"))[0])
        self.assertEqual(ta[0][3:7], ["13", "0", "0", "25.3"])

    def test_hour_in_field_name(self):
        """Issue #4: database field names that already end in the hour ('..._7am') plus a time
        column: fixed-hour readings keep their hour (not read as daily values)."""
        from csv2sef.headers import split_time_suffix
        self.assertEqual(split_time_suffix("attached_thermometer_7am"), ("attached_thermometer", (7, 0), "7am"))
        self.assertEqual(split_time_suffix("clearness_sky_sunrise")[1], (6, 0))
        for name in ("casual_phenomena_line_2", "barometer_observed_117", "attached_thermometer_9pm_1",
                     "open_air_thermometer_mean"):
            self.assertEqual(split_time_suffix(name), (name, None, None))           # bare numbers: not times
        data = os.path.join(self.d, "hour.csv")
        with open(data, "w", newline="") as f:
            csv.writer(f).writerows([
                ["StationName", "ObservationDate", "value", "unit", "field_key"],
                ["X", "1876-01-01 07:00:00", "-30", "F", "air_temperature_7am"],
                ["X", "1876-01-01 14:00:00", "-14.5", "F", "air_temperature_2pm"],
                ["X", "1876-01-01 20:00:00", "-8", "F", "air_temperature_9pm"]])     # name and time disagree
        out = os.path.join(self.d, "o5")
        rep = pipeline.run(data, self.meta, outdir=out)
        self.assertIn("all files valid", rep)
        self.assertNotIn("could not read time", rep)
        self.assertIn("says 9pm, time column says 20:00: time column used", rep)
        ta = sef_rows(glob.glob(os.path.join(out, "SEF", "*_ta.tsv"))[0])
        self.assertEqual([r[3:6] for r in ta], [["12", "0", "0"], ["19", "0", "0"], ["1", "0", "0"]])  # UTC-5

    def test_template(self):
        p = os.path.join(self.d, "t.csv")
        mdmod.write_template(p, [("ta", "F", "Air temperature")])
        with open(p) as f:
            text = f.read()
        self.assertIn("unit.ta,F", text)
        self.assertIn("unit_change,", text)                             # blank line to fill in
        self.assertNotIn("PTC", text)                                   # no pressure: no line

    def test_template_pressure_and_unknown(self):
        p = os.path.join(self.d, "t2.csv")
        mdmod.write_template(p, [("foo", None, "UNKNOWN variable")], pressure=["p"])
        with open(p) as f:
            text = f.read()
        self.assertIn("variable.p,header_meta=PTC=|PGC=", text)
        self.assertIn("alias.foo,", text)
        # blank alias / unit_change / PTC lines must not break a conversion
        data = os.path.join(self.d, "p.csv")
        with open(data, "w", newline="") as f:
            csv.writer(f).writerows([["year", "month", "day", "p 08:00 [mmHg]"], [1883, 9, 1, 761.3]])
        rows = list(csv.reader(open(p, encoding="utf-8")))
        fill = {"name": "T", "id": "T", "lat": "58.2", "lon": "-62.6", "utc_offset": "-4", "source": "TEST"}
        rows = [[r[0], fill.get(r[0], r[1])] + r[2:] if r else r for r in rows]
        with open(p, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        out = os.path.join(self.d, "o4")
        rep = pipeline.run(data, p, outdir=out)
        self.assertIn("PTC, PGC not filled in", rep)
        self.assertIn("all files valid", rep)
        with open(glob.glob(os.path.join(out, "SEF", "*_p.tsv"))[0], encoding="utf-8") as f:
            self.assertNotIn("PTC=", f.read())                         # blanks kept out of the header


if __name__ == "__main__":
    unittest.main()
