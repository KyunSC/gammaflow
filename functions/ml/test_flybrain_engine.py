import unittest
import numpy as np
import pandas as pd
from flybrain.engine import backtest, exit_rule

class EngineTests(unittest.TestCase):
    def test_fills_costs_extremes_and_session_flat(self):
        df=pd.DataFrame(dict(date=pd.to_datetime(['2024-01-02T14:30Z','2024-01-02T14:35Z','2024-01-02T14:40Z','2024-01-03T14:30Z','2024-01-03T14:35Z']),
            session=[0,0,0,1,1],open=[100,101,102,104,105],high=[101,103,104,105,107],low=[99,100,101,103,104],close=[100,102,103,104,106]))
        r=backtest(df,[1,0,1,-1,0],'QQQ',10,n_contracts=2)
        t=r.trades[0]
        self.assertEqual(t['entry_idx'],1)
        self.assertAlmostEqual(t['entry_price'],101*41.2+.25)
        self.assertAlmostEqual(t['pnl'],(103-101)*41.2*2*2 - 2*(.5*2+.25*2*2))
        self.assertEqual(t['exit_idx'],2)
        self.assertEqual(r.position[2],0); self.assertEqual(r.position[-1],0)
        self.assertTrue(np.all(r.bar_lo<=r.equity)); self.assertTrue(np.all(r.bar_hi>=r.equity))
        self.assertAlmostEqual(r.bar_open[1],50000-2.)
        self.assertEqual(len(r.trades),2)
        self.assertEqual(r.trades[1]['side'],-1)

    def bars(self, rows, sessions=None):
        """rows of (open, high, low, close) in ETF points, ATR 1, five-minute bars."""
        o,h,l,c=map(list,zip(*rows)); n=len(rows)
        sessions=sessions or [0]*n
        date=pd.Timestamp('2024-01-02T14:30Z')+pd.to_timedelta([5*i+1440*s for i,s in enumerate(sessions)],unit='min')
        return pd.DataFrame(dict(date=date,session=sessions,open=o,high=h,low=l,close=c,atr_14=1.))

    def bracket_trade(self, third_bar, rr=2.):
        df=self.bars([(100,100.2,99.8,100),(100,101,99.5,100.5),third_bar,(101,101,101,101),(101,101,101,101)])
        r=backtest(df,[1,0,0,0,0],'QQQ',1,exits=exit_rule(dict(rr=rr,stop_atr=1.)))
        self.assertEqual(len(r.trades),1)
        return r.trades[0]

    def test_bracket_target_holds_past_max_hold(self):
        t=self.bracket_trade((100.5,102.5,100,102))
        self.assertAlmostEqual(t['raw_exit_price'],102.); self.assertEqual(t['hold'],2)
        self.assertAlmostEqual(t['pnl'],(102-100)*41.2*4-2*(.25*4+1.))

    def test_bracket_bar_touching_both_fills_stop(self):
        self.assertAlmostEqual(self.bracket_trade((100.5,102.5,98.5,102))['raw_exit_price'],99.)

    def test_bracket_gap_through_stop_fills_open(self):
        self.assertAlmostEqual(self.bracket_trade((98,98.5,97,98))['raw_exit_price'],98.)

    def test_bracket_without_a_hit_exits_at_session_close(self):
        t=self.bracket_trade((100.5,101.5,99.5,101))
        self.assertEqual(t['exit_idx'],4); self.assertAlmostEqual(t['raw_exit_price'],101.)

    def test_lucid_daily_loss_limit_flattens_and_blocks_the_session(self):
        flat=(100,100,100,100)
        df=self.bars([flat,flat,(100,100,90,91),flat,flat,flat,flat,flat],sessions=[0,0,0,0,0,1,1,1])
        r=backtest(df,[1]*8,'QQQ',100,exits=exit_rule(dict(lucid_dll=True)))
        first=r.trades[0]
        # Equity hits start - $1,200 at the floor; the exit then pays its slippage and commission.
        self.assertAlmostEqual(first['raw_exit_price'],(100*41.2+.25-299.75)/41.2)
        self.assertAlmostEqual(first['pnl'],-1202.)
        self.assertEqual(first['exit_idx'],2)
        # No more entries that session; the next session trades again.
        self.assertEqual([t['entry_idx'] for t in r.trades],[1,6])

    def test_plain_exit_unchanged_by_disabled_options(self):
        df=self.bars([(100,101,99,100),(100,102,99,101),(101,103,100,102),(102,104,101,103)])
        a=backtest(df,[1,0,-1,0],'QQQ',1); b=backtest(df,[1,0,-1,0],'QQQ',1,exits=exit_rule(dict(rr=0,lucid_dll=False)))
        self.assertEqual(a.trades,b.trades); np.testing.assert_array_equal(a.equity,b.equity)

if __name__ == '__main__': unittest.main()
