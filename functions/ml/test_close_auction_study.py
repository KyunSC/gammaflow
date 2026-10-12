"""Offline checks for close_auction_study on synthetic 1-min bars and session tables."""
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

import close_auction_study as ca


def weekdays(n, start=date(2024, 3, 4), skip=()):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5 and d not in skip:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_minutes(days, seed=0, lo=ca.OPEN, hi=ca.POST_LATE, quiet_after=None):
    """1-min bars stamped at their start (UTC) from `lo` to `hi` ET, random-walk closes.
    `quiet_after`: {day: minute} -> a half day closing at that minute."""
    rng = np.random.default_rng(seed)
    rows, idx, px = [], [], 100.0
    for d in days:
        t0 = pd.Timestamp(f"{d} 00:00", tz=ca.ET)
        for mnt in range(lo, hi):
            o = px
            px = o * np.exp(5e-4 * rng.standard_normal())
            vol = 1000.0
            if quiet_after and d in quiet_after and mnt >= quiet_after[d]:
                # a half day: the bar at the early close holds the post-close prints, then quiet
                vol = 1e6 if mnt == quiet_after[d] else 1.0
            rows.append((o, max(o, px), min(o, px), px, vol))
            idx.append((t0 + pd.Timedelta(minutes=mnt)).tz_convert("UTC"))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=pd.DatetimeIndex(idx, name="ts_event"))


def daily_from(m, days, dividends=None):
    """Official open = the 09:30 bar's open; official close = the 15:59 bar's close + 1 bp."""
    et = m.index.tz_convert(ca.ET)
    mins = et.hour * 60 + et.minute
    rows = {}
    for d in days:
        sel = et.date == d
        rows[d] = dict(open=float(m.loc[sel & (mins == ca.OPEN), "open"].iloc[0]),
                       close=float(m.loc[sel & (mins == ca.CLOSE - 1), "close"].iloc[0]) * 1.0001,
                       dividends=(dividends or {}).get(d, 0.0))
    return pd.DataFrame.from_dict(rows, orient="index")


def bar(m, d, hhmm, col="close"):
    t = pd.Timestamp(f"{d} {hhmm}", tz=ca.ET).tz_convert("UTC")
    return float(m.loc[t, col])


class SessionTable(unittest.TestCase):
    def setUp(self):
        # 2024-03-08 is EST, 2024-03-11 EDT: the ET clock must be used on both sides of the switch.
        self.days = weekdays(6, start=date(2024, 3, 6))
        self.m = make_minutes(self.days)
        self.daily = daily_from(self.m, self.days)
        self.tab = ca.session_table(self.m, self.daily)

    def test_prices_are_et_bar_closes_across_dst(self):
        for d in (date(2024, 3, 8), date(2024, 3, 11)):
            self.assertAlmostEqual(self.tab.loc[d, "p_1555"], bar(self.m, d, "15:54"))
            self.assertAlmostEqual(self.tab.loc[d, "p_1550"], bar(self.m, d, "15:49"))
            self.assertAlmostEqual(self.tab.loc[d, "p_1605"], bar(self.m, d, "16:04"))

    def test_vwap_window(self):
        d = self.days[2]
        et = self.m.index.tz_convert(ca.ET)
        mins = et.hour * 60 + et.minute
        w = self.m[(et.date == d) & (mins >= ca.VWAP_PRE[0]) & (mins < ca.VWAP_PRE[1])]
        self.assertEqual(len(w), 15)
        tp = (w["high"] + w["low"] + w["close"]) / 3
        self.assertAlmostEqual(self.tab.loc[d, "vwap_pre"], float((tp * w["volume"]).sum() / w["volume"].sum()))

    def test_next_session_skips_weekend(self):
        self.assertEqual(self.tab.loc[date(2024, 3, 8), "next_session"], date(2024, 3, 11))
        self.assertAlmostEqual(self.tab.loc[date(2024, 3, 8), "open_next"], self.daily.loc[date(2024, 3, 11), "open"])
        self.assertTrue(pd.isna(self.tab.loc[self.days[-1], "open_next"]))

    def test_moc_signals_ignore_bars_from_1555(self):
        m2 = self.m.copy()
        et = m2.index.tz_convert(ca.ET)
        late = (et.hour * 60 + et.minute) >= ca.DECISION
        m2.loc[late, ["open", "high", "low", "close"]] *= 1.05
        a = ca.add_signals(ca.session_table(self.m, self.daily))
        b = ca.add_signals(ca.session_table(m2, self.daily))
        pd.testing.assert_series_equal(a["dev_pre"], b["dev_pre"])
        pd.testing.assert_series_equal(a["r_imb"], b["r_imb"])
        self.assertFalse(np.allclose(a["dev_close"], b["dev_close"]))

    def test_missing_post_bar_keeps_session_without_post_return(self):
        d = self.days[1]
        gone = [pd.Timestamp(f"{d} 16:{mm:02d}", tz=ca.ET).tz_convert("UTC") for mm in range(0, 5)]
        t = ca.add_signals(ca.session_table(self.m.drop(index=gone), self.daily))
        self.assertIn(d, t.index)
        self.assertTrue(np.isnan(t.loc[d, "on_post"]))
        self.assertTrue(np.isfinite(t.loc[d, "on_close"]))


class Holidays(unittest.TestCase):
    def test_holiday_dividend_and_half_day(self):
        holiday, half, exdiv = date(2024, 3, 13), date(2024, 3, 15), date(2024, 3, 19)
        days = weekdays(8, start=date(2024, 3, 11), skip={holiday})
        m = make_minutes(days, quiet_after={half: ca.NOON1})
        daily = daily_from(m, days, dividends={exdiv: 0.5})
        tab = ca.session_table(m, daily)
        self.assertEqual(tab.loc[date(2024, 3, 12), "next_session"], date(2024, 3, 14))
        self.assertTrue(tab.loc[half, "early_close"])
        self.assertFalse(tab.loc[date(2024, 3, 14), "early_close"])
        t = ca.add_signals(tab)
        self.assertNotIn(half, t.index)
        prev = date(2024, 3, 18)
        expect = np.log((daily.loc[exdiv, "open"] + 0.5) / daily.loc[prev, "close"])
        self.assertAlmostEqual(t.loc[prev, "on_close"], expect)


class Rules(unittest.TestCase):
    def test_sigma_excludes_today_and_future(self):
        rng = np.random.default_rng(1)
        t = pd.DataFrame({"s": rng.standard_normal(60)}, index=weekdays(60))
        d = ca.cell_direction(t, "s", 1.0)
        self.assertTrue((d.iloc[:ca.SIGMA_WIN] == 0).all())
        t2 = t.copy()
        t2.iloc[-1, 0] = 50.0
        d2 = ca.cell_direction(t2, "s", 1.0)
        pd.testing.assert_series_equal(d.iloc[:-1], d2.iloc[:-1])
        self.assertEqual(d2.iloc[-1], -1.0)  # fade a big positive signal

    def test_calendar_flags(self):
        f = ca.calendar_flags(weekdays(35, start=date(2024, 3, 1)))
        self.assertTrue(f.loc[date(2024, 3, 15), "quad_witch"])
        self.assertTrue(f.loc[date(2024, 3, 29), "quarter_end"])
        self.assertFalse(f.loc[date(2024, 3, 28), "month_end"])
        self.assertFalse(f.loc[date(2024, 4, 12), "opex"])

    def test_research_sessions_drop_gap(self):
        days = weekdays(40, start=date(2026, 7, 27))
        r = ca.research_sessions(days)
        self.assertTrue(all(d < ca.VERIFY_START.date() for d in r))
        pre = [d for d in days if d < ca.VERIFY_START.date()]
        self.assertEqual(len(r), len(pre) - ca.GAP_SESSIONS)

    def test_gex_join_uses_full_time_of_day(self):
        d1, d2 = date(2024, 3, 4), date(2024, 3, 5)
        at = lambda d, hms: pd.Timestamp(f"{d} {hms}", tz=ca.ET).tz_convert("UTC")
        snaps = pd.DataFrame({
            "computed_at": [at(d1, "15:00:00"), at(d1, "15:55:40"), at(d2, "15:55:00")],
            "net_gex": [-1.0, 1.0, 1.0], "abs_gex_total": [1.0, 1.0, 1.0]})
        t = ca.attach_gex(pd.DataFrame(index=[d1, d2]), snaps)
        # 15:55:40 is after the 15:55 decision but before the close; 15:55:00 exactly counts for both.
        self.assertEqual(t["long_gamma_moc"].tolist(), [False, True])
        self.assertEqual(t["long_gamma_post"].tolist(), [True, True])

    def test_trade_stats_edge_and_legs(self):
        r = np.array([0.001, -0.002, 0.003])
        s = ca.trade_stats(r, np.array([1.0, -1.0, 1.0]), mu=0.0005, cost_bp=1.0)
        self.assertAlmostEqual(s["net_bp"], (10 + 20 + 30) / 3 - 1)
        self.assertAlmostEqual(s["edge_bp"], ((10 - 5) + (20 + 5) + (30 - 5)) / 3, places=3)
        self.assertAlmostEqual(s["short_net_bp"], 19.0)

    def test_planted_reversal_passes_and_noise_does_not(self):
        rng = np.random.default_rng(2)
        n = 900
        idx = weekdays(n, start=date(2022, 1, 3))
        base = {c: rng.standard_normal(n) * 1e-3 for c in ("dev_pre", "r_imb", "dev_close", "r_close")}
        noise = rng.standard_normal(n) * 5e-4

        def frame(on_close):
            t = pd.DataFrame(base, index=idx)
            t["on_close"], t["on_post"] = on_close, on_close
            t["win_share_z"] = 0.0
            t["long_gamma_moc"] = t["long_gamma_post"] = True
            for f in ca.CALENDAR:
                t[f] = False
            return t

        planted = ca.evaluate_execution(frame(2e-4 - 0.8 * base["dev_pre"] + noise), "moc")
        self.assertEqual(planted["verdict"], "PASS")
        self.assertTrue(planted["selected"].startswith("moc:dev_pre"))
        null = ca.evaluate_execution(frame(2e-4 + noise), "moc")
        self.assertNotEqual(null["verdict"], "PASS")
        self.assertIn("beats_always_long", null["verdict"])


if __name__ == "__main__":
    unittest.main()
