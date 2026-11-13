"""Synthetic-only tests for choch_futures_swing (no real bars are read).

    ./.venv/bin/python test_choch_futures_swing.py
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

import choch_futures_swing as s
import choch_rule

T0 = int(pd.Timestamp("2015-03-02 00:00", tz="UTC").timestamp())  # a Monday, UTC midnight
B = s.BAR_SECONDS
TK = s.TICK


def tape(rows, seg=None, t=None, product="NQ", iid=None) -> s.Tape:
    a = np.asarray(rows, float)
    n = len(a)
    t = np.asarray(t if t is not None else T0 + np.arange(n) * 60, np.int64)
    return s.Tape(product, t, a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.ones(n, int) if seg is None else np.asarray(seg),
                  None if iid is None else np.asarray(iid))


def walk(seed: int, days: int, roll_at: float | None = None, product="NQ") -> s.Tape:
    """24h random walk of 1m bars on the tick grid; an optional roll (new segment, price jump) at a fraction of it."""
    rng = np.random.default_rng(seed)
    n = days * 1440
    c = 10000 + np.cumsum(np.round(rng.normal(0, 8, n)) * TK)
    o = np.r_[10000.0, c[:-1]]
    h = np.maximum(o, c) + np.round(np.abs(rng.normal(0, 3, n))) * TK
    l = np.minimum(o, c) - np.round(np.abs(rng.normal(0, 3, n))) * TK
    seg = np.ones(n, int)
    if roll_at is not None:
        r = int(n * roll_at)
        seg[r:] = 2
        o[r:], h[r:], l[r:], c[r:] = o[r:] + 40, h[r:] + 40, l[r:] + 40, c[r:] + 40
    return s.Tape(product, T0 + np.arange(n) * 60, o, h, l, c, seg)


# One 1m bar per 4h bin, so each row is a 4h bar. 14 rising warm-up bins (no swings, finite ATR from bin 13), then a
# k=1 uptrend (swing highs 12, 14, 15; swing lows 7, 9) and a close of 8.6 below the last higher low at bin 21: a
# bearish CHoCH with extreme 15.
WARM = [(1.5 + 0.5 * i, 2 + 0.5 * i, 1 + 0.5 * i, 1.5 + 0.5 * i) for i in range(14)]
PATTERN = [(9, 10, 8, 9), (10, 12, 9, 11), (11, 11, 7, 8), (8, 13, 8, 12), (12, 14, 10, 13), (13, 13, 9, 10),
           (10, 15, 11, 14), (14, 14.5, 8.5, 8.6)]
SIG_BIN = len(WARM) + len(PATTERN) - 1


def choch_tape(after, seg=None) -> s.Tape:
    rows = WARM + PATTERN + list(after)
    return tape(rows, seg=seg, t=T0 + np.arange(len(rows)) * B)


def flat(px, n, half=0.1):
    return [(px, px + half, px - half, px)] * n


class Binning(unittest.TestCase):
    def test_utc_4h_bins_no_fabrication(self):
        ts = [pd.Timestamp(x, tz="UTC").timestamp() for x in
              ("2015-03-06 00:00", "2015-03-06 03:59", "2015-03-06 04:00", "2015-03-06 07:59", "2015-03-06 20:59",
               "2015-03-08 23:00", "2015-03-08 23:59", "2015-03-09 00:00")]  # Fri .. Sun-evening reopen .. Mon
        tp = tape([(100, 101, 99, 100)] * len(ts), t=ts)
        bn = s.bins_4h(tp, 0, tp.n)
        self.assertEqual(bn.first.tolist(), [0, 2, 4, 5, 7])
        self.assertEqual(bn.last.tolist(), [1, 3, 4, 6, 7])
        self.assertTrue(np.all(np.diff(bn.key) > 0))
        self.assertEqual(len(bn.key), 5)  # the weekend's empty bins do not exist
        self.assertEqual(int(bn.key[0]) * B, int(pd.Timestamp("2015-03-06 00:00", tz="UTC").timestamp()))

    def test_no_bin_spans_a_roll(self):
        tp = walk(1, 3, roll_at=0.5)  # roll at 12:00 UTC on day 2... bins 12:00-16:00 on both sides
        tp.seg[tp.t >= tp.t[0] + 86400 + 2 * 3600] = 2  # move the roll inside a 4h bin (02:00 UTC)
        tp.seg[tp.t < tp.t[0] + 86400 + 2 * 3600] = 1
        for a, b in tp.segments():
            bn = s.bins_4h(tp, a, b)
            self.assertTrue(np.all(tp.seg[bn.first] == tp.seg[bn.last]))
            self.assertTrue(bn.first[0] == a and bn.last[-1] == b - 1)
        keys = [s.bins_4h(tp, a, b).key for a, b in tp.segments()]
        self.assertEqual(keys[0][-1], keys[1][0])  # the 00:00-04:00 bin is split in two, one per segment


class Rule(unittest.TestCase):
    def test_uses_choch_rule_verbatim(self):
        self.assertIs(s.choch_events, choch_rule.choch_events)
        self.assertEqual(len(s.spec_hash()), 16)
        self.assertIn("choch_rule.py", s.code_hashes())

    def test_signal_stop_distance_and_next_bar_entry(self):
        tp = choch_tape(flat(8.5, 5))
        sigs, _ = s.signals(tp, k=1)
        self.assertEqual(len(sigs), 1)
        sg = sigs[0]
        bn = s.bins_4h(tp, 0, tp.n)
        atr = bn.atr(14)[SIG_BIN]
        self.assertEqual((sg.sig, sg.entry, sg.side), (SIG_BIN, SIG_BIN + 1, -1))
        self.assertAlmostEqual(sg.dist, (15 - 8.6) + 0.1 * atr)
        self.assertEqual(sg.end_why, "window_end")

    def test_swings_and_atr_reset_at_roll(self):
        n = len(WARM) + len(PATTERN) + 5
        seg = np.ones(n, int)
        seg[SIG_BIN:] = 2  # roll just before the breaking bin: segment 1's swings are forgotten
        self.assertEqual(s.signals(choch_tape(flat(8.5, 5), seg=seg), k=1)[0], [])
        seg = np.ones(n, int)
        seg[SIG_BIN - 12:] = 2  # roll inside the warm-up: 13 bins up to the signal, ATR14 not ready; swings intact
        sigs, skipped = s.signals(choch_tape(flat(8.5, 5), seg=seg), k=1)
        self.assertEqual((sigs, skipped["atr_warmup"]), ([], 1))

    def test_signals_of_a_segment_do_not_depend_on_the_previous_one(self):
        full = walk(3, 40, roll_at=0.5)
        a = int(np.flatnonzero(full.seg == 2)[0])
        alone = s.Tape("NQ", full.t[a:], full.o[a:], full.h[a:], full.l[a:], full.c[a:], full.seg[a:])
        for k in (1, 2):
            got = [(g.sig - a, g.side, round(g.dist, 9), g.end - a, g.end_why) for g in s.signals(full, k)[0] if g.sig >= a]
            ref = [(g.sig, g.side, round(g.dist, 9), g.end, g.end_why) for g in s.signals(alone, k)[0]]
            self.assertEqual(got, ref)
            self.assertTrue(len(ref) > 0)

    def test_entry_is_next_1m_bar_same_segment(self):
        tp = walk(5, 30, roll_at=0.6)
        sigs, _ = s.signals(tp, 2)
        self.assertTrue(len(sigs) > 3)
        for g in sigs:
            self.assertEqual(g.entry, g.sig + 1)
            self.assertNotEqual(tp.t[g.sig] // B, tp.t[g.entry] // B)  # sig is the last 1m bar of its bin
            self.assertEqual(tp.seg[g.sig], tp.seg[g.entry])

    def test_no_entry_bar_in_segment_skips(self):
        n = len(WARM) + len(PATTERN) + 3
        seg = np.ones(n, int)
        seg[SIG_BIN + 1:] = 2  # the signal bin is the segment's last bar
        sigs, skipped = s.signals(choch_tape(flat(8.5, 3), seg=seg), k=1)
        self.assertEqual((sigs, skipped["no_entry_bar"]), ([], 1))


class Execution(unittest.TestCase):
    def leg(self, rows, side, dist=2.0, end=None, why="time"):
        tp = tape(rows)
        sg = s.Signal(0, 1, side, dist, tp.n - 1 if end is None else end, why)
        return s.leg(tp, sg, side)

    # row 0 = signal bar, row 1 = entry bar (open 100): long fills 100.25, stop 98.25, target 102.25; short fills 99.75, stop 101.75, target 97.75
    def test_long_target_tick_through(self):
        lg = self.leg([(100, 100, 100, 100), (100, 101, 99.5, 100), (100, 102.25, 99, 101), (101, 102.5, 100, 102)], 1)
        self.assertEqual((lg.why, lg.exit, lg.pts, lg.exit_px), ("target", 3, 2.0, 102.25))  # 102.25 touch is no fill

    def test_long_stop_slip_and_gap(self):
        lg = self.leg([(100, 100, 100, 100), (100, 100.5, 98.25, 99), (99, 99, 99, 99)], 1)
        self.assertEqual((lg.why, lg.exit, lg.pts), ("stop", 1, -2.25))  # the entry bar can stop out (not at its open)
        lg = self.leg([(100, 100, 100, 100), (100, 100.5, 99, 99.5), (97, 97.5, 96, 97)], 1)
        self.assertEqual((lg.why, lg.exit, lg.exit_px, lg.pts), ("stop", 2, 96.75, 96.75 - 100.25))

    def test_long_same_bar_stop_first(self):
        lg = self.leg([(100, 100, 100, 100), (100, 103, 97, 100)], 1)
        self.assertEqual((lg.why, lg.pts), ("stop", -2.25))

    def test_short_mirror(self):
        lg = self.leg([(100, 100, 100, 100), (100, 100.5, 97.75, 99), (99, 99.5, 97.5, 98)], -1)
        self.assertEqual((lg.why, lg.exit, lg.entry_px, lg.exit_px, lg.pts), ("target", 2, 99.75, 97.75, 2.0))
        lg = self.leg([(100, 100, 100, 100), (100, 101.75, 99, 101)], -1)
        self.assertEqual((lg.why, lg.exit_px, lg.pts), ("stop", 102.0, -2.25))
        lg = self.leg([(100, 100, 100, 100), (100, 100.5, 99.5, 100), (103, 104, 102.5, 103.5)], -1)
        self.assertEqual((lg.why, lg.exit_px, lg.pts), ("stop", 103.25, 99.75 - 103.25))

    def test_close_exit_slips_one_tick(self):
        lg = self.leg([(100, 100, 100, 100)] + flat(100.5, 4), 1, end=3, why="roll")
        self.assertEqual((lg.why, lg.exit, lg.pts), ("roll", 3, (100.5 - TK) - (100.5 + TK)))
        lg = self.leg([(100, 100, 100, 100)] + flat(100.5, 4), -1, why="time")
        self.assertEqual((lg.why, lg.exit, lg.pts), ("time", 4, (100.5 - TK) - (100.5 + TK)))

    def test_net_r(self):
        self.assertAlmostEqual(s.net_r(2.0, 2.0, 2.0), (4 - 1) / 4)       # MNQ
        self.assertAlmostEqual(s.net_r(-2.25, 2.0, 5.0), (-11.25 - 1) / 10)  # MES

    def test_forced_exit_at_segment_end_and_time_cap(self):
        n_after = 10
        n = len(WARM) + len(PATTERN) + n_after
        seg = np.ones(n, int)
        seg[SIG_BIN + 6:] = 2
        tp = choch_tape(flat(8.5, n_after, half=0.05), seg=seg)
        trades, _ = s.run_book(tp, s.signals(tp, 1)[0])
        self.assertEqual(len(trades), 1)
        for side in (1, -1):
            lg = trades[0].legs[side]
            self.assertEqual((lg.why, lg.exit), ("roll", SIG_BIN + 5))
            self.assertAlmostEqual(lg.exit_px, 8.5 - side * TK)
        # no roll, 30 days of quiet 4h bars: time cap at the last bar starting before entry + 20 days
        tp = choch_tape(flat(8.5, 180, half=0.05))
        trades, _ = s.run_book(tp, s.signals(tp, 1)[0])
        lg = trades[0].legs[-1]
        self.assertEqual((lg.why, lg.exit), ("time", SIG_BIN + 1 + 119))
        self.assertLess(tp.t[lg.exit] + 60, tp.t[SIG_BIN + 1] + 20 * 86400 + 1)
        # tape ends before the cap
        tp = choch_tape(flat(8.5, 30, half=0.05))
        self.assertEqual(s.run_book(tp, s.signals(tp, 1)[0])[0][0].legs[1].why, "window_end")


class Book(unittest.TestCase):
    def test_one_position_mirror_flat(self):
        tp = tape(flat(100, 100, half=0))
        mk = lambda e, end, side=1: s.Signal(e - 1, e, side, 1.0, end, "time")  # noqa: E731
        trades, dropped = s.run_book(tp, [mk(5, 50), mk(20, 70), mk(50, 80), mk(51, 60, -1)])
        self.assertEqual([t.sig.entry for t in trades], [5, 51])
        self.assertEqual(dropped, 2)  # entry inside the trade, and entry on its exit bar
        # long leg still open after the short leg stops: the book stays busy (mirror-flat)
        rows = flat(100, 60, half=0)
        rows[10] = (100, 101, 100, 100)  # short stop 99.75 + 1 = 100.75 hit; long target 101.25 + tick not reached
        tp = tape(rows)
        trades, dropped = s.run_book(tp, [mk(5, 50, -1), mk(30, 55, -1), mk(52, 58, -1)])
        self.assertEqual(trades[0].legs[-1].exit, 10)
        self.assertEqual(trades[0].legs[1].exit, 50)
        self.assertEqual(([t.sig.entry for t in trades], dropped), ([5, 52], 1))

    def test_prefix_invariance(self):
        full = walk(11, 60, roll_at=0.4)
        k = 2
        tf, _ = s.run_book(full, s.signals(full, k)[0])
        cut = int(full.n * 0.75) + 37  # mid-bin on purpose
        part = s.Tape("NQ", full.t[:cut], full.o[:cut], full.h[:cut], full.l[:cut], full.c[:cut], full.seg[:cut])
        tpart, _ = s.run_book(part, s.signals(part, k)[0])

        def key(t):
            return (t.sig.sig, t.sig.side, round(t.sig.dist, 9),
                    tuple((lg.exit, lg.why, round(lg.pts, 9)) for lg in (t.legs[1], t.legs[-1])))
        done_full = [key(t) for t in tf if t.exit < cut - 1]
        done_part = [key(t) for t in tpart if t.exit < cut - 1]
        self.assertGreater(len(done_full), 3)
        self.assertEqual(done_full, done_part)
        # every signal whose bin closed and entered before the cut is the same, side and distance included
        sf = [(g.sig, g.side, round(g.dist, 9)) for g in s.signals(full, k)[0] if g.entry < cut - 1]
        sp = [(g.sig, g.side, round(g.dist, 9)) for g in s.signals(part, k)[0] if g.entry < cut - 1]
        self.assertEqual(sf, sp)


class Statistics(unittest.TestCase):
    def test_twin_p_calibrated_on_random_walk(self):
        """No edge on a random walk: per-walk twin p roughly uniform, and the pooled test neither passes nor is tiny."""
        ps, ps_fair, pool = [], [], [[], [], []]
        for seed in range(40):
            tp = walk(100 + seed, 120, roll_at=0.5)
            trades, _ = s.run_book(tp, s.signals(tp, 2)[0])
            m = s.mirrors(trades, s.PT_USD["NQ"])
            ps.append(s.r_test(*m, n_twins=500)["p"])
            ps_fair.append(s.r_test(*m, p_long=0.5, n_twins=500)["p"])
            for acc, x in zip(pool, m):
                acc.append(x)
        ps, ps_fair = np.array(ps), np.array(ps_fair)
        self.assertTrue(0.3 < np.median(ps) < 0.7, ps)
        self.assertLessEqual((ps < 0.05).mean(), 0.15, ps)
        self.assertLessEqual((ps_fair < 0.05).mean(), 0.15, ps_fair)
        t = s.r_test(*(np.concatenate(x) for x in pool), n_twins=2000)
        self.assertGreater(t["trades"], 400)
        self.assertGreater(t["p"], 0.05)
        self.assertFalse(s.passes(t))

    def test_r_test_detects_planted_edge(self):
        rng = np.random.default_rng(0)
        rl = rng.choice([1.0, -1.1], 300)
        rs = -rl - 0.1
        self.assertLess(s.r_test(rl, rs, np.where(rl > 0, 1, -1), n_twins=500)["p"], 0.01)


class OneLook(unittest.TestCase):
    def test_lock_written_before_load_and_refuses_second_run(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "choch_futures"
            loaded = []

            def load(p):
                self.assertTrue((out / "swing.lock").exists() and (out / "swing_prereg.json").exists())
                loaded.append(p)
                return walk(200 + len(loaded), 40, roll_at=0.5, product=p)

            with redirect_stdout(io.StringIO()) as buf:
                rc = s.confirm(out, n_twins=50, load=load, missing=lambda p: [])
            self.assertEqual(rc, 0)
            self.assertEqual(loaded, ["NQ", "ES"])
            self.assertIn("VERDICT", buf.getvalue())
            res = json.loads((out / "swing_results.json").read_text())
            self.assertIn(res["verdict"], ("PASS", "FAIL"))
            self.assertEqual(set(res["products"]["NQ"]["rows"]), {"k=1", "k=2", "k=3", "k=5"})
            pre = json.loads((out / "swing_prereg.json").read_text())
            self.assertEqual(pre["spec_hash"], res["spec_hash"])
            self.assertEqual(pre["spec"]["id"], "C6F")
            self.assertIn("finished", (out / "swing.lock").read_text())
            before = (out / "swing_results.json").read_text()
            with redirect_stdout(io.StringIO()):
                rc = s.confirm(out, n_twins=50, load=load, missing=lambda p: [])
            self.assertEqual(rc, 3)
            self.assertEqual(loaded, ["NQ", "ES"])
            self.assertEqual((out / "swing_results.json").read_text(), before)

    def test_missing_month_refuses_without_lock(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x"
            with redirect_stdout(io.StringIO()):
                rc = s.confirm(out, n_twins=50, load=lambda p: self.fail("loaded bars"),
                               missing=lambda p: ["2015-05"] if p == "ES" else [])
            self.assertEqual(rc, 2)
            self.assertFalse((out / "swing.lock").exists())

    def test_check_reports_rolls_without_signals(self):
        tp = walk(7, 5, roll_at=0.5)
        tp.iid = np.where(tp.seg == 1, 101, 202)
        with redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(s.check(load=lambda p: tp, missing=lambda p: []), 0)
        self.assertIn("2 contract segments", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
