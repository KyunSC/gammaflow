"""Controller tests (not frozen; kept outside tests/ because the manifest pins tests/*.py).

    cd functions/ml && ../../.venv/bin/python -B -m unittest research_loop_crypto/test_controller.py
"""
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller as K  # noqa: E402
from eval import engine as E  # noqa: E402
from eval import manifest as M  # noqa: E402

T0 = int(pd.Timestamp('2022-03-20', tz='UTC').timestamp())


def walk(n=40 * 1440, seed=0, t0=T0, vol=6e-4, sym='BTCUSDT'):
    rng = np.random.default_rng(seed)
    c = 30_000 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    df = pd.DataFrame(dict(time=t0 + 60 * np.arange(n), open=o, high=hi, low=lo, close=c, volume=np.ones(n)))
    return E.Market(sym, df)


def daily_sigs(m, peek=False):
    out = []
    for a in range(30, m.n - 1, 1440):   # no dependence on m.n beyond the decision bar (truncation-invariant)
        side = (1 if a + 1440 < m.n else -1) if peek else 1   # peek: "does a day of future data exist"
        d = 0.02 * m.c[a]
        out.append(E.Signal(a, side, d, d, E.end_by_time(m, a, 86400)))
    return out


class Pure(unittest.TestCase):
    def test_configs_and_run_key(self):
        g = {'base': {'a': 1}, 'axes': {'s': [1, 2, 3]}}
        self.assertEqual(K.configs(g), [{'a': 1, 's': 1}, {'a': 1, 's': 2}, {'a': 1, 's': 3}])
        self.assertEqual(K.configs({'base': {'a': 1}}), [{'a': 1}])
        keys = {K.run_key('x', 0, 'train', 'd', 's', 'p'), K.run_key('x', 1, 'train', 'd', 's', 'p'),
                K.run_key('x', 0, 'validation', 'd', 's', 'p'), K.run_key('x', 0, 'train', 'e', 's', 'p'),
                K.run_key('x', 0, 'train', 'd', 't', 'p'), K.run_key('x', 0, 'train', 'd', 's', 'q')}
        self.assertEqual(len(keys), 6)

    def test_forbidden_source(self):
        for bad in ('from eval.blocks import open_block', 'Block("train", a, b, r)', 'open("x")', 'import os.path',
                    'pd.read_parquet(f)', 'import requests', 'blk._read("klines-1m", s)', 'C.TEST_START'):
            with self.assertRaises(K.Refused, msg=bad):
                K.check_source(bad, 'x.py')
        K.check_source('import numpy as np\nfrom eval.engine import Signal\nfeats.metrics("BTCUSDT")\n', 'ok.py')

    def test_spent_conflicts_only_crypto_rows(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 's.json'
            p.write_text(json.dumps({'rows': [
                dict(study='a', market=['ES'], kind='one_look', families=['orb'], start='2011-01-01', end='2026-01-01'),
                dict(study='b', market=['BTC', 'ETH'], kind='one_look', families=['choch'], start='2020-01-01', end='2024-06-30'),
                dict(study='c', market=['BTC'], kind='discovery', families=['oi'], start='2020-01-01', end='2024-06-30')]}))
            self.assertFalse(K.spent_conflicts(['orb'], 'train', p))
            self.assertTrue(K.spent_conflicts(['choch'], 'train', p))
            self.assertFalse(K.spent_conflicts(['choch'], 'validation', p))
            self.assertFalse(K.spent_conflicts(['oi'], 'train', p))


def row(cid, k, block, ok=True, s='s', p='p'):
    return dict(kind='candidate', id=cid, k=k, block=block, status='ok', strategy_sha256=s, prereg_sha256=p, run_key=f'{cid}{k}{block}',
                **{'pass': ok})


class PlanRun(unittest.TestCase):
    spec = {'grid': {'base': {}, 'axes': {'a': [1, 2]}}}

    def plan(self, block, rows=(), spec=None, state=None, looks=0, s='s', p='p', cid='x'):
        return K.plan_run(cid, block, spec or self.spec, s, p, list(rows), state or {}, looks)

    def test_refusals(self):
        with self.assertRaises(K.Refused):
            self.plan('test')
        with self.assertRaises(K.Refused):
            self.plan('train', spec={'grid': {'axes': {'a': [1, 2, 3, 4]}}})
        with self.assertRaises(K.Refused):   # changed strategy after its train row
            self.plan('train', rows=[row('x', 0, 'train')], s='other')
        with self.assertRaises(K.Refused):   # budget: 9 used + 2 new > 10
            self.plan('train', rows=[row(f'o{i}', 0, 'train') for i in range(9)])
        with self.assertRaises(K.Refused):   # no train pass
            self.plan('validation', rows=[row('x', 0, 'train', ok=False), row('x', 1, 'train', ok=False)])
        with self.assertRaises(K.Refused):   # 6th look
            self.plan('validation', rows=[row('x', 0, 'train')], looks=5)
        with self.assertRaises(K.Refused):   # already has its validation row
            self.plan('validation', rows=[row('x', 0, 'train'), row('x', 0, 'validation')])
        with self.assertRaises(K.Refused):   # K0 without approval, and never on train
            self.plan('validation', spec={**self.spec, 'k0': True}, state={'c4_approval': 'PENDING'})
        with self.assertRaises(K.Refused):
            self.plan('train', spec={**self.spec, 'k0': True}, state={'c4_approval': 'YES'})

    def test_resume_and_k(self):
        self.assertEqual(self.plan('train', rows=[row('x', 0, 'train')]), ([1], 1))
        todo, k = self.plan('validation', rows=[row('x', 0, 'train'), row('x', 1, 'train', ok=False), row('y', 0, 'train')])
        self.assertEqual((todo, k), ([0], 2))
        self.assertEqual(self.plan('validation', spec={**self.spec, 'k0': True}, state={'c4_approval': 'YES'})[0], [0, 1])

    def test_user_override_of_failed_train(self):
        failed = [row('x', 0, 'train', ok=False), row('x', 1, 'train', ok=False)]
        ov = {'approved_by': 'user', 'train_failed_ack': True, 'configs': [0, 1], 'K': 2}
        self.assertEqual(self.plan('validation', rows=failed, state={'validation_overrides': {'x': ov}}), ([0, 1], 2))
        with self.assertRaises(K.Refused):   # override for another id does not apply
            self.plan('validation', rows=failed, state={'validation_overrides': {'y': ov}})
        with self.assertRaises(K.Refused):   # needs the explicit acknowledgement
            self.plan('validation', rows=failed, state={'validation_overrides': {'x': {**ov, 'train_failed_ack': False}}})
        with self.assertRaises(K.Refused):   # every config must have been run on train
            self.plan('validation', rows=failed[:1], state={'validation_overrides': {'x': ov}})
        with self.assertRaises(K.Refused):   # still one row per config, and still the look limit
            self.plan('validation', rows=failed + [row('x', 0, 'validation'), row('x', 1, 'validation')],
                      state={'validation_overrides': {'x': ov}})
        with self.assertRaises(K.Refused):
            self.plan('validation', rows=failed, state={'validation_overrides': {'x': ov}}, looks=5)


class Floors(unittest.TestCase):
    def test_sol_warmup_never_reaches_its_gappy_months(self):
        self.assertEqual(K.data_floor('SOLUSDT'), K.SOL_TRAIN_START)
        self.assertLess(K.data_floor('BTCUSDT'), K.SOL_TRAIN_START)
        sb = K.symbol_block(K.Block('train', pd.Timestamp('2020-01-01', tz='UTC'), pd.Timestamp('2024-07-01', tz='UTC'), Path('.')), 'SOLUSDT')
        self.assertEqual(sb.start, K.SOL_TRAIN_START)
        w = int(max(0, min(90, (sb.start - K.data_floor('SOLUSDT')).days)))
        self.assertEqual(w, 0)


class Views(unittest.TestCase):
    def test_exec_view_drops_warmup_signals_and_shifts(self):
        m = walk(n=5 * 1440)
        off = 2 * 1440
        sigs = [E.Signal(100, 1, 50.0, 50.0, 400), E.Signal(off + 10, -1, 60.0, None, off + 900)]
        mx, ex = K.exec_view(m, off, sigs)
        self.assertEqual(mx.n, m.n - off)
        self.assertEqual(len(ex), 1)
        self.assertEqual((ex[0].sig, ex[0].end, ex[0].side), (10, 900, -1))
        self.assertEqual(mx.t[ex[0].sig], m.t[off + 10])

    def test_truncation_check_catches_a_peek(self):
        full = walk()
        cut = pd.Timestamp('2022-04-02', tz='UTC')

        def fake_load(blk, sym, w):
            keep = full.bars[full.bars['time'] < int(blk.end.timestamp())].reset_index(drop=True)
            return E.Market(sym, keep), None, 0

        class Mod:
            peek = False

            def signals(self, m, f, p):
                return daily_sigs(m, self.peek)
        blk = K.Block('train', pd.Timestamp(T0, unit='s', tz='UTC'), cut + pd.Timedelta(days=20), Path('.'))
        with mock.patch.object(K, 'load_market', fake_load), mock.patch.object(K, 'TRUNC_CUTS', (cut,)):
            honest = Mod()
            r = K.truncation_check(honest, {}, 'BTCUSDT', blk, 0, full, honest.signals(full, None, {}))
            self.assertTrue(r['ok'] and r['before_cut'] > 0, r)
            cheat = Mod()
            cheat.peek = True
            r = K.truncation_check(cheat, {}, 'BTCUSDT', blk, 0, full, cheat.signals(full, None, {}))
            self.assertFalse(r['ok'], r)


class Measure(unittest.TestCase):
    def test_random_is_about_minus_cost_and_flat_is_empty(self):
        m = walk(n=400 * 1440, vol=4e-4)
        x = K.measure(m, E.run_book(m, daily_sigs(m)), ev=False)
        self.assertGreater(x['trades'], 300)
        lo, hi = x['gross_ci_session']
        self.assertLess(lo, 0)
        self.assertGreater(hi, 0)
        self.assertAlmostEqual(x['mean_r'] - x['gross_r'], -np.mean([t.legs[1].costs for t in E.run_book(m, daily_sigs(m))]) / E.RISK_USD, 2)
        self.assertAlmostEqual(x['median_stop_pct'], 2.0, 6)
        self.assertEqual(K.measure(m, [], ev=False)['trades'], 0)
        fails = K.gate(x, 'train')
        self.assertIn('EV not computed', fails)
        self.assertEqual(K.gate({'trades': 0}, 'train'), ['no trades'])


class KillResume(unittest.TestCase):
    """A run killed mid-way leaves no row; reruns add each config exactly once."""

    def test_kill_then_resume(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'prereg').mkdir()
            (d / 'strategies').mkdir()
            (d / 'prereg' / 'x.json').write_text(json.dumps({'grid': {'axes': {'a': [1, 2]}}, 'family': ['f']}))
            (d / 'strategies' / 'x.py').write_text('def signals(m, feats, params):\n    return []\n')
            (d / 'state.json').write_text(json.dumps({'freeze': {'digest': 'd'}}))
            m = walk(n=3 * 1440)
            calls = {'n': 0, 'die_at': 3}

            def fake_measure(m, trades, ev, workers=3):
                calls['n'] += 1
                if calls['n'] == calls['die_at']:
                    raise KeyboardInterrupt('killed')
                return {'trades': 0}

            @contextlib.contextmanager
            def fake_open(name, **kw):
                yield K.Block(name, pd.Timestamp(T0, unit='s', tz='UTC'), pd.Timestamp('2022-03-23', tz='UTC'), d)
            patches = [mock.patch.object(K, n, v) for n, v in dict(
                LEDGER=d / 'ledger.jsonl', PREREG=d / 'prereg', STRATS=d / 'strategies', STATE=d / 'state.json',
                RUNS=d / 'runs', verify_eval=lambda: 'd', open_block=fake_open, looks=lambda: [],
                spent_conflicts=lambda f, b: [], load_market=lambda b, s, w: (m, None, 0), measure=fake_measure,
                truncation_check=lambda *a: {'checked': False}).items()]
            for p in patches:
                p.start()
            try:
                with self.assertRaises(KeyboardInterrupt):
                    K.cmd_run('x', 'train')
                self.assertEqual(K.ledger_rows(), [])
                calls['die_at'] = -1
                self.assertEqual(K.cmd_run('x', 'train'), 0)
                self.assertEqual(K.cmd_run('x', 'train'), 0)
                rows = K.ledger_rows()
                self.assertEqual(sorted(r['k'] for r in rows), [0, 1])
                self.assertEqual(len({r['run_key'] for r in rows}), 2)
                self.assertTrue(all(not r['pass'] for r in rows))
            finally:
                for p in patches:
                    p.stop()


class OneByte(unittest.TestCase):
    def test_one_byte_change_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            files = [d / 'a.py', d / 'b.json']
            files[0].write_text('x = 1\n')
            files[1].write_text('{}')
            man = d / 'MANIFEST.sha256'
            digest = M.write(man, files, root=d, env=False)
            self.assertEqual(M.verify(man, files, root=d, expect_digest=digest, env=False), digest)
            files[0].write_text('x = 2\n')
            with self.assertRaises(M.HashMismatch):
                M.verify(man, files, root=d, expect_digest=digest, env=False)

    def test_controller_refuses_a_wrong_pinned_digest(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / 'state.json'
            st.write_text(json.dumps({'freeze': {'digest': '0' * 64}}))
            with mock.patch.object(K, 'STATE', st):
                with self.assertRaises(K.Refused):
                    K.verify_eval()
            st.write_text('{}')
            with mock.patch.object(K, 'STATE', st):
                with self.assertRaises(K.Refused):
                    K.verify_eval()


if __name__ == '__main__':
    unittest.main()
