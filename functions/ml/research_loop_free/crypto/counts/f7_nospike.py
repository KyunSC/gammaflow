"""F7 report-only control (prereg against_the_mechanism): same rule with vol_mode='no_spike'. Not gated, not in the
budget; measured with the controller's measure() (no EV), mirrored to the shared ledger as kind=report."""
import json
import sys
import time
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
sys.path.append(str(CRY.parents[1]))
import controller as K  # noqa: E402
from eval import engine as E  # noqa: E402
from eval.blocks import open_block  # noqa: E402
from research_loop_free.shared import mirror_run  # noqa: E402

digest = K.verify_eval()
spec, path, s_sha, p_sha = K._load_candidate('F7_liq_cascade_fade')
mod = K.load_strategy(path)
with open_block('train', purpose='free-data loop (research_loop_free/crypto): F7 no-spike control (report only)',
                spec_hashes=[p_sha[:16]]) as blk:
    for sym in K.GATE_SYMBOLS:
        m_full, feats, off = K.load_market(K.symbol_block(blk, sym), sym, mod.WARMUP_DAYS)
        for k, cfg in enumerate(K.configs(spec['grid'])):
            params = {**cfg, 'vol_mode': 'no_spike'}
            m, ex = K.exec_view(m_full, off, mod.signals(m_full, feats, params))
            x = K.measure(m, E.run_book(m, ex), ev=False)
            row = dict(kind='report', id='F7_liq_cascade_fade', k=k, block='train', symbol=sym, params=params,
                       eval_digest=digest, strategy_sha256=s_sha, prereg_sha256=p_sha, ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                       metrics=dict(trades=x['trades'], mean_r=x.get('mean_r'), gross_r=x.get('gross_r'),
                                    cost_r=x['book']['cost_r'] if x.get('trades') else None,
                                    twin_p=x['twins']['p'] if x.get('trades') else None))
            mirror_run(row, K.LOOP_NAME)
            print(sym, cfg['k'], json.dumps(row['metrics'], default=float))
