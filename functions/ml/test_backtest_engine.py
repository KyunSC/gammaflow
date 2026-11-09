"""Unit tests for the Python backtest engine. The first block mirrors frontend/lib/backtest/engine.test.mjs
case for case, so the two engines are held to the same written-down behaviour as well as to each other."""
from __future__ import annotations

import math
import unittest

import numpy as np
import pandas as pd

from backtest import Dataset, Strategy, run_backtest
from backtest.clock import trading_day
from backtest.metrics import dataset_periods_per_year, periods_per_year
from backtest.series import flat_by_flags, vwap
from backtest.stats import holdout_split

T0 = int(pd.Timestamp("2026-06-01T14:00Z").timestamp())
FRICTIONLESS = dict(slippage_bps=0, commission_per_trade=0)


def dataset(rows, time=None):
    """Bars from (open, high, low, close) rows, 5 minutes apart in one session."""
    o, h, l, c = map(list, zip(*rows))
    return Dataset(time=time if time is not None else [T0 + i * 300 for i in range(len(rows))],
                   open=o, high=h, low=l, close=c, volume=[1] * len(rows), interval="5m")


class Always(Strategy):
    id = "always"

    def __init__(self, direction, at=None):
        self.direction, self.at = direction, at

    def signal(self, i, s, ds, p, prev):
        return self.at(i) if self.at else self.direction


def decline(n=12):
    rows, p = [], 100.0
    for _ in range(n):
        rows.append((p, p, p * 0.99, p * 0.99))
        p *= 0.99
    return rows


class MirrorsJsEngineTests(unittest.TestCase):
    def test_stopped_long_does_not_reenter_while_signal_still_long(self):
        r = run_backtest(dataset(decline()), Always(1), costs=FRICTIONLESS, risk=dict(stop_pct=0.5))
        self.assertEqual([t.reason for t in r.trades], ["stop"])

    def test_reentry_resumes_once_signal_leaves_stopped_direction(self):
        r = run_backtest(dataset(decline(10)), Always(1, at=lambda i: 0 if i == 3 else 1), costs=FRICTIONLESS,
                         risk=dict(stop_pct=0.5))
        self.assertEqual([t.entry_idx for t in r.trades], [1, 5])
        self.assertTrue(all(t.reason == "stop" for t in r.trades))

    def test_time_exit_also_waits_for_fresh_signal(self):
        r = run_backtest(dataset([(100, 101, 99, 100)] * 10), Always(1), costs=FRICTIONLESS, risk=dict(max_bars=2))
        self.assertEqual([t.reason for t in r.trades], ["time"])

    def test_long_stop_gapped_through_fills_at_open(self):
        rows = [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (100, 100.5, 99.5, 100), (90, 91, 89, 90), (90, 91, 89, 90)]
        t = run_backtest(dataset(rows), Always(1), costs=FRICTIONLESS, risk=dict(stop_pct=2)).trades[0]
        self.assertEqual((t.reason, t.exit_idx, t.exit_price), ("stop", 3, 90))

    def test_short_stop_gapped_through_fills_at_open(self):
        rows = [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (110, 111, 109, 110), (110, 111, 109, 110)]
        t = run_backtest(dataset(rows), Always(-1), costs=FRICTIONLESS, risk=dict(stop_pct=2)).trades[0]
        self.assertEqual((t.reason, t.exit_price), ("stop", 110))

    def test_intrabar_stop_fills_at_stop(self):
        rows = [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (99.5, 99.8, 97, 97.5), (97.5, 98, 97, 97.5)]
        t = run_backtest(dataset(rows), Always(1), costs=FRICTIONLESS, risk=dict(stop_pct=2)).trades[0]
        self.assertEqual((t.reason, t.exit_price), ("stop", 98))

    def test_target_gapped_beyond_fills_at_open(self):
        rows = [(100, 100, 100, 100), (100, 100.5, 99.5, 100), (105, 106, 104, 105), (105, 106, 104, 105)]
        t = run_backtest(dataset(rows), Always(1), costs=FRICTIONLESS, risk=dict(target_pct=2)).trades[0]
        self.assertEqual((t.reason, t.exit_price), ("target", 105))

    def two_sessions(self):
        rows = [(100, 100, 100, 100), (100, 100, 97, 97), (97, 97, 96, 96),
                (96, 96.5, 95.5, 96), (96, 96.5, 95.5, 96), (96, 96.5, 95.5, 96)]
        time = [T0 + i * 300 + (86400 if i >= 3 else 0) for i in range(len(rows))]
        return dataset(rows, time)

    def test_stop_in_one_session_does_not_veto_next(self):
        r = run_backtest(self.two_sessions(), Always(1), costs=FRICTIONLESS,
                         risk=dict(stop_pct=2, flat_at_session_end=True))
        self.assertEqual([(t.entry_idx, t.reason) for t in r.trades], [(1, "stop"), (4, "session")])

    def test_stop_does_not_veto_next_session_when_holding_overnight(self):
        r = run_backtest(self.two_sessions(), Always(1), costs=FRICTIONLESS, risk=dict(stop_pct=2))
        self.assertEqual([(t.entry_idx, t.reason) for t in r.trades], [(1, "stop"), (3, "end-of-data")])

    def test_futures_annualised_on_their_own_bars_per_day(self):
        start = int(pd.Timestamp("2026-06-07T22:00Z").timestamp())
        time = [start + d * 86400 + b * 300 for d in range(5) for b in range(276)]
        ds = Dataset(time=time, open=np.ones(len(time)), high=np.ones(len(time)), low=np.ones(len(time)),
                     close=np.ones(len(time)), volume=np.ones(len(time)), interval="5m")
        self.assertEqual(dataset_periods_per_year(ds), 252 * 276)
        self.assertEqual(dataset_periods_per_year(dataset([(100, 100, 100, 100)] * 10)), periods_per_year("5m"))

    def test_holdout_never_cuts_a_globex_session(self):
        start = int(pd.Timestamp("2026-06-07T22:00Z").timestamp())
        time = np.array([start + d * 86400 + b * 300 for d in range(4) for b in range(276)], dtype=float)
        h = holdout_split(time, 25)
        self.assertGreater(h["holdout_bars"], 0)
        self.assertNotEqual(trading_day(time[h["cut"]]), trading_day(time[h["cut"] - 1]))
        self.assertEqual(pd.Timestamp(time[h["cut"]], unit="s").hour, 22)
        self.assertEqual(holdout_split(time[:276], 25)["holdout_bars"], 0)

    def test_futures_vwap_anchors_at_globex_open(self):
        start = int(pd.Timestamp("2026-06-07T22:00Z").timestamp())
        time = [start + h * 3600 for h in range(5)] + [start + 86400]
        px = [100, 102, 104, 106, 108, 120]
        v = vwap(Dataset(time=time, open=px, high=px, low=px, close=px, volume=[1] * 6))
        self.assertEqual((v[3], v[4], v[5]), (103, 104, 120))


class PythonOnlyTests(unittest.TestCase):
    def test_signal_on_bar_i_fills_at_open_of_bar_i_plus_1(self):
        rows = [(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(6)]
        r = run_backtest(dataset(rows), Always(1, at=lambda i: 1 if i == 2 else 0), costs=FRICTIONLESS)
        t = r.trades[0]
        self.assertEqual((t.entry_idx, t.entry_price), (3, 103))       # signal at 2's close, filled at 3's open
        self.assertEqual((t.exit_idx, t.exit_price, t.reason), (4, 104, "signal"))

    def test_costs_are_inside_pnl(self):
        rows = [(100, 100, 100, 100)] * 4
        r = run_backtest(dataset(rows), Always(1, at=lambda i: 1 if i == 0 else 0),
                         costs=dict(slippage_bps=10, commission_per_trade=1, initial_capital=10_000))
        t = r.trades[0]
        self.assertAlmostEqual(t.entry_price, 100.1)
        self.assertAlmostEqual(t.exit_price, 99.9)
        self.assertAlmostEqual(t.pnl, (99.9 - 100.1) * t.qty - 2)
        self.assertAlmostEqual(r.equity[-1], 10_000 + t.pnl)

    def test_flat_by_cutoff_blocks_until_globex_reopen(self):
        # 16:30-18:30 ET on 2026-06-08 (EDT), 30m bars: cutoff 16:45 ET
        start = int(pd.Timestamp("2026-06-08T20:30Z").timestamp())
        time = np.array([start + k * 1800 for k in range(5)], dtype=float)
        end, blocked = flat_by_flags(time, 16 * 60 + 45)
        self.assertEqual(end.tolist(), [True, False, False, False, True])   # last bar of the data also ends a day
        self.assertEqual(blocked.tolist(), [False, True, True, False, False])  # 17:00, 17:30 blocked; 18:00 reopens

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(ValueError):
            run_backtest(dataset([(100, 100, 100, 100)] * 4), Always(1), risk=dict(stopPct=1))  # camelCase typo

    def test_trades_frame_has_utc_times(self):
        r = run_backtest(dataset(decline()), Always(1), costs=FRICTIONLESS, risk=dict(stop_pct=0.5))
        df = r.trades_frame()
        self.assertEqual(str(df.entry_time.dt.tz), "UTC")
        self.assertTrue(math.isclose(df.pnl.sum(), r.equity[-1] - 100_000))

    def test_two_days_fall_back_to_the_interval_label(self):
        # The JS needs 3+ trading days before it trusts a median of bars per day.
        start = int(pd.Timestamp("2026-06-07T22:00Z").timestamp())
        for days, want in ((2, periods_per_year("5m")), (3, 252 * 276)):
            time = [start + d * 86400 + b * 300 for d in range(days) for b in range(276)]
            one = np.ones(len(time))
            ds = Dataset(time=time, open=one, high=one, low=one, close=one, volume=one, interval="5m")
            self.assertEqual(dataset_periods_per_year(ds), want, days)

    def test_news_flags_are_nan_from_the_coverage_end_on(self):
        import econ_calendar as ec
        from backtest.news import news_window_flags
        end = min(ec._cover_end(k) for k in ec._selected("high", None))
        time = [end - 600, end - 300, end, end + 300]
        one = np.ones(4)
        flags = news_window_flags(Dataset(time=time, open=one, high=one, low=one, close=one, volume=one), "high")
        self.assertEqual([math.isnan(x) for x in flags], [False, False, True, True])


class ValidationTests(unittest.TestCase):
    """Inputs that would otherwise give a quietly wrong answer."""

    def setUp(self):
        self.ds = dataset(decline())

    def test_unknown_or_misspelled_params_raise(self):
        from backtest import get_strategy
        with self.assertRaisesRegex(ValueError, "short_side"):
            run_backtest(self.ds, "smaCross", {"short_side": False})
        with self.assertRaisesRegex(ValueError, "maType"):
            run_backtest(self.ds, "smaCross", {"maType": "wma"})
        with self.assertRaisesRegex(ValueError, "before"):
            run_backtest(self.ds, "smaCross", risk=dict(news_blackout=dict(impact="high", before=30)))
        with self.assertRaisesRegex(ValueError, "impact"):
            run_backtest(self.ds, "smaCross", risk=dict(news_blackout=dict(impact="hgh")))
        self.assertEqual(get_strategy("smaCross").id, "smaCross")

    def test_bad_bars_are_refused(self):
        rows = decline()
        o, h, l, c = map(list, zip(*rows))
        good = dict(open=o, high=h, low=l, close=c, volume=[1] * len(c))
        t = [T0 + i * 300 for i in range(len(c))]
        with self.assertRaisesRegex(ValueError, "NaN"):
            Dataset(time=t, **dict(good, close=[math.nan] + c[1:]))
        with self.assertRaisesRegex(ValueError, "epoch seconds"):
            Dataset(time=[x * 1000 for x in t], **good)              # milliseconds
        with self.assertRaisesRegex(ValueError, "epoch seconds"):
            Dataset(time=list(range(len(c))), **good)                 # a row number
        with self.assertRaisesRegex(ValueError, "OHLC"):
            Dataset(time=t, **dict(good, high=[x - 5 for x in h]))
        with self.assertRaisesRegex(ValueError, "DatetimeIndex"):
            Dataset.from_frame(pd.DataFrame(good), "5m")

    def test_from_frame_reads_timestamps_and_any_case(self):
        idx = pd.date_range("2026-06-01 13:30", periods=12, freq="5min", tz="UTC")
        o, h, l, c = map(list, zip(*decline()))
        df = pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=1.0, net_gex=1.0), index=idx)
        ds = Dataset.from_frame(df, "5m", features={"extra": np.zeros(12)})
        self.assertEqual(ds.time[0], idx[0].timestamp())
        self.assertEqual(sorted(ds.features), ["extra", "net_gex"])

    def test_bars_are_frozen_and_copies_get_a_fresh_cache(self):
        import dataclasses
        from backtest.series import get_series
        get_series(self.ds, "sma:3")
        with self.assertRaises(ValueError):
            self.ds.close[0] = 1.0                                    # would leave the cached SMA stale
        other = dataclasses.replace(self.ds, close=self.ds.close * 1.01, high=self.ds.high * 1.01)
        self.assertIsNot(other.cache, self.ds.cache)
        self.assertEqual(other.cache, {})

    def test_windows(self):
        n = len(self.ds)
        r = run_backtest(self.ds, Always(1), window={"start": 2, "end": None})
        self.assertEqual((r.window_start, r.window_end), (2, n - 1))
        with self.assertRaisesRegex(ValueError, "empty window"):
            run_backtest(self.ds, Always(1), window=(8, 4))

    def test_huge_annualised_growth_is_inf_not_a_crash(self):
        # 12 bars rising 1% each with 500 contracts: CAGR overflows a float. JS reports Infinity.
        rows, p = [], 100.0
        for _ in range(12):
            rows.append((p, p * 1.01, p, p * 1.01))
            p *= 1.01
        r = run_backtest(dataset(rows), Always(1), costs=dict(instrument=dict(point_value=20, contracts=500)))
        self.assertEqual(r.metrics["cagr"], math.inf)

    def test_research_strategy_without_its_columns_warns(self):
        with self.assertWarnsRegex(UserWarning, "cannot trade"):
            r = run_backtest(self.ds, "gexRegime")
        self.assertEqual(r.trades, [])
        self.assertEqual(list(r.trades_frame().columns)[:3], ["side", "entry_idx", "entry_time"])

    def test_js_round(self):
        from backtest._js import js_round
        self.assertEqual([js_round(x) for x in (2.5, -2.5, 0.49999999999999994, 1.4999, -0.5)], [3, -2, 0, 1, 0])

    def test_cli_json_is_strict_json(self):
        import contextlib
        import io
        import json
        from pathlib import Path
        from backtest.__main__ import main
        path = Path(__file__).resolve().parents[2] / "frontend" / "public" / "backtest" / "qqq_5m.json"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--data", str(path), "--strategy", "smaCross", "--window", "100", "100", "--json"])
        m = json.loads(out.getvalue(), parse_constant=lambda c: self.fail(f"non-standard JSON constant {c}"))
        self.assertIsNone(m["inference"]["psr"])                     # NaN: one bar has no Sharpe


if __name__ == "__main__":
    unittest.main()
