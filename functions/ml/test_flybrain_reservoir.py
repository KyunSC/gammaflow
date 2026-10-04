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
        b = dan_path(df, x, dict(p, loss_aversion=1., caution=0., cooldown_bars=0))
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

if __name__ == '__main__': unittest.main()
