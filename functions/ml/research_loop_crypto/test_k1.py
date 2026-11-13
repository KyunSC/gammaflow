"""K1 strategy tests on synthetic data only (no train data is read).

    cd functions/ml/research_loop_crypto && ../../../.venv/bin/python -B -m unittest test_k1.py
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller as K  # noqa: E402
from eval import engine as E  # noqa: E402
from eval.features import Series  # noqa: E402
from strategies import k1_cb_premium as S  # noqa: E402

T0 = int(pd.Timestamp('2022-01-03', tz='UTC').timestamp())   # Monday
P = dict(lookback_days=60, min_hist=40, min_samples=70, stop_atr=1.0, min_stop_pct=1.5, hold_h=24, z=0.5)


def market(days=120, seed=0, vol=6e-4, zero=None):
    rng = np.random.default_rng(seed)
    n = days * 1440
    c = 40_000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = np.ones(n)
    if zero is not None:
        v[zero] = 0
    return E.Market('BTCUSDT', pd.DataFrame(dict(time=T0 + 60 * np.arange(n), open=o, high=hi, low=lo, close=c, volume=v)))


class Feats:
    """Coinbase BTC-USD built from the perp so that g_t equals a known per-NY-day gap exactly."""

    def __init__(self, m, seed=1, drop_usdt_day=None, hi=None):
        rng = np.random.default_rng(seed)
        t = np.arange(T0, int(m.t[-1]) - 300, 300, dtype=np.int64)
        if hi is not None:
            t = t[t < hi]
        day, _, _ = S.ny_days(t)
        u = np.unique(day)
        self.gap_bp = dict(zip(u.tolist(), rng.normal(0, 5, len(u))))
        usdt = 1 + rng.normal(0, 5e-4, len(t))
        prem = rng.normal(0, 2e-4, len(t))
        i = np.searchsorted(m.t, t + 240)
        i = np.minimum(i, m.n - 1)
        cb = m.c[i] * usdt * (1 + prem) * np.exp(np.array([self.gap_bp[d] for d in day]) / 1e4)
        ut = t.copy()
        if drop_usdt_day is not None:
            ut = ut[day != drop_usdt_day]
            usdt_v = usdt[day != drop_usdt_day]
        else:
            usdt_v = usdt
        self._cb = Series(t, t + 300, dict(close=cb))
        self._usdt = Series(ut, ut + 300, dict(close=usdt_v))
        self._prem = Series(t + 240, t + 300, dict(close=prem))

    def coinbase(self, product):
        return self._usdt if product == 'USDT-USD' else self._cb

    def pmi(self, kind, sym):
        return self._prem


class K1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = market()
        cls.f = Feats(cls.m)

    def test_daily_gap_is_recovered_exactly(self):
        day, g = S.gap_samples(self.m, self.f, 'BTC-USD')
        u, inv = np.unique(day, return_inverse=True)
        n = np.bincount(inv)
        G = np.bincount(inv, g) / n * 1e4
        full = n == 78
        self.assertGreater(full.sum(), 70)                   # NY weekdays with all 78 samples
        for d, x in zip(u[full], G[full]):
            self.assertAlmostEqual(x, self.f.gap_bp[d], 6)
        _, mins, dow = S.ny_days(np.array([T0]))
        self.assertTrue(set(n) <= set(range(79)))

    def test_z_uses_only_previous_days(self):
        day, g = S.gap_samples(self.m, self.f, 'BTC-USD')
        zs = S.daily_z(day, g, P)
        valid = sorted(d for d in np.unique(day) if (day == d).sum() >= 70)
        d = sorted(zs)[5]
        prev = [self.f.gap_bp[x] for x in valid if x < d][-60:]
        want = (self.f.gap_bp[d] - np.mean(prev)) / np.std(prev, ddof=1)
        self.assertAlmostEqual(zs[d], want, 6)
        self.assertEqual(len([x for x in valid if x < sorted(zs)[0]]), 40)   # first z needs 40 prior valid days

    def test_signals(self):
        zs = S.daily_z(*S.gap_samples(self.m, self.f, 'BTC-USD'), P)
        sigs = S.signals(self.m, self.f, P)
        self.assertGreater(len(sigs), 10)
        for s in sigs:
            self.assertEqual(self.m.ny_min[s.sig], 959)
            z = zs[int(self.m.ny_date[s.sig])]
            self.assertGreaterEqual(abs(z), 0.5)
            self.assertEqual(s.side, 1 if z > 0 else -1)
            self.assertIsNone(s.target)
            self.assertGreaterEqual(s.stop, 0.015 * self.m.c[s.sig] - 1e-9)
            if s.end + 1 < self.m.n:   # the last signal's exit is clipped at the data end
                self.assertAlmostEqual((self.m.t[s.end + 1] - self.m.t[s.sig + 1]) / 3600, 24, 6)
        hi = S.signals(self.m, self.f, {**P, 'z': 1.0})
        self.assertLess(len(hi), len(sigs))
        self.assertEqual(S.signals(E.Market('SOLUSDT', self.m.bars), self.f, P), [])

    def test_missing_usdt_or_stale_bars_drop_the_day(self):
        day, _ = S.gap_samples(self.m, self.f, 'BTC-USD')
        target = sorted(np.unique(day))[50]
        f2 = Feats(self.m, drop_usdt_day=target)
        d2, _ = S.gap_samples(self.m, f2, 'BTC-USD')
        self.assertNotIn(target, set(d2.tolist()))
        # a stale run (>= 3 zero-volume bars) covering 10 sample bars removes those samples: 68 < 70, day skipped
        first = int(np.flatnonzero((self.m.ny_date == target) & (self.m.ny_min == 600))[0])
        zero = np.zeros(self.m.n, bool)
        zero[first - 1:first + 50] = True
        m3 = market(zero=zero)
        d3, _ = S.gap_samples(m3, Feats(m3), 'BTC-USD')
        self.assertLess((d3 == target).sum(), 70)
        self.assertNotIn(target, S.daily_z(*S.gap_samples(m3, Feats(m3), 'BTC-USD'), P))

    def test_truncation_invariant(self):
        cut = pd.Timestamp(T0 + 100 * 86400 + 13 * 3600 + 47 * 60, unit='s', tz='UTC')

        def fake_load(blk, sym, w):
            keep = self.m.bars[self.m.bars['time'] < int(blk.end.timestamp())].reset_index(drop=True)
            mm = E.Market(sym, keep)
            return mm, Feats(mm, hi=int(blk.end.timestamp())), 0
        blk = K.Block('train', pd.Timestamp(T0, unit='s', tz='UTC'), pd.Timestamp(T0 + 119 * 86400, unit='s', tz='UTC'), Path('.'))
        full = S.signals(self.m, self.f, P)
        with mock.patch.object(K, 'load_market', fake_load), mock.patch.object(K, 'TRUNC_CUTS', (cut,)):
            r = K.truncation_check(S, P, 'BTCUSDT', blk, 0, self.m, full)
        self.assertTrue(r['ok'] and r['before_cut'] > 10, r)

    def test_source_allowed(self):
        K.check_source(Path(S.__file__).read_text(), 'k1_cb_premium.py')


if __name__ == '__main__':
    unittest.main()
