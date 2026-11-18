"""Synthetic-data tests for red_day_nq_study.py: no real bars are read."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import red_day_nq_study as rd  # noqa: E402

ET = "America/New_York"


def bar(ts_et: str, o: float, c: float | None = None, inst: int = 1, v: float = 10.0) -> dict:
    c = o if c is None else c
    return dict(ts_event=pd.Timestamp(ts_et, tz=ET).tz_convert("UTC"), open=o, high=max(o, c), low=min(o, c),
                close=c, volume=v, instrument_id=inst)


def session(td: str, open18: float, rth_open: float, rth_close: float, pre: float, close1659: float,
            inst: int = 1, early_close: bool = False) -> list[dict]:
    """Sparse bars for the Globex session whose trade date is td (opens 18:00 ET the evening before)."""
    d = pd.Timestamp(td)
    eve = (d - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    out = [bar(f"{eve} 18:00", open18, inst=inst), bar(f"{eve} 23:00", open18, inst=inst),
           bar(f"{td} 09:30", rth_open, inst=inst), bar(f"{td} 12:00", rth_open, inst=inst)]
    if early_close:
        return out
    return out + [bar(f"{td} 15:59", rth_close, rth_close, inst=inst), bar(f"{td} 16:58", pre, pre, inst=inst),
                  bar(f"{td} 16:59", pre, close1659, inst=inst)]


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows).set_index("ts_event").sort_index()


class SessionTable(unittest.TestCase):
    def test_sunday_evening_belongs_to_monday(self):
        df = frame([bar("2021-03-07 18:00", 100), bar("2021-03-08 09:30", 101)])   # Sunday 18:00, Monday 09:30
        tab = rd.session_table(df)
        self.assertEqual(list(tab.index.get_level_values("td")), [pd.Timestamp("2021-03-08")])
        self.assertEqual(tab["g_open"].iat[0], 100)
        self.assertEqual(tab["rth_open"].iat[0], 101)

    def test_dst_switch_keeps_et_times(self):
        # 2021-03-14 DST starts: 18:00 ET Sunday is 22:00 UTC, the Friday before was 23:00 UTC.
        df = frame(session("2021-03-12", 100, 101, 102, 103, 104) + session("2021-03-15", 200, 201, 202, 203, 204))
        tab = rd.session_table(df).droplevel("inst")
        self.assertEqual(tab.loc["2021-03-15", "g_open"], 200)
        self.assertEqual(tab.loc["2021-03-15", "close1700"], 204)
        self.assertEqual(tab.loc["2021-03-15", "pre_close"], 203)

    def test_globex_flag_ignores_the_entry_minute(self):
        """The 16:59 bar's close is the fill, not the signal: changing it must not flip the red flag."""
        base = session("2021-06-01", 100, 100, 100, 101, 101)
        a = session("2021-06-02", 100, 100, 100, 99, 150)    # red at 16:59:00, rallies into the fill
        b = session("2021-06-02", 100, 100, 100, 99, 50)
        nxt = session("2021-06-03", 120, 120, 120, 120, 120)
        for rows in (a, b):
            days = rd.day_table(rd.session_table(frame(base + rows + nxt)), date(2021, 6, 2), date(2021, 6, 2))
            self.assertEqual(days["red_globex"].iat[0], 1.0)


class Trades(unittest.TestCase):
    def setUp(self):
        self.rows = (session("2021-06-01", 100, 100, 100, 100, 100)
                     + session("2021-06-02", 100, 101, 95, 96, 97)       # red on all three definitions
                     + session("2021-06-03", 98, 99, 110, 111, 112)      # green on all three
                     + session("2021-06-04", 113, 114, 120, 121, 122))

    def days(self, rows=None):
        return rd.day_table(rd.session_table(frame(rows or self.rows)), date(2021, 6, 2), date(2021, 6, 4))

    def test_flags(self):
        d = self.days().set_index("td")
        self.assertEqual(d.loc["2021-06-02", ["red_globex", "red_rth", "red_settle"]].tolist(), [1.0, 1.0, 1.0])
        self.assertEqual(d.loc["2021-06-03", ["red_globex", "red_rth", "red_settle"]].tolist(), [0.0, 0.0, 0.0])
        self.assertTrue(np.isnan(d.loc["2021-06-04", "x_session_close"]))   # no next session: no exit

    def test_prices_and_costs(self):
        days = self.days()
        sub, net, red = rd.cell_returns(days, "rth/close1700/session_close", "NQ")
        self.assertEqual(len(net), 2)   # 06-04 has no exit
        cost = 2 * 0.25 + 4.50 / 20
        self.assertAlmostEqual(net[red][0], (112 - 97) - cost)
        _, net, red = rd.cell_returns(days, "rth/open1800/rth_open", "MNQ")
        self.assertAlmostEqual(net[red][0], (99 - 98) - (2 * 0.25 + 1.0 / 2))
        _, gross, red = rd.cell_returns(days, "rth/close1700/rth_close", friction=0.0)
        self.assertAlmostEqual(gross[red][0], 110 - 97)

    def test_roll_inside_hold_is_skipped(self):
        rows = (session("2021-06-01", 100, 100, 100, 100, 100) + session("2021-06-02", 100, 101, 95, 96, 97)
                + session("2021-06-03", 98, 99, 110, 111, 112, inst=2))
        d = self.days(rows).set_index("td")
        self.assertTrue(np.isnan(d.loc["2021-06-02", "x_session_close"]))
        self.assertTrue(np.isnan(d.loc["2021-06-03", "red_settle"]))   # prior settle was on the old contract

    def test_outrights_trade_the_front_and_exit_on_it(self):
        back = [dict(r, volume=1.0, close=r["close"] + 50, open=r["open"] + 50, instrument_id=9) for r in self.rows]
        d = self.days(self.rows + back).set_index("td")
        self.assertEqual(d.loc["2021-06-02", "inst"], 1)
        self.assertEqual(d.loc["2021-06-02", "x_session_close"], 112)

    def test_holiday_session_is_held_through(self):
        rows = (session("2021-06-01", 100, 100, 100, 100, 100) + session("2021-06-02", 100, 101, 95, 96, 97)
                + session("2021-06-03", 98, 99, 0, 0, 0, early_close=True)
                + session("2021-06-04", 113, 114, 120, 121, 122))
        d = self.days(rows).set_index("td")
        self.assertEqual(d.loc["2021-06-02", "x_rth_open"], 99)       # 09:30 exists on the short day
        self.assertEqual(d.loc["2021-06-02", "x_session_close"], 122)  # no 16:59 there: next session
        self.assertEqual(d.loc["2021-06-02", "xd_session_close"], pd.Timestamp("2021-06-04"))

    def test_data_hole_is_not_a_trade(self):
        rows = (session("2021-06-01", 100, 100, 100, 100, 100) + session("2021-06-02", 100, 101, 95, 96, 97)
                + session("2021-06-14", 98, 99, 110, 111, 112))
        d = rd.day_table(rd.session_table(frame(rows)), date(2021, 6, 2), date(2021, 6, 2))
        self.assertTrue(np.isnan(d["x_session_close"].iat[0]))
        self.assertTrue(np.isnan(d["px_open1800"].iat[0]))


class Stats(unittest.TestCase):
    def test_perm_p(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 2000)
        mask = rng.random(2000) < 0.5
        self.assertGreater(rd.perm_p(x, mask, 999), 0.01)
        y = x + 0.5 * mask
        self.assertLess(rd.perm_p(y, mask, 999), 0.01)

    def test_drift_alone_is_not_an_edge(self):
        """Random walk with upward drift: red days make money like every day, and the edge is ~0."""
        rng = np.random.default_rng(7)
        tds = pd.bdate_range("2015-01-05", periods=400)
        p, rows = 10000.0, []
        for td in tds:
            o18 = p
            ro = o18 + rng.normal(2, 20)
            rc = ro + rng.normal(2, 40)
            pre = rc + rng.normal(0, 5)
            c = pre + rng.normal(0, 1)
            rows += session(td.strftime("%Y-%m-%d"), o18, ro, rc, pre, c)
            p = c + rng.normal(1, 10)
        days = rd.day_table(rd.session_table(frame(rows)), tds[1].date(), tds[-1].date())
        res = rd.score(days, "settle/close1700/session_close", reps=999)
        self.assertGreater(res["all_mean"], 0)
        self.assertGreater(res["p"], 0.01)
        self.assertEqual(sum(v["n"] for v in res["by_year"].values()), res["n_red"])

    def test_max_drawdown(self):
        self.assertEqual(rd.max_drawdown(np.array([1.0, -3.0, 1.0, -2.0, 5.0])), 4.0)
        self.assertEqual(rd.max_drawdown(np.array([-1.0])), 1.0)


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(rd, "PREREG", self.tmp / "prereg.json"),
                        mock.patch.object(rd, "LOOKS", self.tmp / "looks.log"),
                        mock.patch.object(rd, "OUT", self.tmp / "out"),
                        mock.patch.object(rd, "DIRS", (self.tmp / "bars",))]
        for p in self.patches:
            p.start()
        (self.tmp / "bars").mkdir()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def write_bars(self, rows):
        frame(rows).to_parquet(self.tmp / "bars" / "a.parquet")

    def test_load_refuses_the_sealed_block(self):
        with self.assertRaises(ValueError):
            rd.load((date(2026, 8, 1), date(2026, 8, 24)))

    def test_load_stops_at_17_on_the_last_day(self):
        self.write_bars(session("2021-12-30", 1, 1, 1, 1, 1) + session("2021-12-31", 2, 2, 2, 2, 2)
                        + session("2022-01-03", 3, 3, 3, 3, 3))
        df = rd.load((date(2021, 12, 30), date(2021, 12, 31)))
        self.assertLess(df.index.max(), pd.Timestamp("2021-12-31 17:00", tz=ET))
        self.assertEqual(df["close"].max(), 2)

    def test_confirm_needs_a_freeze_then_refuses_a_second_look(self):
        self.assertEqual(rd.main(["--confirm"]), 1)                          # nothing frozen
        self.assertEqual(rd.main(["--freeze", "globex/close1700/session_close"]), 0)
        self.assertEqual(rd.main(["--freeze", "rth/close1700/rth_open"]), 1)  # no re-freeze
        self.write_bars(session("2022-01-04", 1, 1, 1, 1, 1))
        self.assertEqual(rd.main(["--confirm"]), 1)                          # coverage short: look not spent
        self.assertFalse(rd.LOOKS.exists())
        rd.LOOKS.write_text("cell=x\n")
        self.assertEqual(rd.main(["--confirm"]), 1)                          # already looked

    def test_changed_script_refuses(self):
        rd.PREREG.write_text(json.dumps(dict(cell="globex/close1700/session_close", contract="NQ",
                                             script_sha="0" * 16)))
        self.assertEqual(rd.main(["--check"]), 1)

    def test_cells(self):
        self.assertEqual(len(rd.CELLS), 18)


if __name__ == "__main__":
    unittest.main()
