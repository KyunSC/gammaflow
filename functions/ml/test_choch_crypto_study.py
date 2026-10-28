"""Offline checks for choch_crypto_study.py on synthetic bars; no Binance data is read."""
import unittest

import numpy as np
import pandas as pd

import choch_crypto_study as st
import mfp_crypto_study as mfp

T0 = int(pd.Timestamp("2021-03-01", tz="UTC").timestamp())

# Pinned so the a-priori spec cannot drift silently after the train look. Change it only with a logged reason.
PRIMARY_HASH = "a680817f1496890a"


def zigzag(points, step=1.0):
    """Close path through the given turning points, one bar per `step` of price."""
    out = [float(points[0])]
    for a, b in zip(points, points[1:]):
        n = max(1, int(round(abs(b - a) / step)))
        out.extend(np.linspace(a, b, n + 1)[1:].tolist())
    return np.array(out)


def bars_from_close(c):
    o = np.r_[c[0], c[:-1]]
    return np.maximum(o, c), np.minimum(o, c), c


class Swings(unittest.TestCase):
    def test_levels_js_semantics(self):
        h = np.array([1, 2, 5, 5, 3, 2, 1.0])
        lo = h - 0.5
        is_h, _ = st.swing_points(h, lo, 2)
        # The first bar of a flat top wins: strictly above the left bars, at least the right bars.
        self.assertEqual(np.flatnonzero(is_h).tolist(), [2])

    def test_uptrend_break_shorts_with_stop_past_last_swing_high(self):
        # Higher highs and higher lows, then a close below the last higher low (86).
        c = zigzag([80, 90, 84, 96, 86, 104, 82, 82], step=1.0)
        h, lo, cl = bars_from_close(c)
        ev = st.choch_events(h, lo, cl, 2)
        self.assertEqual(len(ev), 1)
        t, side, level = ev[0]
        self.assertEqual(side, -1)
        self.assertLess(cl[t], 86)
        self.assertGreaterEqual(cl[t - 1], 86)  # the first close below
        self.assertEqual(level, 104)

    def test_downtrend_break_is_the_mirror(self):
        c = 200 - zigzag([80, 90, 84, 96, 86, 104, 82, 82], step=1.0)
        h, lo, cl = bars_from_close(c)
        ev = st.choch_events(h, lo, cl, 2)
        self.assertEqual([(s, lv) for _, s, lv in ev], [(1, 96.0)])

    def test_each_swing_fires_once(self):
        c = zigzag([80, 90, 84, 96, 86, 104, 85, 87, 84, 86, 83], step=1.0)
        h, lo, cl = bars_from_close(c)
        self.assertEqual(sum(1 for _, s, _ in st.choch_events(h, lo, cl, 2) if s < 0), 1)

    def test_no_lookahead_prefix_invariance(self):
        # A signal at bar t must be the same whether or not the bars after t exist.
        rng = np.random.default_rng(11)
        c = 1000 + np.cumsum(rng.normal(0, 3, 1500))
        h, lo, cl = c + rng.uniform(0, 2, c.size), c - rng.uniform(0, 2, c.size), c
        for k in (1, 2, 5):
            full = st.choch_events(h, lo, cl, k)
            for t, side, level in full[::7]:
                pre = st.choch_events(h[: t + 1], lo[: t + 1], cl[: t + 1], k)
                self.assertEqual(pre[-1], (t, side, level))
            self.assertGreater(len(full), 20)

    def test_unconfirmed_swing_is_not_used(self):
        # Price closes below a higher low at 86 one bar after it bounced: 86 is not a known swing yet, so the last
        # higher low is still 84 and nothing fires (a centred-window pivot would short at 85.25).
        c = zigzag([70, 80, 74, 90, 84, 96, 86, 86.5, 84], step=1.0)
        h, lo, cl = bars_from_close(c)
        is_h, is_l = st.swing_points(h, lo, 2)
        self.assertEqual(lo[is_l].tolist(), [74.0, 84.0])
        self.assertEqual(st.choch_events(h, lo, cl, 2), [])


class Signals(unittest.TestCase):
    def market(self, close_4h, minutes=240):
        c = np.repeat(close_4h, minutes)
        t = T0 + 60 * np.arange(c.size)
        df = pd.DataFrame(dict(time=t, open=c, high=c, low=c, close=c, volume=np.ones(c.size)))
        return mfp.Market("BTCUSDT", df)

    def test_signal_on_4h_bars_with_padded_stop(self):
        path = np.r_[np.linspace(100, 110, 30), zigzag([110, 120, 114, 126, 116, 134, 112, 112], step=1.0) - 0]
        m = self.market(path)
        sigs = st.signals_c6(m, 2)
        self.assertTrue(sigs)
        sg = [s for s in sigs if s.side < 0][0]
        self.assertEqual((sg.sig + 1) % 240, 0)  # the last minute of a 4h bar
        self.assertGreater(sg.stop, 134 - m.c[sg.sig])
        self.assertAlmostEqual(sg.target, sg.stop)
        self.assertLessEqual(m.t[sg.end] - m.t[sg.sig], 20 * 86400)

    def test_random_walk_has_no_edge_over_twins(self):
        rng = np.random.default_rng(5)
        n = 720 * 1440
        px = 30000 * np.exp(np.cumsum(rng.normal(0, 6e-4, n)))
        o = np.r_[px[0], px[:-1]]
        df = pd.DataFrame(dict(time=T0 + 60 * np.arange(n), open=o, high=np.maximum(o, px), low=np.minimum(o, px),
                               close=px, volume=np.ones(n)))
        m = mfp.Market("BTCUSDT", df)
        trades = mfp.run_book(m, st.signals_c6(m, 2))
        rl, rs, dirs = mfp.mirrors(trades)
        t = mfp.r_test(rl, rs, dirs, n_twins=500)
        self.assertGreater(t["trades"], 60)
        self.assertGreater(t["p"], 0.01)
        self.assertLess(t["mean_r"], 0.15)


class Spec(unittest.TestCase):
    def test_primary_is_in_grid_and_hash_is_stable(self):
        self.assertIn(st.SPEC["primary"], st.configs())
        self.assertEqual(st.spec_hash(st.SPEC["primary"]), PRIMARY_HASH)
        self.assertEqual(len({st.spec_hash(p) for p in st.configs()}), len(st.configs()))


if __name__ == "__main__":
    unittest.main()
