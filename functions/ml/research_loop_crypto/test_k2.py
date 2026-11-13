"""K2 strategy tests on synthetic data only (no train data is read).

    cd functions/ml/research_loop_crypto && ../../../.venv/bin/python -B -m unittest test_k2.py
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
from strategies import k2_oi_backed as S  # noqa: E402

T0 = int(pd.Timestamp('2022-01-01', tz='UTC').timestamp())
P = dict(lookback=180, min_hist=120, oi_z=0.5, stop_atr=1.0, min_stop_pct=1.5, hold_h=24, k=1.0)


def market(days=80, seed=0, vol=8e-4, zero=None, drop=None):
    rng = np.random.default_rng(seed)
    n = days * 1440
    c = 40_000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    v = np.ones(n)
    if zero is not None:
        v[zero] = 0
    df = pd.DataFrame(dict(time=T0 + 60 * np.arange(n), open=o, high=hi, low=lo, close=c, volume=v))
    if drop is not None:
        df = df.drop(index=drop).reset_index(drop=True)
    return E.Market('BTCUSDT', df)


class Feats:
    """5m OI snapshots (stamp t, usable t+300), a random walk; `nan_at` stamps are missing (zero OI -> NaN)."""

    def __init__(self, days=80, seed=3, nan_at=(), hi=None):
        rng = np.random.default_rng(seed)
        t = np.arange(T0, T0 + days * 86400, 300, dtype=np.int64)
        oi = 80_000 * np.exp(np.cumsum(rng.normal(0, 3e-3, len(t))))
        oi[np.isin(t, list(nan_at))] = np.nan
        if hi is not None:
            oi, t = oi[t < hi], t[t < hi]
        self._oi = Series(t, t + 300, {'sum_open_interest': oi})

    def metrics(self, sym):
        return self._oi


def brute(m, f, p):
    """Independent reference: walk boundaries in time order with pandas lookups."""
    oi = pd.Series(f._oi.values['sum_open_interest'], index=f._oi.stamp)
    bars = pd.Series(np.arange(m.n), index=m.t)
    hr, hd, out = [], [], []
    for T in range(T0 + S.H4, int(m.t[-1]) + 61, S.H4):
        if T - 60 not in bars.index or T - S.H4 - 60 not in bars.index:
            continue
        s, j = int(bars[T - 60]), int(bars[T - S.H4 - 60])
        if s - j != 240 or m.stale[j + 1:s + 1].any():
            continue
        a, b = oi.get(T - 300, np.nan), oi.get(T - S.H4 - 300, np.nan)
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        r, d = np.log(m.c[s] / m.c[j]), np.log(a / b)
        if len(hr) >= p['min_hist']:
            sr, sd = np.std(hr[-p['lookback']:], ddof=1), np.std(hd[-p['lookback']:], ddof=1)
            if abs(r) >= p['k'] * sr and d >= p['oi_z'] * sd:
                out.append((s, 1 if r > 0 else -1))
        hr.append(r)
        hd.append(d)
    return out


class K2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.f = market(), Feats()

    def test_matches_brute_force(self):
        for k in (1.0, 1.5):
            p = {**P, 'k': k}
            got = [(s.sig, s.side) for s in S.signals(self.m, self.f, p)]
            self.assertEqual(got, brute(self.m, self.f, p))
            self.assertGreater(len(got), 10)

    def test_signal_fields(self):
        sigs = S.signals(self.m, self.f, P)
        for s in sigs:
            self.assertEqual((self.m.t[s.sig] + 60) % S.H4, 0)
            self.assertIsNone(s.target)
            self.assertGreaterEqual(s.stop, 0.015 * self.m.c[s.sig] - 1e-9)
        self.assertLess(len(S.signals(self.m, self.f, {**P, 'k': 1.5})), len(sigs))

    def test_missing_oi_and_holes_skip_without_history_update(self):
        s, r, d, ok = S.boundaries(self.m, self.f)
        T = int(self.m.t[s[200]] + 60)
        f2 = Feats(nan_at=(T - 300,))
        _, _, _, ok2 = S.boundaries(self.m, f2)
        self.assertTrue(ok[200] and not ok2[200])
        self.assertEqual(int(ok.sum() - ok2.sum()), 2)          # T as 'now' and T+4h's 'before'
        p = {**P, 'k': 1.0}
        self.assertEqual([(x.sig, x.side) for x in S.signals(self.m, f2, p)], brute(self.m, f2, p))
        # a stale run inside one window, and a missing 1m bar inside another
        zero = np.zeros(self.m.n, bool)
        zero[int(s[300]) - 10:int(s[300]) - 5] = True
        m3 = market(zero=zero)
        _, _, _, ok3 = S.boundaries(m3, self.f)
        self.assertFalse(ok3[300])
        m4 = market(drop=[int(s[310]) - 100])
        s4, _, _, ok4 = S.boundaries(m4, self.f)
        bad = int(np.flatnonzero(m4.t[s4] == self.m.t[s[310]])[0])
        self.assertFalse(ok4[bad])
        self.assertEqual([(x.sig, x.side) for x in S.signals(m4, self.f, p)], brute(m4, self.f, p))

    def test_truncation_invariant(self):
        cut = pd.Timestamp(T0 + 60 * 86400 + 13 * 3600 + 47 * 60, unit='s', tz='UTC')

        def fake_load(blk, sym, w):
            keep = self.m.bars[self.m.bars['time'] < int(blk.end.timestamp())].reset_index(drop=True)
            return E.Market(sym, keep), Feats(hi=int(blk.end.timestamp())), 0
        blk = K.Block('train', pd.Timestamp(T0, unit='s', tz='UTC'), pd.Timestamp(T0 + 79 * 86400, unit='s', tz='UTC'), Path('.'))
        full = S.signals(self.m, self.f, P)
        with mock.patch.object(K, 'load_market', fake_load), mock.patch.object(K, 'TRUNC_CUTS', (cut,)):
            res = K.truncation_check(S, P, 'BTCUSDT', blk, 0, self.m, full)
        self.assertTrue(res['ok'] and res['before_cut'] > 10, res)

    def test_source_allowed(self):
        K.check_source(Path(S.__file__).read_text(), 'k2_oi_backed.py')


if __name__ == '__main__':
    unittest.main()
