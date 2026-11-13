"""K4 strategy tests on synthetic data only (no train data is read).

    cd functions/ml/research_loop_crypto && ../../../.venv/bin/python -B -m unittest test_k4.py
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
from strategies import k4_dvol_regime as S  # noqa: E402

T0 = int(pd.Timestamp('2022-01-01', tz='UTC').timestamp())
P = dict(rv_days=30, lookback=180, min_hist=120, stop_atr=1.0, min_stop_pct=1.5, hold_h=48, N=5)
DAYS = 330


def market(days=DAYS, seed=0, zero=None, drop=None):
    rng = np.random.default_rng(seed)
    n = days * 1440
    vol = np.repeat(np.exp(rng.normal(np.log(6e-4), 0.35, days)), 1440)      # regime-varying vol
    c = 40_000 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 1, n)) * vol / 2)
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 1, n)) * vol / 2)
    v = np.ones(n)
    if zero is not None:
        v[zero] = 0
    df = pd.DataFrame(dict(time=T0 + 60 * np.arange(n), open=o, high=hi, low=lo, close=c, volume=v))
    if drop is not None:
        df = df.drop(index=drop).reset_index(drop=True)
    return E.Market('BTCUSDT', df)


class Feats:
    def __init__(self, days=DAYS, seed=9, drop=(), hi=None):
        rng = np.random.default_rng(seed)
        t = np.arange(T0, T0 + days * 86400, 3600, dtype=np.int64)
        cl = 55 * np.exp(np.cumsum(rng.normal(0, 0.02, len(t))))
        keep = ~np.isin(t, list(drop))
        if hi is not None:
            keep &= t < hi
        t, cl = t[keep], cl[keep]
        self._d = Series(t, t + 3600, dict(open=cl, high=cl, low=cl, close=cl))

    def dvol(self, cur):
        return self._d


def brute(m, f, p):
    """Independent reference with pandas daily resampling and timestamp lookups."""
    b = m.bars.copy()
    b['day'] = b['time'] // 86400
    b['stale'] = m.stale
    g = b.groupby('day').agg(n=('time', 'size'), st=('stale', 'sum'), h=('high', 'max'), l=('low', 'min'),
                             c=('close', 'last'), last_t=('time', 'max'))
    dv = pd.Series(f._d.values['close'], index=f._d.stamp + 3600)            # usable at the hour's end
    idx = pd.Series(np.arange(m.n), index=m.t)
    hist, out = [], []
    W, N = p['rv_days'], p['N']
    for d in g.index:
        win = [d - k for k in range(W, -1, -1)]
        if not all(w in g.index for w in win) or not all(g.loc[w, 'n'] == 1440 and g.loc[w, 'st'] == 0 for w in win):
            continue
        T = (d + 1) * 86400
        a = dv[(dv.index <= T) & (dv.index >= T - 7200)]
        if not len(a):
            continue
        rv = np.std(np.diff(np.log(g.loc[win, 'c'].to_numpy())), ddof=1) * np.sqrt(365) * 100
        x = np.log(a.iloc[-1] / rv)
        prev = g.loc[[d - k for k in range(N, 0, -1)]]
        c = g.loc[d, 'c']
        br = 1 if c > prev['h'].max() else (-1 if c < prev['l'].min() else 0)
        if len(hist) >= p['min_hist'] and br != 0:
            H = np.array(hist[-p['lookback']:])
            lo, hi = np.quantile(H, 1 / 3), np.quantile(H, 2 / 3)
            if x >= hi:
                out.append((int(idx[g.loc[d, 'last_t']]), br))
            elif x <= lo:
                out.append((int(idx[g.loc[d, 'last_t']]), -br))
        hist.append(x)
    return out


class K4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.f = market(), Feats()

    def test_matches_brute_force_and_both_arms(self):
        for N in (5, 10):
            p = {**P, 'N': N}
            got = [(s.sig, s.side) for s in S.signals(self.m, self.f, p)]
            self.assertEqual(got, brute(self.m, self.f, p))
        last, x, brk, ok = S.days(self.m, self.f, P)
        arms = {'follow': 0, 'fade': 0}
        for i, side in S.picks(x, brk, ok, P):
            arms['follow' if side == brk[i] else 'fade'] += 1
        self.assertGreater(arms['follow'], 3)
        self.assertGreater(arms['fade'], 3)

    def test_signal_fields(self):
        for s in S.signals(self.m, self.f, P):
            self.assertEqual((self.m.t[s.sig] + 60) % 86400, 0)
            self.assertIsNone(s.target)
            self.assertGreaterEqual(s.stop, 0.015 * self.m.c[s.sig] - 1e-9)
        self.assertEqual(S.signals(E.Market('SOLUSDT', self.m.bars), self.f, P), [])

    def test_missing_dvol_and_bad_days(self):
        last, x, brk, ok = S.days(self.m, self.f, P)
        i = 200
        T = int((self.m.t[last[i]] // 86400 + 1) * 86400)
        f2 = Feats(drop=(T - 3600, T - 7200, T - 10800))            # rows usable at T, T-1h, T-2h gone; next is 3h old
        _, _, _, ok2 = S.days(self.m, f2, P)
        self.assertTrue(ok[i] and not ok2[i])
        k = int(last[i]) - 500
        zero = np.zeros(self.m.n, bool)
        zero[k:k + 3] = True
        _, _, _, ok3 = S.days(market(zero=zero), self.f, P)
        self.assertFalse(ok3[i])                                    # stale day itself
        self.assertFalse(ok3[i + 30])                               # still inside the next days' 30-day window
        self.assertTrue(ok3[i + 31] == ok[i + 31])
        m4 = market(drop=[k])
        self.assertEqual([(s.sig, s.side) for s in S.signals(m4, f2, P)], brute(m4, f2, P))

    def test_truncation_invariant(self):
        cut = pd.Timestamp(T0 + 300 * 86400 + 13 * 3600 + 47 * 60, unit='s', tz='UTC')

        def fake_load(blk, sym, w):
            keep = self.m.bars[self.m.bars['time'] < int(blk.end.timestamp())].reset_index(drop=True)
            return E.Market(sym, keep), Feats(hi=int(blk.end.timestamp())), 0
        blk = K.Block('train', pd.Timestamp(T0, unit='s', tz='UTC'), pd.Timestamp(T0 + 329 * 86400, unit='s', tz='UTC'), Path('.'))
        full = S.signals(self.m, self.f, P)
        with mock.patch.object(K, 'load_market', fake_load), mock.patch.object(K, 'TRUNC_CUTS', (cut,)):
            res = K.truncation_check(S, P, 'BTCUSDT', blk, 0, self.m, full)
        self.assertTrue(res['ok'] and res['before_cut'] > 5, res)

    def test_source_allowed(self):
        K.check_source(Path(S.__file__).read_text(), 'k4_dvol_regime.py')


if __name__ == '__main__':
    unittest.main()
