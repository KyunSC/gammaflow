"""Evaluator tests (plan, Evaluator section): controls, as-of joins, holes, block guard, Elite replay parity.

    cd functions/ml && ../../.venv/bin/python -B -m unittest discover -s research_loop_free/b2/crypto/tests
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval import config as C  # noqa: E402
from eval import engine as E  # noqa: E402
from eval import features as F  # noqa: E402
from eval import blocks as B  # noqa: E402
from eval.blocks import Block, HoldoutError, check_before_test, open_block  # noqa: E402
from eval import manifest as M  # noqa: E402
from eval.prop import run_prop  # noqa: E402


def walk(n=200_000, seed=0, t0=1_600_000_000, vol=4e-4):
    """Synthetic 1m random walk (no edge anywhere)."""
    rng = np.random.default_rng(seed)
    c = 30_000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    t = t0 - t0 % 86400 + 60 * np.arange(n)
    return pd.DataFrame(dict(time=t, open=o, high=hi, low=lo, close=c, volume=np.full(n, 5.0)))


def every(m, minutes=240, stop=0.015, tgt=0.03, hold_h=8):
    out = []
    for s in range(minutes, m.n - 2, minutes):
        px = m.c[s]
        out.append(E.Signal(s, 1, stop * px, tgt * px, E.end_by_time(m, s, hold_h * 3600)))
    return out


class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = E.Market("BTCUSDT", walk(300_000))
        cls.trades = E.run_book(cls.m, every(cls.m))
        cls.rl, cls.rs, _ = E.mirrors(cls.trades)

    def test_enough_trades(self):
        self.assertGreater(len(self.trades), 300)

    def test_planted_lookahead_passes(self):
        t = E.r_test(self.rl, self.rs, E.lookahead_dirs(self.m, self.trades), n_twins=500)
        self.assertTrue(E.passes(t), t)

    def test_coin_flip_fails(self):
        fails = sum(not E.passes(E.r_test(self.rl, self.rs, E.coin_dirs(len(self.trades), 100 + k), n_twins=300, seed=k))
                    for k in range(20))
        self.assertGreaterEqual(fails, 17)  # ~5% false pass rate expected

    def test_costs_make_random_negative(self):
        t = E.r_test(self.rl, self.rs, E.coin_dirs(len(self.trades), 1), n_twins=200)
        self.assertLess(t['twin_mean_r'], 0)

    def test_entry_is_next_open(self):
        tr = self.trades[0]
        self.assertEqual(tr.entry, tr.sig.sig + 1)


class Holes(unittest.TestCase):
    def test_zero_volume_run_and_gap_flag_trades(self):
        df = walk(20_000, seed=3)
        df.loc[5000:5002, 'volume'] = 0.0          # 3 zero-volume bars = stale hole
        df = df.drop(index=range(9000, 9010)).reset_index(drop=True)  # 10 missing minutes
        m = E.Market('BTCUSDT', df)
        self.assertEqual(int(m.stale.sum()), 3)
        self.assertEqual(len(m.holes()), 1)
        sigs = [E.Signal(4990, 1, 1e9, None, 5100), E.Signal(5200, 1, 1e9, None, 5300), E.Signal(8950, 1, 1e9, None, 9050)]
        held = [t.holed for t in E.run_book(m, sigs)]
        self.assertEqual(held, [True, False, True])

    def test_two_zero_bars_are_not_a_hole(self):
        df = walk(2000, seed=4)
        df.loc[100:101, 'volume'] = 0.0
        self.assertEqual(int(E.Market('BTCUSDT', df).stale.sum()), 0)


class AsOf(unittest.TestCase):
    def test_visibility_boundary(self):
        s = F.Series(np.array([0, 100]), np.array([300, 400]), dict(x=np.array([1.0, 2.0])))
        v, j = s.asof(np.array([299, 300, 399, 400, 10_000]), max_age=np.inf)
        np.testing.assert_array_equal(j, [-1, 0, 0, 1, 1])
        self.assertTrue(math.isnan(v['x'][0]))
        v, j = s.asof(np.array([10_000]), max_age=600)
        self.assertEqual(j[0], -1)

    def test_decision_time_is_bar_close(self):
        np.testing.assert_array_equal(F.decision_times(np.array([0, 60])), [60, 120])

    def test_hourly_needs_complete_hour(self):
        t = np.arange(0, 7200, 60)
        s = F.hourly_from_bars(t, dict(v=np.ones(len(t))))
        v, _ = s.asof(F.decision_times(t), max_age=np.inf)
        self.assertTrue(np.isnan(v['v'][:59]).all())   # bars 0..58 close before 3600
        self.assertEqual(v['v'][59], 60.0)              # bar 59 closes at 3600: hour 0 complete
        self.assertEqual(v['bars'][-1], 60.0)

    def test_max_age_is_required(self):
        s = F.Series(np.array([0]), np.array([60]), dict(x=np.array([1.0])))
        with self.assertRaises(TypeError):
            s.asof(np.array([100]))

    def test_empty_inputs(self):
        e = F.Series(np.zeros(0, np.int64), np.zeros(0, np.int64), dict(x=np.zeros(0)))
        v, j = e.asof(np.array([1, 2]), max_age=60)
        self.assertTrue(np.isnan(v['x']).all() and (j == -1).all())
        h = F.hourly_from_bars(np.zeros(0, np.int64), dict(v=np.zeros(0)))
        self.assertEqual(len(h), 0)

    def test_hourly_counts_stale_bars(self):
        t = np.arange(0, 7200, 60)
        stale = np.zeros(len(t), bool)
        stale[10:40] = True
        v, _ = F.hourly_from_bars(t, dict(v=np.ones(len(t))), stale).asof(np.array([3600, 7200]), max_age=np.inf)
        np.testing.assert_array_equal(v['stale_bars'], [30, 0])
        np.testing.assert_array_equal(v['bars'], [60, 60])

    def test_rejects_test_rows(self):
        with self.assertRaises(HoldoutError):
            F.Series(np.array([F.TEST_S]), np.array([F.TEST_S]), dict(x=np.array([1.0])))


class RealJoins(unittest.TestCase):
    """On one train month: every joined row was published before the decision and the next one was not."""

    @classmethod
    def setUpClass(cls):
        blk = Block('unit-test', pd.Timestamp('2022-03-01', tz='UTC'), pd.Timestamp('2022-04-01', tz='UTC'), C.BINANCE)
        cls.f = F.Features(blk)
        rng = np.random.default_rng(0)
        cls.t_dec = np.sort(rng.integers(cls.f.lo_s + 86400, cls.f.hi_s, 2000)) // 60 * 60

    def check(self, s: F.Series, cadence: int):
        self.assertGreater(len(s), 0)
        self.assertTrue((s.avail - s.stamp == cadence).all())
        _, j = s.asof(self.t_dec, max_age=np.inf)
        ok = j >= 0
        self.assertTrue(ok.mean() > 0.99)
        self.assertTrue((s.avail[j[ok]] <= self.t_dec[ok]).all())
        nxt = np.minimum(j[ok] + 1, len(s) - 1)
        last = j[ok] == len(s) - 1
        self.assertTrue(((s.avail[nxt] > self.t_dec[ok]) | last).all())
        self.assertTrue((s.stamp >= self.f.lo_s).all() and (s.stamp < self.f.hi_s).all())

    def test_metrics(self):
        self.check(self.f.metrics('BTCUSDT'), 300)

    def test_premium_mark_index(self):
        for k in F.PMI:
            with self.subTest(k):
                self.check(self.f.pmi(k, 'BTCUSDT'), 60)

    def test_coinbase(self):
        self.check(self.f.coinbase('BTC-USD'), 300)

    def test_dvol(self):
        self.check(self.f.dvol('BTC'), 3600)

    def test_funding(self):
        self.check(self.f.funding('BTCUSDT'), 0)


class StampMeaning(unittest.TestCase):
    """What each stamp means, measured on one train month against Binance 1m klines (review finding 4): a wrong
    `avail` offset would show up as alignment with the wrong window. Data check only; no strategy statistic."""

    @classmethod
    def setUpClass(cls):
        blk = Block('unit-test', pd.Timestamp('2023-03-01', tz='UTC'), pd.Timestamp('2023-04-01', tz='UTC'), C.BINANCE)
        cls.f = F.Features(blk)
        k = blk.bars('BTCUSDT').set_index('time')
        cls.k = k

    def window(self, stamps, lo, hi, col):
        """Sum of a 1m kline column over [stamp + lo, stamp + hi) for each stamp."""
        cs = np.r_[0.0, np.cumsum(self.k[col].to_numpy())]
        t = self.k.index.to_numpy()
        a = np.searchsorted(t, stamps + lo)
        b = np.searchsorted(t, stamps + hi)
        return cs[b] - cs[a], b - a

    def test_metrics_taker_ratio_covers_the_5m_before_its_stamp(self):
        s = self.f.metrics('BTCUSDT')
        m = s.values['sum_taker_long_short_vol_ratio']
        corr = {}
        for name, lo, hi in (('before', -300, 0), ('after', 0, 300)):
            buy, n = self.window(s.stamp, lo, hi, 'taker_buy_volume')
            vol, _ = self.window(s.stamp, lo, hi, 'volume')
            r = buy / (vol - buy)
            ok = (n == 5) & np.isfinite(m) & np.isfinite(r)
            corr[name] = np.corrcoef(m[ok], r[ok])[0, 1]
        self.assertGreater(corr['before'], 0.99, corr)   # so the row is complete at its stamp; +300 is conservative
        self.assertLess(corr['after'], 0.5, corr)

    def test_coinbase_candle_covers_the_5m_after_its_open(self):
        s = self.f.coinbase('BTC-USD')
        cb = s.values['close'] / s.values['open'] - 1
        close = self.k['close']
        opn = self.k['open']
        corr = {}
        for name, shift in (('same', 0), ('previous', -300)):
            a = opn.reindex(s.stamp + shift).to_numpy()
            b = close.reindex(s.stamp + shift + 240).to_numpy()
            r = b / a - 1
            ok = np.isfinite(r) & np.isfinite(cb)
            corr[name] = np.corrcoef(cb[ok], r[ok])[0, 1]
        self.assertGreater(corr['same'], 0.9, corr)      # so the candle is complete at open + 300
        self.assertLess(corr['previous'], 0.5, corr)

    def test_mark_close_is_the_bar_close(self):
        s = self.f.pmi('mark', 'BTCUSDT')
        kc = self.k['close'].reindex(s.stamp).to_numpy()
        ok = np.isfinite(kc)
        rel = np.abs(s.values['close'][ok] / kc[ok] - 1)
        self.assertLess(np.median(rel), 5e-4)
        rm, rk = np.diff(np.log(s.values['close'][ok])), np.diff(np.log(kc[ok]))
        self.assertGreater(np.corrcoef(rm, rk)[0, 1], 0.9)


class BlockGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.log, self.lock = self.tmp / 'looks.jsonl', self.tmp / '.lock'

    def test_test_block_refused(self):
        with self.assertRaises(HoldoutError):
            with open_block('test', purpose='x', log=self.log, lock=self.lock):
                pass
        self.assertFalse(self.log.exists())

    def test_validation_limit_counts_shared_log(self):
        self.log.write_text(''.join(json.dumps(dict(block='validation', at='x', purpose='mfp')) + '\n' for _ in range(4)))
        with open_block('validation', purpose='fifth', log=self.log, lock=self.lock) as b:
            self.assertEqual(b.end, pd.Timestamp('2025-07-01', tz='UTC'))
        rows = [json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertEqual((len(rows), rows[-1]['loop']), (5, 'crypto_perp'))
        with self.assertRaises(HoldoutError):
            with open_block('validation', purpose='sixth', log=self.log, lock=self.lock):
                pass

    def test_reader_refuses_test_rows(self):
        root = self.tmp / 'um'
        (root / 'klines-1m' / 'BTCUSDT').mkdir(parents=True)
        t = int(C.TEST_START.timestamp())
        pd.DataFrame(dict(time=[t - 60, t], open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)).to_parquet(
            root / 'klines-1m' / 'BTCUSDT' / '2025-07.parquet')
        with self.assertRaises(HoldoutError):  # construction refuses a window past the test start
            Block('x', pd.Timestamp('2025-07-01', tz='UTC'), pd.Timestamp('2025-08-01', tz='UTC'), root)
        # Second layer: even a block that got past construction refuses a row at the test start.
        b = Block('x', pd.Timestamp('2025-07-01', tz='UTC'), pd.Timestamp('2025-07-08', tz='UTC'), root, B._OPEN)
        b.end = pd.Timestamp('2025-08-01', tz='UTC')
        with self.assertRaises(HoldoutError):
            b.bars('BTCUSDT')

    def test_validation_needs_a_logged_open(self):
        with self.assertRaises(HoldoutError):
            Block('validation', pd.Timestamp('2024-07-08', tz='UTC'), pd.Timestamp('2025-07-01', tz='UTC'), C.BINANCE)
        with self.assertRaises(HoldoutError):  # a train window stretched into validation is refused too
            Block('x', pd.Timestamp('2024-06-01', tz='UTC'), pd.Timestamp('2024-07-09', tz='UTC'), C.BINANCE)
        Block('train', pd.Timestamp('2020-01-01', tz='UTC'), pd.Timestamp('2024-07-01', tz='UTC'), C.BINANCE)

    def test_features_refuse_window_past_test(self):
        with self.assertRaises(HoldoutError):
            F.Features(Block('x', pd.Timestamp('2025-06-01', tz='UTC'), pd.Timestamp('2025-08-01', tz='UTC'), C.BINANCE))

    def test_check_before_test(self):
        check_before_test('2025-07-07 23:59')
        with self.assertRaises(HoldoutError):
            check_before_test('2025-07-08')


class Manifest(unittest.TestCase):
    def test_one_byte_missing_and_unpinned_are_refused(self):
        tmp = Path(tempfile.mkdtemp())
        a, b = tmp / 'a.py', tmp / 'b.py'
        a.write_text('x = 1\n')
        b.write_text('y = 2\n')
        man = tmp / 'MANIFEST.sha256'
        d = M.write(man, [a, b], tmp, env=False)
        self.assertEqual(M.verify(man, [a, b], tmp, expect_digest=d, env=False), d)
        a.write_text('x = 2\n')
        with self.assertRaisesRegex(M.HashMismatch, 'changed a.py'):
            M.verify(man, [a, b], tmp, env=False)
        a.write_text('x = 1\n')
        with self.assertRaisesRegex(M.HashMismatch, 'missing b.py'):
            M.verify(man, [a], tmp, env=False)
        c = tmp / 'c.py'
        c.write_text('')
        with self.assertRaisesRegex(M.HashMismatch, 'unpinned c.py'):
            M.verify(man, [a, b, c], tmp, env=False)
        with self.assertRaises(M.HashMismatch):
            M.verify(man, [a, b], tmp, expect_digest='0' * 64, env=False)

    def test_data_files_stop_before_validation_end(self):
        for name, want in (('BTCUSDT-metrics-2025-06-30.zip', True), ('BTCUSDT-metrics-2025-07-01.zip', False),
                           ('BTCUSDT-1m-2025-06.zip', True), ('BTCUSDT-1m-2025-07.zip', False),
                           ('2025-06.parquet', True), ('2025-07.parquet', False), ('2022-02.gappy.parquet', True)):
            self.assertEqual(M._dated_before(Path(name)), want, name)


class PropParity(unittest.TestCase):
    """eval/prop.py replays the frontend's MyFundedPerps rules exactly (fixture exported from perps.js)."""

    def equal(self, a, b, path=''):
        if b is None:
            self.assertTrue(a is None or isinstance(a, (float, int)) and not math.isfinite(a), path)
        elif isinstance(b, dict):
            self.assertEqual(set(a), set(b), path)
            for k in b:
                self.equal(a[k], b[k], path + '/' + k)
        elif isinstance(b, list):
            self.assertEqual(len(a), len(b), path)
            for i, (x, y) in enumerate(zip(a, b)):
                self.equal(x, y, f'{path}/{i}')
        elif isinstance(b, (float, int)) and not isinstance(b, bool):
            self.assertAlmostEqual(a, b, delta=1e-9, msg=path)
        else:
            self.assertEqual(a, b, path)

    def test_mfp_plans(self):
        f = json.loads((C.EVAL / 'fixtures' / 'mfp_parity.json').read_text())
        for c in f['cases']:
            with self.subTest(plan=c['plan']['plan'], path=c['key'], dll=c['plan']['dll']):
                r = f['results'][c['key']]
                out = run_prop(r['result'], r['time'], c['plan'], c['plan']['startBalance'], paths=f['paths'],
                               block_size=f['blockSize'], horizon=f['horizon'], seed=f['seed'], keep_attempts=False)
                self.equal(out, c['output'])


if __name__ == '__main__':
    unittest.main()
