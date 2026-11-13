import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import open_ema_trail_study as st
from open_ema_trail_study import TICK, Cell, Day, select, simulate


def day(bars, atr=10.0, ema=None):
    a = np.array(bars, float)
    n = len(a)
    end5 = np.zeros(n, bool)
    end5[4::5] = True
    end5[-1] = True
    e = np.full(n, 0.0) if ema is None else np.array(ema, float)
    return Day(date(2015, 1, 5), a[:, 0], a[:, 1], a[:, 2], a[:, 3], end5, e,
               {3: np.full(n, np.nan)}, {3: np.full(n, np.nan)}, 100.0, 99.0, atr)


class Simulate(unittest.TestCase):
    def test_trail_ratchets_and_stops(self):
        # entry 100.25; D = 0.25*10 = 2.5; rally to 110 then drop -> stop at 107.5 - 1 tick
        d = day([(100, 101, 99.5, 100.5), (100.5, 110, 100.5, 109.5), (109.5, 109.5, 105, 106)], atr=10)
        pnl, D, held = simulate(d, 1, Cell("trail_atr", 0.25))
        self.assertEqual(D, 2.5)
        self.assertAlmostEqual(pnl, 107.5 - TICK - 100.25)
        self.assertEqual(held, 3)

    def test_close_through_new_stop_same_bar(self):
        # bar makes the high then closes below the ratcheted stop -> exit on that bar
        d = day([(100, 110, 100, 106), (106, 106, 106, 106)], atr=10)
        pnl, _, held = simulate(d, 1, Cell("trail_atr", 0.25))
        self.assertAlmostEqual(pnl, 107.5 - TICK - 100.25)
        self.assertEqual(held, 1)

    def test_gap_through_stop_fills_at_open(self):
        d = day([(100, 100.5, 99.5, 100), (90, 91, 89, 90)], atr=10)
        pnl, _, _ = simulate(d, 1, Cell("trail_atr", 0.25))
        self.assertAlmostEqual(pnl, 90 - TICK - 100.25)

    def test_short_mirrors_long(self):
        d = day([(100, 100.5, 99.5, 100), (100, 100, 90, 91), (91, 95, 91, 94)], atr=10)
        pnl, D, _ = simulate(d, -1, Cell("trail_atr", 0.25))
        # short entry 99.75, best low 90 -> stop 92.5, bar 3 high 95 -> fill 92.75
        self.assertAlmostEqual(pnl, 99.75 - 92.75)

    def test_time_exit(self):
        d = day([(100, 100.5, 99.8, 100.2)] * 4, atr=10)
        pnl, _, held = simulate(d, 1, Cell("trail_atr", 0.40))
        self.assertAlmostEqual(pnl, 100.2 - TICK - 100.25)
        self.assertEqual(held, 4)

    def test_step_locks_whole_R(self):
        # D = 2.5; best 105.5 = entry + 2.1R -> stop at entry + 1R = 102.75
        d = day([(100, 105.5, 100, 105), (105, 105, 102, 103)], atr=10)
        pnl, _, _ = simulate(d, 1, Cell("step", 0.25))
        self.assertAlmostEqual(pnl, 102.75 - TICK - 100.25)

    def test_tighten_waits_for_1R(self):
        # below +1R the stop stays at entry - D
        d = day([(100, 102, 100, 101), (101, 101, 97, 97.5)], atr=10)
        pnl, D, _ = simulate(d, 1, Cell("tighten", 0.25))
        self.assertAlmostEqual(pnl, -D - TICK)

    def test_ema_exit_next_open(self):
        bars = [(100, 101, 99.9, 100.5)] * 4 + [(100.5, 100.6, 99.9, 99.95), (99, 99.5, 98.9, 99.2)]
        ema = [100.0] * 6
        d = day(bars, atr=10, ema=ema)
        pnl, _, held = simulate(d, 1, Cell("ema_exit", 0.40))
        self.assertAlmostEqual(pnl, 99 - TICK - 100.25)
        self.assertEqual(held, 6)

    def test_bracket_target_needs_tick_through(self):
        d = day([(100, 102.75, 100, 102), (102, 103.0, 102, 103)], atr=10)
        pnl, D, held = simulate(d, 1, Cell("bracket", 0.25, target=1, reference=True))
        self.assertEqual(held, 2)  # 102.75 is the target: touching it is not a fill
        self.assertAlmostEqual(pnl, D)


class Selection(unittest.TestCase):
    def test_needs_both_symbols_positive(self):
        t = {"a/1": {"NQ": {"mean_net_R": 0.2}, "ES": {"mean_net_R": -0.01}, "avg_mean_R": 0.095},
             "b/1": {"NQ": {"mean_net_R": 0.05}, "ES": {"mean_net_R": 0.01}, "avg_mean_R": 0.03}}
        chosen, fam = select(t)
        self.assertEqual(chosen, "b/1")
        self.assertEqual(fam, {"a": "a/1", "b": "b/1"})


def rth_session(d: date, base: float, iid: int) -> pd.DataFrame:
    """390 1m RTH bars, flat at base with one +1 / -1 wick, so the day's range is 2 points."""
    idx = pd.date_range(pd.Timestamp(f"{d} 09:30", tz=st.ET), periods=390, freq="min").tz_convert("UTC")
    o = np.full(390, base)
    h, lo = o.copy(), o.copy()
    h[100], lo[200] = base + 1, base - 1
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": o, "volume": 1, "instrument_id": iid},
                        index=pd.DatetimeIndex(idx, name="ts_event"))


class Rolls(unittest.TestCase):
    def test_segments_restart_on_flip_back(self):
        seg = st.contract_segments(pd.Series([5, 5, 7, 7, 5, 5]))
        self.assertEqual(seg.tolist(), [1, 1, 2, 2, 3, 3])

    def test_roll_day_skipped_and_atr_ignores_gap(self):
        days = pd.bdate_range("2017-01-03", periods=19).date
        bars = pd.concat([rth_session(d, 5000.0 if i < 16 else 5100.0, 1 if i < 16 else 2)
                          for i, d in enumerate(days)])
        out = st.build_days(bars, days[0], days[-1])
        traded = [d.d for d in out]
        # ATR needs 14 prior sessions (days 15, 16); day 17 is the first of contract 2 (EMA has < 36 bars)
        self.assertEqual(traded, [days[14], days[15], days[17], days[18]])
        for d in out:
            self.assertAlmostEqual(d.atr, 2.0)  # a 100-point roll gap would show up here

    def test_load_fut_bars_segments_on_full_tape(self):
        days = pd.bdate_range("2017-01-03", periods=2).date
        a, b = rth_session(days[0], 5000.0, 11), rth_session(days[1], 5100.0, 22)
        night = a.iloc[[-1]].copy()
        night.index = pd.DatetimeIndex([pd.Timestamp(f"{days[0]} 20:00", tz=st.ET).tz_convert("UTC")],
                                       name="ts_event")
        night["instrument_id"] = 22  # the roll happens overnight
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "NQ"
            folder.mkdir()
            pd.concat([a, night, b]).to_parquet(folder / "2017-01-01_2017-02-01.parquet")
            with mock.patch.object(st, "FUT_BARS", Path(tmp)):
                bars = st.load_fut_bars("NQ", date(2017, 1, 1), date(2017, 2, 1))
                self.assertEqual(sorted(set(bars.instrument_id)), [1, 2])
                self.assertEqual(len(bars), 780)  # the 20:00 bar is not RTH
                with self.assertRaises(AssertionError):
                    st.load_fut_bars("NQ", date(2017, 1, 1), date(2022, 2, 1))  # past the confirm window
            pd.concat([a.assign(open=500.0, high=501.0, low=499.0, close=500.0)]).to_parquet(
                folder / "2017-01-01_2017-02-01.parquet")
            with mock.patch.object(st, "FUT_BARS", Path(tmp)), self.assertRaises(AssertionError):
                st.load_fut_bars("NQ", date(2017, 1, 1), date(2017, 2, 1))  # ETF-sized prices


class Coverage(unittest.TestCase):
    def test_missing_months(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("2016-01-01_2016-02-01.parquet", "2016-03-01_2016-04-01.parquet",
                         "2016-02-01_2016-03-01.dbn.zst", "notes.parquet"):
                (Path(tmp) / name).touch()
            miss = st.missing_months(Path(tmp), date(2016, 1, 4), date(2016, 5, 1))
            self.assertEqual(miss, ["2016-02", "2016-04"])  # a DBN without its Parquet does not count

    def test_lock_refuses_second_look(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "confirm.lock"
            self.assertTrue(st.confirm_lock_ok(lock))
            lock.write_text("looked")
            self.assertFalse(st.confirm_lock_ok(lock))


class Regime(unittest.TestCase):
    def test_latest_snapshot_at_or_before_entry(self):
        ts = pd.to_datetime(["2017-01-03 09:35", "2017-01-03 09:40", "2017-01-04 09:40",
                             "2017-01-05 09:35", "2017-01-06 09:30", "2017-01-06 09:35"]).tz_localize(st.ET)
        g = pd.DataFrame({"computed_at": ts.tz_convert("UTC"), "net_gex": [-1.0, 5.0, -2.0, 0.0, 3.0, -4.0]})
        r = st.regime_by_day(g, st.ENTRY_M)
        self.assertEqual(r, {date(2017, 1, 3): -1.0, date(2017, 1, 6): -4.0})  # 01-04 too late, 01-05 zero

    def test_split_regime(self):
        ds = [day([(100, 101, 99, 100)] * 3) for _ in range(3)]
        for d, dd in zip(ds, (date(2017, 1, 3), date(2017, 1, 4), date(2017, 1, 5))):
            d.d = dd
        out = st.split_regime(ds, {date(2017, 1, 3): -1.0, date(2017, 1, 4): 2.0})
        self.assertEqual([[d.d for d in out[k]] for k in ("neg", "pos", "none")],
                         [[date(2017, 1, 3)], [date(2017, 1, 4)], [date(2017, 1, 5)]])


class PerYear(unittest.TestCase):
    def test_pooled_uses_whatever_traded(self):
        def at(d, bars):
            x = day(bars)
            x.d = d
            return x
        up = [(100, 100, 100, 100), (100, 110, 100, 110)]  # signal is long (sig_close 100 > ema 99)
        nq = [at(date(2016, 6, 1), up), at(date(2017, 6, 1), up)]
        es = [at(date(2017, 6, 1), up)]
        yr = st.per_year({"NQ": nq, "ES": es}, Cell("hold", 0.25, reference=True))
        self.assertEqual(yr.loc[2016, "NQ_n"], 1)
        self.assertEqual(yr.loc[2016, "ES_n"], 0)
        self.assertAlmostEqual(yr.loc[2016, "pooled_R"], yr.loc[2016, "NQ_R"])
        self.assertAlmostEqual(yr.loc[2017, "pooled_R"], (yr.loc[2017, "NQ_R"] + yr.loc[2017, "ES_R"]) / 2)
        self.assertLess(yr.loc[2017, "NQ_rev_R"], 0)


if __name__ == "__main__":
    unittest.main()
