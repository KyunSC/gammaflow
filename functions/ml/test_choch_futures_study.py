"""Offline checks for choch_futures_study.py on synthetic 1m bars; no Databento data is read."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import choch_futures_study as st
import mfp_crypto_study as mfp

SUNDAY_OPEN = pd.Timestamp("2015-03-01 18:00", tz=st.ET)  # a Sunday


def globex_frame(close, inst=None, start=SUNDAY_OPEN, high=None, low=None, open_=None):
    """1m bars at Globex hours only (Sun 18:00 -> Fri 17:00 ET, daily 17:00-18:00 break), UTC index ts_event."""
    n = len(close)
    stamps, t = [], start
    while len(stamps) < n:
        local = t.tz_convert(st.ET)
        dow, hm = local.dayofweek, local.hour * 60 + local.minute
        closed = (dow == 5) or (dow == 6 and hm < 18 * 60) or (dow == 4 and hm >= 17 * 60) or (17 * 60 <= hm < 18 * 60)
        if not closed:
            stamps.append(t)
        t += pd.Timedelta(minutes=1)
    c = np.asarray(close, float)
    o = np.r_[c[0], c[:-1]] if open_ is None else np.asarray(open_, float)
    h = np.maximum(o, c) if high is None else np.asarray(high, float)
    lo = np.minimum(o, c) if low is None else np.asarray(low, float)
    idx = pd.DatetimeIndex(stamps).tz_convert("UTC").rename("ts_event")
    return pd.DataFrame(dict(open=o, high=h, low=lo, close=c,
                             instrument_id=np.full(n, 1) if inst is None else np.asarray(inst)), index=idx)


def walk(n, seed, sd=0.75, p0=2000.0):
    rng = np.random.default_rng(seed)
    return np.round((p0 + np.cumsum(rng.normal(0, sd, n))) / st.TICK) * st.TICK


class Calendar(unittest.TestCase):
    def test_sessions_and_4h_buckets_follow_the_globex_open(self):
        tp = st.tape_from_frame(globex_frame(np.full(60 * 23, 2000.0)))  # exactly the Monday session
        et = pd.to_datetime(tp.t, unit="s", utc=True).tz_convert(st.ET)
        monday = (pd.Timestamp("2015-03-02") - pd.Timestamp(0)).days
        self.assertTrue((tp.session[et.dayofweek == 6] == monday).all())  # Sunday evening trades for Monday
        at = {(e.hour, e.minute): (s, b) for e, s, b in zip(et, tp.session, tp.bucket)}
        self.assertEqual(at[(18, 0)], (monday, 0))
        self.assertEqual(at[(21, 59)], (monday, 0))
        self.assertEqual(at[(22, 0)], (monday, 1))
        self.assertEqual(at[(9, 59)], (monday, 3))
        self.assertEqual(at[(14, 0)], (monday, 5))
        self.assertEqual(at[(16, 59)], (monday, 5))

    def test_load_reads_only_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            early = globex_frame(np.full(600, 1.0), start=pd.Timestamp("2011-12-30 10:00", tz=st.ET))
            inside = globex_frame(np.full(600, 2.0), start=pd.Timestamp("2012-01-02 18:00", tz=st.ET))
            late = globex_frame(np.full(600, 3.0), start=pd.Timestamp("2021-12-31 16:00", tz=st.ET))
            pd.concat([early, inside, late]).to_parquet(Path(d) / "x.parquet")
            tp = st.load("ES", Path(d))
        self.assertEqual(set(tp.c.tolist()), {2.0, 3.0})
        last = pd.Timestamp(int(tp.t.max()), unit="s", tz="UTC").tz_convert(st.ET)
        self.assertEqual((last.date(), last.hour), (pd.Timestamp("2021-12-31").date(), 16))
        first = pd.Timestamp(int(tp.t.min()), unit="s", tz="UTC").tz_convert(st.ET)
        self.assertEqual(str(first), "2012-01-02 18:00:00-05:00")


class Execution(unittest.TestCase):
    def tape(self, close, **kw):
        return st.tape_from_frame(globex_frame(close, **kw))

    def test_costs_and_slippage_in_r(self):
        tp = self.tape(np.r_[np.full(5, 2000.0), np.linspace(2000, 2012, 49), np.full(50, 2012.0)])
        sg = st.FSignal(3, 1, 1990.0, 2010.0, 10.0, tp.n - 1)
        lg = st.simulate(tp, sg, 1, tp.n - 1)
        self.assertEqual(lg.reason, "target")
        # Target 10 points above the 2000 entry, one slipped fill (entry), $4.50 on $50/pt.
        self.assertAlmostEqual(lg.r(50.0), (10 - 0.25 - 4.5 / 50) / 10)
        self.assertAlmostEqual(lg.r(50.0, 0, 0), 1.0)
        self.assertAlmostEqual(lg.r(50.0, 2, 2), (10 - 0.5 - 9 / 50) / 10)

    def test_target_needs_a_tick_through(self):
        c = np.r_[np.full(5, 2000.0), np.full(20, 2010.0), np.full(5, 2000.0)]
        tp = self.tape(c, high=c, low=np.minimum(c, np.r_[c[0], c[:-1]]))
        lg = st.simulate(tp, st.FSignal(3, 1, 1990.0, 2010.0, 10.0, tp.n - 1), 1, tp.n - 1)
        self.assertEqual(lg.reason, "data-end")

    def test_gap_through_stop_fills_at_the_open_and_stop_wins_ties(self):
        c = np.r_[np.full(5, 2000.0), np.full(10, 1980.0)]
        tp = self.tape(c, open_=c)
        lg = st.simulate(tp, st.FSignal(3, 1, 1990.0, 2010.0, 10.0, tp.n - 1), 1, tp.n - 1)
        self.assertEqual(lg.reason, "stop")
        self.assertAlmostEqual(lg.points, -20.0)
        self.assertAlmostEqual(lg.r(50.0), (-20 - 0.5 - 0.09) / 10)
        h = np.r_[np.full(5, 2000.0), 2015.0, np.full(5, 2000.0)]
        lo = np.r_[np.full(5, 2000.0), 1985.0, np.full(5, 2000.0)]
        tp2 = self.tape(np.full(11, 2000.0), high=h, low=lo)
        self.assertEqual(st.simulate(tp2, st.FSignal(3, 1, 1990.0, 2010.0, 10.0, 10), 1, 10).reason, "stop")

    def test_mirror_leg_uses_mirrored_levels(self):
        tp = self.tape(np.r_[np.full(5, 2000.0), np.linspace(2000, 1985, 16), np.full(10, 1985.0)])
        sg = st.FSignal(3, 1, 1990.0, 2010.0, 10.0, tp.n - 1)
        self.assertEqual(st.simulate(tp, sg, 1, tp.n - 1).reason, "stop")
        short = st.simulate(tp, sg, -1, tp.n - 1)
        self.assertEqual(short.reason, "target")  # short from 2000, target 1990
        self.assertAlmostEqual(short.points, 10.0)


class Signals(unittest.TestCase):
    def test_roll_restarts_the_run_and_closes_trades(self):
        n = 60 * 24 * 40
        c = walk(n, 3)
        inst = np.r_[np.full(n // 2, 1), np.full(n - n // 2, 2)]
        c[n // 2:] += 40.0  # the next contract trades at a premium: a fake jump at the roll
        tp = st.tape_from_frame(globex_frame(c, inst=inst))
        sigs = st.signals(tp, 2)
        self.assertTrue(sigs)
        for sg in sigs:
            self.assertEqual(tp.inst[sg.sig], tp.inst[sg.end])  # never held into the next contract
            self.assertEqual(tp.bucket[sg.sig + 1] != tp.bucket[sg.sig] or tp.session[sg.sig + 1] != tp.session[sg.sig], True)
        trades = st.run_book(tp, sigs)
        self.assertTrue(all(tp.inst[t.legs[1].exit] == tp.inst[t.sig.sig] for t in trades))

    def test_no_signal_reads_a_later_4h_bar(self):
        n = 60 * 24 * 30
        c = walk(n, 9)
        full = st.signals(st.tape_from_frame(globex_frame(c)), 2)
        for sg in full[::3]:
            pre = st.signals(st.tape_from_frame(globex_frame(c[: sg.sig + 2])), 2)
            self.assertTrue(any(p.sig == sg.sig and p.side == sg.side and p.stop == sg.stop for p in pre))

    def test_random_walk_has_no_edge_over_twins(self):
        tp = st.tape_from_frame(globex_frame(walk(60 * 23 * 5 * 52 * 2, 21)))
        res = st.score(tp, "ES", 2, n_twins=500, controls=True)
        self.assertGreater(res["trades"], 40)
        self.assertGreater(res["twins"]["p"], 0.01)
        self.assertLess(res["controls"]["coin_pass_rate"], 0.1)
        self.assertLess(res["controls"]["lookahead"]["p"], 0.01)  # the planted bug must be caught


class OneLook(unittest.TestCase):
    def test_prereg_pins_the_current_files(self):
        self.assertEqual(json.loads(st.PREREG.read_text())["script_sha"], st.script_sha())
        self.assertEqual(st.looks(), [])

    def test_refuses_a_second_look_and_a_changed_spec(self):
        with tempfile.TemporaryDirectory() as d:
            looks, prereg = Path(d) / "looks.log", Path(d) / "prereg.json"
            prereg.write_text(json.dumps(dict(script_sha=st.script_sha())))
            looks.write_text("script=x at then\n")
            with mock.patch.object(st, "LOOKS", looks), mock.patch.object(st, "PREREG", prereg), \
                    mock.patch.object(st, "load", side_effect=AssertionError("must not read bars")):
                self.assertEqual(st.main(["--score"]), 1)
                looks.write_text("")
                prereg.write_text(json.dumps(dict(script_sha="0" * 16)))
                self.assertEqual(st.main(["--score"]), 1)

    def test_incomplete_download_does_not_spend_the_look(self):
        with tempfile.TemporaryDirectory() as d:
            looks = Path(d) / "looks.log"
            tp = st.tape_from_frame(globex_frame(np.full(100, 2000.0)))
            with mock.patch.object(st, "LOOKS", looks), mock.patch.object(st, "load", return_value=tp):
                self.assertEqual(st.main(["--score"]), 1)
            self.assertFalse(looks.exists())


if __name__ == "__main__":
    unittest.main()
