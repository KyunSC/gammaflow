import unittest
import numpy as np
import pandas as pd
from scipy import sparse
from flybrain.connectome import Circuit, matrix_hash
from flybrain.reservoir import run_reservoir
from flybrain.readout import oos_signals, fold_schedule, dan_path


def frame(n=40, bars=8, seed=3):
    rng = np.random.default_rng(seed)
    dates = [d + pd.Timedelta(minutes=5*i) for d in pd.date_range('2023-01-02 14:30', periods=n, freq='B', tz='UTC') for i in range(bars)]
    x = rng.normal(size=n*bars)
    close = 100 + np.cumsum(rng.normal(0, .1, len(x)))
    df = pd.DataFrame(dict(date=dates, session=np.repeat(np.arange(n),bars), open=close-.01, high=close+.1, low=close-.1, close=close, atr_14=1., z_x=x))
    df['session_end'] = df.session.ne(df.session.shift(-1))
    df.attrs['features'] = ['x']
    return df


def params():
    return dict(rho=.8, leak=.6, input_gain=1., kc_sparsity=None, gex_off=False, readout_from='kc', readout='ridge', ridge_lambda=1., threshold_q=.6, horizon_bars=1, dan_lr=.001, seed=4)

class ReservoirTests(unittest.TestCase):
    def circuit(self):
        W = sparse.csr_matrix(np.full((10,10), .1))
        return Circuit(W, {'pn':np.arange(4),'kc':np.arange(4,9),'mbon':np.array([9])}, 'fly', matrix_hash(W))

    def test_batch_and_causality(self):
        c=self.circuit(); p=params()
        x=np.random.default_rng(3).normal(size=(3,6,2)); mask=np.ones((3,6),bool); mask[2,4:]=False
        a=run_reservoir(c,x,mask,p)
        b={k:np.concatenate([run_reservoir(c,x[i:i+1],mask[i:i+1],p)[k] for i in range(3)]) for k in a}
        for k in a: np.testing.assert_allclose(a[k],b[k],atol=1e-10)
        x[1,3]*=100
        b=run_reservoir(c,x,mask,p)
        for k in a:
            np.testing.assert_array_equal(a[k][:9],b[k][:9])
            np.testing.assert_array_equal(a[k][12:],b[k][12:])

    def test_kwta(self):
        p=params(); p['kc_sparsity']=.4
        a=run_reservoir(self.circuit(),np.ones((2,6,2)),np.ones((2,6),bool),p)
        # First step KCs are zero: inputs need one recurrent step to reach them.
        np.testing.assert_array_equal((a['kc'].reshape(2,6,5)[:,1:] > 0).sum(axis=2),2)

    def test_train_only_threshold(self):
        df=frame(); p=params(); df.attrs['fold_schedule']=fold_schedule(df,1)
        x=df[['z_x']].to_numpy(); a=[]
        oos_signals(df,{'kc':x},p,a)
        y=x.copy(); y[a[-1]['test']]*=1000
        b=[]; oos_signals(df,{'kc':y},p,b)
        self.assertEqual(a[-1]['threshold'],b[-1]['threshold'])

    def test_dan_reward_causal(self):
        df=frame(); p=params(); p['readout']='dan'
        x=df[['z_x']].to_numpy()
        a=dan_path(df,x,p)[0]
        df.loc[100:,'close']*=100
        b=dan_path(df,x,p)[0]
        np.testing.assert_array_equal(a[:100],b[:100])

    def test_dan_reinforces_both_sides(self):
        # Constant pattern, steadily falling then rising price: a winning trade in either direction
        # must push w.s further in the direction of the action taken.
        for sign in (-1, 1):
            df = frame(n=6, bars=8); p = params(); p['readout'] = 'dan'; p['dan_lr'] = .1
            df['close'] = 100 + sign * np.arange(len(df)) * .5
            df['open'] = df.close.shift(1).fillna(df.close.iloc[0]); df['atr_14'] = 1.
            x = np.ones((len(df), 1))
            w0 = np.array([sign * .01])
            _, signals, w = dan_path(df, x, p, initial=w0)
            self.assertTrue((signals[signals != 0] == sign).all())
            self.assertGreater(sign * w[0], sign * w0[0])

    def falling(self, n=6, bars=8):
        df = frame(n=n, bars=bars); df['close'] = 100 - np.arange(len(df)) * .5
        df['open'] = df.close.shift(1).fillna(df.close.iloc[0]); df['atr_14'] = 1.
        return df

    def test_loss_aversion_scales_losing_update(self):
        # One session, one long that loses: the weight step is exactly loss_aversion times larger.
        df = self.falling(n=1, bars=8); x = np.ones((len(df), 1)); w0 = np.array([.01])
        step = {}
        for lam in (1., 3.):
            p = dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, loss_aversion=lam)
            _, signals, w = dan_path(df, x, p, initial=w0)
            self.assertEqual(signals[0], 1)
            step[lam] = w[0] - (1 - .0001) * w0[0]
        self.assertLess(step[1.], 0)
        self.assertAlmostEqual(step[3.] / step[1.], 3.)

    def test_loss_aversion_leaves_wins_alone(self):
        df = self.falling(n=1, bars=8); x = np.ones((len(df), 1)); w0 = np.array([-.01])
        out = [dan_path(df, x, dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, loss_aversion=lam), initial=w0)[2]
               for lam in (1., 5.)]
        np.testing.assert_array_equal(out[0], out[1])

    def test_win_reward_scales_winning_update(self):
        # One session, one short that wins: the weight step is exactly win_reward times larger.
        df = self.falling(n=1, bars=8); x = np.ones((len(df), 1)); w0 = np.array([-.01])
        step = {}
        for gain in (1., 3.):
            p = dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, win_reward=gain)
            _, signals, w = dan_path(df, x, p, initial=w0)
            self.assertEqual(signals[0], -1)
            step[gain] = w[0] - (1 - .0001) * w0[0]
        self.assertLess(step[1.], 0)
        self.assertAlmostEqual(step[3.] / step[1.], 3.)

    def test_win_reward_leaves_losses_alone(self):
        df = self.falling(n=1, bars=8); x = np.ones((len(df), 1)); w0 = np.array([.01])
        out = [dan_path(df, x, dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, win_reward=g), initial=w0)[2]
               for g in (1., 5.)]
        np.testing.assert_array_equal(out[0], out[1])

    def test_entry_reward_fires_on_entry(self):
        # One long: entering is one extra learn step (decay w0, add lr * side * entry_reward), decayed again at the close.
        df = self.falling(n=1, bars=8); x = np.ones((len(df), 1)); w0 = np.array([.01])
        out = {}
        for e in (0., 2.):
            _, signals, w = dan_path(df, x, dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, entry_reward=e), initial=w0)
            self.assertEqual(signals[0], 1)
            out[e] = w[0]
        self.assertAlmostEqual(out[2.] - out[0.], (1 - .0001) * (.1 * 2. - .0001 * w0[0]), places=12)
        # Frozen replay never learns, so the entry reward cannot move it.
        fz = (np.array([.01]), .001); base = dict(params(), readout='dan')
        np.testing.assert_array_equal(dan_path(df, x, base, frozen=fz)[1],
                                      dan_path(df, x, dict(base, entry_reward=5.), frozen=fz)[1])

    def ranged(self, df):
        df['high'] = df[['open', 'close']].max(axis=1) + .05; df['low'] = df[['open', 'close']].min(axis=1) - .05
        df.attrs['symbol'] = 'QQQ'
        return df

    def test_bracket_reward_is_the_fill(self):
        # One long, one session: the 0.6-ATR stop fills at 99.4 on bar 2, so the reward is -0.6, not the close's -1.0.
        df = self.ranged(self.falling(n=1, bars=3)); x = np.ones((len(df), 1)); w0 = np.array([.01])
        p = dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, rr=2., stop_atr=.6)
        _, signals, w = dan_path(df, x, p, initial=w0)
        self.assertEqual(signals[0], 1)
        self.assertAlmostEqual(w[0] - (1 - .0001) * w0[0], .1 * -.6)

    def test_daily_loss_limit_stops_learning_for_the_session(self):
        # A growing input keeps the fly long into a steady fall; the DLL ends the session's trading early.
        from flybrain.engine import backtest, exit_rule
        df = self.ranged(self.falling(n=1, bars=60)); x = np.arange(1., 61.).reshape(-1, 1)
        p = dict(params(), readout='dan', dan_lr=1e-7, horizon_bars=1, threshold_q=0.)
        free, s_free, w_free = dan_path(df, x, p, initial=np.array([.01]))
        capped, s_cap, w_cap = dan_path(df, x, dict(p, lucid_dll=True), initial=np.array([.01]))
        self.assertGreater(w_cap[0], w_free[0])
        n_free = len(backtest(df, s_free, 'QQQ', 1).trades)
        n_cap = len(backtest(df, s_cap, 'QQQ', 1, exits=exit_rule(dict(lucid_dll=True))).trades)
        self.assertLess(n_cap, n_free)

    def test_caution_blocks_entries_after_losses(self):
        df = self.falling(); x = np.ones((len(df), 1)); fz = (np.array([.01]), .001)
        base = dict(params(), readout='dan')
        neutral = dan_path(df, x, base, frozen=fz)[1]
        scared = dan_path(df, x, dict(base, caution=1e6), frozen=fz)[1]
        first_loss = np.flatnonzero(neutral)[0] + 1  # signal bar, then the entry bar closes (horizon 1) and realises it
        self.assertGreater(np.count_nonzero(neutral), 3)
        self.assertEqual(np.count_nonzero(scared[first_loss:]), 0)
        np.testing.assert_array_equal(neutral[:first_loss], scared[:first_loss])

    def test_cooldown_after_two_losses(self):
        df = self.falling(n=1, bars=40); x = np.ones((len(df), 1)); fz = (np.array([.01]), .001)
        base = dict(params(), readout='dan')
        neutral = dan_path(df, x, base, frozen=fz)[1]
        cooled = dan_path(df, x, dict(base, cooldown_bars=6), frozen=fz)[1]
        self.assertLess(np.count_nonzero(cooled), np.count_nonzero(neutral))
        second_loss = np.flatnonzero(neutral)[1] + 1
        self.assertEqual(np.count_nonzero(cooled[second_loss:second_loss + 6]), 0)

    def test_risk_gate_causal_and_frozen_replay(self):
        from flybrain.readout import frozen_signals
        df = frame(n=20, bars=8); p = dict(params(), readout='dan', dan_lr=.1, caution=2., cooldown_bars=3, threshold_q=.5)
        x = df[['z_x']].to_numpy()
        a = dan_path(df, x, p)[1]
        df.loc[60:, 'close'] *= 100
        np.testing.assert_array_equal(a[:60], dan_path(df, x, p)[1][:60])
        fitted = dict(coef=np.array([.05]), intercept=0., threshold=.01)
        with self.assertRaises(ValueError):
            frozen_signals({'kc': x}, p, fitted)
        np.testing.assert_array_equal(frozen_signals({'kc': x}, p, fitted, df),
                                      dan_path(df, x, p, frozen=(fitted['coef'], fitted['threshold']))[1])

    def test_loss_averse_defaults_are_neutral(self):
        df = frame(n=20, bars=8); x = df[['z_x']].to_numpy(); p = dict(params(), readout='dan', dan_lr=.1)
        a = dan_path(df, x, p)
        b = dan_path(df, x, dict(p, loss_aversion=1., win_reward=1., entry_reward=0., caution=0., cooldown_bars=0))
        for u, v in zip(a, b): np.testing.assert_array_equal(u, v)

    def test_frozen_dan_trade_fraction(self):
        from flybrain.readout import fit_frozen, frozen_signals
        df=frame(n=60,bars=20); p=dict(params(),readout='dan',threshold_q=.9,dan_lr=.1)
        X=df[['z_x']].to_numpy()
        fitted=fit_frozen(df,{'kc':X},p)
        self.assertAlmostEqual(np.count_nonzero(frozen_signals({'kc':X},p,fitted))/len(df),.1,delta=.002)

    def test_model_cache_keys_training_values(self):
        from unittest.mock import patch
        from flybrain.readout import fit_ridge
        df=frame(); p=params(); df.attrs['fold_schedule']=fold_schedule(df,1)
        X=df[['z_x']].to_numpy(); cache={}
        with patch('flybrain.readout.fit_ridge',wraps=fit_ridge) as fit:
            oos_signals(df,{'kc':X},p,model_cache=cache)
            count=fit.call_count
            oos_signals(df,{'kc':-X},p,model_cache=cache)
            self.assertEqual(fit.call_count,2*count)

    def test_cache_rejects_truncated_files(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from flybrain import config
        from flybrain.reservoir import cached_states
        df = frame(n=4, bars=6); p = params()
        with tempfile.TemporaryDirectory() as d, patch.object(config, 'DATA_DIR', Path(d)):
            a = cached_states(None, df, p)
            expected = np.array(a['kc'])
            target = next(Path(d, 'states').glob('*-kc.npy'))
            target.write_bytes(target.read_bytes()[:60])  # simulate an interrupted write
            b = cached_states(None, df, p)
            np.testing.assert_array_equal(np.array(b['kc']), expected)
            self.assertFalse(list(Path(d, 'states').glob('*.tmp')))

    def rising(self, n=1, bars=40):
        # Every bar opens at the previous close and gains 0.5 ATR: a horizon-1 paper bet always earns +0.5.
        df = frame(n=n, bars=bars); df['close'] = 100 + np.arange(len(df)) * .5
        df['open'] = df.close.shift(1).fillna(df.close.iloc[0] - .5); df['atr_14'] = 1.
        return df

    def test_learning_options_defaults_are_neutral(self):
        df = frame(n=20, bars=8); x = df[['z_x']].to_numpy(); p = dict(params(), readout='dan', dan_lr=.1)
        a = dan_path(df, x, p)
        b = dan_path(df, x, dict(p, shadow=False, dan_rule='hebbian'))
        for u, v in zip(a, b): np.testing.assert_array_equal(u, v)

    def test_paper_bets_causal(self):
        df = frame(); x = df[['z_x']].to_numpy()
        p = dict(params(), readout='dan', dan_lr=.1, horizon_bars=3, shadow=True, dan_rule='delta')
        a = dan_path(df, x, p)[0]
        df.loc[100:, ['open', 'close']] *= 100
        np.testing.assert_array_equal(a[:100], dan_path(df, x, p)[0][:100])

    def test_paper_bets_stay_in_session(self):
        # Horizon longer than a session: every bet is graded at its own session's close, none at a later bar.
        df = frame(n=2, bars=4); x = np.ones((len(df), 1))
        p = dict(params(), readout='dan', dan_lr=.1, horizon_bars=100, shadow=True)
        stats = {}
        a = dan_path(df, x, p, stats=stats)[0]
        self.assertEqual(stats['n'], 6)  # three non-closing bars per session
        df.loc[4:, ['open', 'close']] *= 100
        np.testing.assert_array_equal(a[:5], dan_path(df, x, p)[0][:5])

    def test_paper_bets_learn_while_flat(self):
        df = frame(n=20, bars=8); x = df[['z_x']].to_numpy(); w0 = np.array([.01])
        p = dict(params(), readout='dan', dan_lr=.1, threshold_q=.999, shadow=True, dan_rule='delta')
        stats = {}
        _, signals, w = dan_path(df, x, p, initial=w0, stats=stats)
        self.assertEqual(stats['n'], 20 * 7)
        self.assertLess(np.count_nonzero(signals), 20)
        self.assertNotEqual(w[0], w0[0])

    def test_delta_rule_learns_from_being_wrong(self):
        df = self.rising(); x = np.ones((len(df), 1))
        p = dict(params(), readout='dan', dan_lr=.5, shadow=True, dan_rule='delta')
        stats = {}
        w = dan_path(df, x, p, initial=np.array([-1.]), stats=stats)[2]
        self.assertAlmostEqual(w[0], .5, delta=.01)  # wrong-sign start flips, then settles on the outcome
        self.assertLess(stats['second_half']['mean_abs_err'], stats['first_half']['mean_abs_err'])
        self.assertEqual(stats['second_half']['hit_rate'], 1.)
        # The hebbian rule keeps pushing after it is already right.
        hebb = dan_path(df, x, dict(p, dan_rule='hebbian'), initial=np.array([-1.]))[2]
        self.assertGreater(hebb[0], 5)

    def test_delta_rule_stable_in_high_dimensions(self):
        df = frame(n=10, bars=20); x = np.random.default_rng(1).normal(size=(len(df), 2000))
        p = dict(params(), readout='dan', dan_lr=1., shadow=True, dan_rule='delta')
        self.assertTrue(np.isfinite(dan_path(df, x, p)[0]).all())

    def test_learning_options_reject_ambiguous_settings(self):
        df = frame(n=2, bars=4); x = np.ones((len(df), 1)); p = dict(params(), readout='dan')
        for bad in (dict(loss_aversion=2., dan_rule='delta'), dict(loss_aversion=2., shadow=True), dict(dan_rule='oja'),
                    dict(win_reward=2., dan_rule='delta'), dict(win_reward=2., shadow=True),
                    dict(entry_reward=.5, dan_rule='delta'), dict(entry_reward=.5, shadow=True)):
            with self.assertRaises(ValueError):
                dan_path(df, x, dict(p, **bad))

    def test_oos_signals_reports_paper_bet_learning(self):
        df = frame(); p = dict(params(), readout='dan', shadow=True, dan_rule='delta'); df.attrs['fold_schedule'] = fold_schedule(df, 1)
        diagnostics = []
        oos_signals(df, {'kc': df[['z_x']].to_numpy()}, p, diagnostics)
        self.assertEqual(diagnostics[0]['learning']['n'], 40 * 7)

if __name__ == '__main__': unittest.main()
