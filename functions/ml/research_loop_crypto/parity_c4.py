"""Evaluator parity (plan step 3a): the ported evaluator must reproduce MFP's C4 train numbers before it is frozen.

Targets are MFP_TRAIN_RESULTS.md (MFP branch 416dbd4), C4 primary (stop=opposite, m=2):
  BTC 1,148 trades, long share 0.50, cost 0.108R, net +0.082R, twins -0.067R, excess +0.148 [+0.088, +0.205], p 0.0005,
      strategy Elite EV +$1,421
  ETH 1,156 trades, net +0.051R, excess +0.094 [+0.028, +0.160], p 0.002, strategy Elite EV +$526
Parity only: not a research run. If anything misses, stop and log the difference; do not fix either side.

    python -B research_loop_crypto/parity_c4.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval import engine as E  # noqa: E402
from eval.blocks import open_block  # noqa: E402
from eval.config import STATE  # noqa: E402
from strategies.c4 import signals_c4  # noqa: E402

TARGET = {
    'BTCUSDT': dict(trades=1148, long_share=0.50, cost_r=0.108, mean_r=0.082, twin_mean_r=-0.067, excess=0.148,
                    excess_ci=[0.088, 0.205], p=0.0005, ev=1421),
    'ETHUSDT': dict(trades=1156, mean_r=0.051, excess=0.094, excess_ci=[0.028, 0.160], p=0.002, ev=526),
}
TOL = dict(trades=0, long_share=0.005, cost_r=0.0005, mean_r=0.0005, twin_mean_r=0.0005, excess=0.0005, p=0.00025, ev=0.5)


def main() -> int:
    out, ok = {}, True
    with open_block('train', purpose='crypto perp loop: evaluator parity vs MFP C4 primary (BTC+ETH); not a research run',
                    spec_hashes=['422d4919183d40e8']) as blk:
        for sym, tgt in TARGET.items():
            m = E.Market(sym, blk.bars(sym))
            trades = E.run_book(m, signals_c4(m, 'opposite', 2.0))
            rl, rs, dirs = E.mirrors(trades)
            d = E.describe(m, trades)
            t = E.r_test(rl, rs, dirs)
            ev = E.account_ev(E.build_book(m, trades), dirs)['ev']
            got = dict(trades=d['trades'], long_share=d['long_share'], cost_r=d['cost_r'], mean_r=t['mean_r'],
                       twin_mean_r=t['twin_mean_r'], excess=t['excess'], excess_ci=t['excess_ci'], p=t['p'], ev=ev,
                       median_hold_h=d['median_hold_h'], holed=d['holed'])
            rows = {}
            for k, want in tgt.items():
                g = got[k]
                if k == 'excess_ci':
                    hit = all(abs(a - b) <= 0.0005 for a, b in zip(g, want))
                else:
                    hit = abs(g - want) <= TOL[k]
                rows[k] = dict(target=want, got=g, match=bool(hit))
                ok &= bool(hit)
            out[sym] = dict(checks=rows, extra=dict(median_hold_h=got['median_hold_h'], holed=got['holed'],
                                                    bars=m.n, first=E.iso(m.t[0]), last=E.iso(m.t[-1])))
            for k, r in rows.items():
                print(f"{sym} {k:12s} target={r['target']} got={r['got']} {'OK' if r['match'] else 'MISS'}", flush=True)
    out['parity'] = ok
    dest = STATE / 'runs' / 'parity_c4.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, default=float))
    print('PARITY', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
