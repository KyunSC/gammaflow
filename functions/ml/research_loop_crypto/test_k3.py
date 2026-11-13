"""K3 strategy tests on synthetic data only (no train data is read).

    cd functions/ml/research_loop_crypto && ../../../.venv/bin/python -B -m unittest test_k3.py
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
from strategies import k3_taker_flow as S  # noqa: E402

T0 = int(pd.Timestamp('2022-01-01', tz='UTC').timestamp())
P = dict(lookback=720, min_hist=480, prem_cap=1.0, stop_atr=1.0, min_stop_pct=1.5, hold_h=12, Z=2.0)


def market(days=60, seed=0, vol=8e-4, zero=None, drop=None):
    rng = np.random.default_rng(seed)
    n = days * 1440
    c = 40_000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = rng.uniform(50, 150, n)
    hour = np.arange(n) // 60
    tilt = rng.normal(0, 0.08, hour.max() + 1)[hour] + rng.standard_t(3, hour.max() + 1)[hour] * 0.03
    tb = v * np.clip(0.5 + tilt + rng.normal(0, 0.05, n), 0, 1)
    if zero is not None:
        v[zero], tb[zero] = 0, 0
    df = pd.DataFrame(dict(time=T0 + 60 * np.arange(n), open=o, high=hi, low=lo, close=c, volume=v, taker_buy_volume=tb))
    if drop is not None:
        df = df.drop(index=drop).reset_index(drop=True)
    return E.Market('BTCUSDT', df)


class Feats:
    def __init__(self, days=60, seed=5, drop=(), hi=None):
        rng = np.random.default_rng(seed)
        t = np.arange(T0, T0 + days * 86400, 60, dtype=np.int64)
        cl = np.repeat(rng.normal(1e-4, 3e-4, days * 24), 60) + rng.normal(0, 5e-5, len(t))
        keep = ~np.isin(t, list(drop))
        if hi is not None:
            keep &= t < hi
        t, cl = t[keep], cl[keep]
        self._p = Series(t, t + 60, dict(open=cl, high=cl, low=cl, close=cl))

    def pmi(self, kind, sym):
        return self._p


def brute(m, f, p):
    """Independent reference: per hour by timestamp lookups."""
    b = m.bars.set_index('time')
    pr = pd.Series(f._p.values['close'], index=f._p.stamp)
    idx = pd.Series(np.arange(m.n), index=m.t)
    hf, hp, out = [], [], []
    for h in range(T0, int(m.t[-1]) + 1, 3600):
        mins = list(range(h, h + 3600, 60))
        if not all(x in b.index for x in mins):
            continue
        ii = idx[mins].to_numpy()
        if m.stale[ii].any():
            continue
        vol, tb = b.loc[mins, 'volume'].sum(), b.loc[mins, 'taker_buy_volume'].sum()
        if not vol > 0:
            continue
        pm = pr[(pr.index >= h) & (pr.index < h + 3600)]
        if len(pm) < 50:
            continue
        imb, prem = (2 * tb - vol) / vol, pm.mean()
        if len(hf) >= p['min_hist']:
            F, Q = np.array(hf[-p['lookback']:]), np.array(hp[-p['lookback']:])
            zf = (imb - F.mean()) / F.std(ddof=1)
            zp = (prem - Q.mean()) / Q.std(ddof=1)
            side = 1 if zf > 0 else -1
            if abs(zf) >= p['Z'] and side * zp < p['prem_cap']:
                out.append((int(idx[h + 3540]), side))
        hf.append(imb)
        hp.append(prem)
    return out


class K3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.f = market(), Feats()

    def test_matches_brute_force(self):
        for Z in (2.0, 3.0):
            p = {**P, 'Z': Z}
            got = [(s.sig, s.side) for s in S.signals(self.m, self.f, p)]
            self.assertEqual(got, brute(self.m, self.f, p))
        self.assertGreater(len(S.signals(self.m, self.f, P)), len(S.signals(self.m, self.f, {**P, 'Z': 3.0})))
        self.assertGreater(len(S.signals(self.m, self.f, {**P, 'Z': 3.0})), 3)

    def test_premium_filter_removes_signals(self):
        a = S.signals(self.m, self.f, P)
        b = S.signals(self.m, self.f, {**P, 'prem_cap': 99.0})
        self.assertLessEqual(len(a), len(b))
        self.assertTrue({(s.sig, s.side) for s in a} <= {(s.sig, s.side) for s in b})

    def test_signal_fields(self):
        for s in S.signals(self.m, self.f, P):
            self.assertEqual((self.m.t[s.sig] + 60) % 3600, 0)
            self.assertIsNone(s.target)
            self.assertGreaterEqual(s.stop, 0.015 * self.m.c[s.sig] - 1e-9)

    def test_holes_and_missing_premium(self):
        start, _, _, ok = S.hours(self.m, self.f)
        i = 700
        h = int(start[i])
        f2 = Feats(drop=tuple(range(h, h + 11 * 60, 60)))      # 11 missing -> 49 rows
        _, _, _, ok2 = S.hours(self.m, f2)
        self.assertTrue(ok[i] and not ok2[i])
        zero = np.zeros(self.m.n, bool)
        k = int(np.searchsorted(self.m.t, h + 600))
        zero[k:k + 3] = True
        m3 = market(zero=zero)
        _, _, _, ok3 = S.hours(m3, self.f)
        self.assertFalse(ok3[i])
        m4 = market(drop=[k])
        s4, _, _, ok4 = S.hours(m4, self.f)
        self.assertFalse(ok4[int(np.flatnonzero(s4 == h)[0])])
        p = {**P, 'Z': 2.0}
        self.assertEqual([(s.sig, s.side) for s in S.signals(m4, f2, p)], brute(m4, f2, p))

    def test_truncation_invariant(self):
        cut = pd.Timestamp(T0 + 40 * 86400 + 13 * 3600 + 47 * 60, unit='s', tz='UTC')

        def fake_load(blk, sym, w):
            keep = self.m.bars[self.m.bars['time'] < int(blk.end.timestamp())].reset_index(drop=True)
            return E.Market(sym, keep), Feats(hi=int(blk.end.timestamp())), 0
        blk = K.Block('train', pd.Timestamp(T0, unit='s', tz='UTC'), pd.Timestamp(T0 + 59 * 86400, unit='s', tz='UTC'), Path('.'))
        full = S.signals(self.m, self.f, P)
        with mock.patch.object(K, 'load_market', fake_load), mock.patch.object(K, 'TRUNC_CUTS', (cut,)):
            res = K.truncation_check(S, P, 'BTCUSDT', blk, 0, self.m, full)
        self.assertTrue(res['ok'] and res['before_cut'] > 5, res)

    def test_source_allowed(self):
        K.check_source(Path(S.__file__).read_text(), 'k3_taker_flow.py')


if __name__ == '__main__':
    unittest.main()
