"""G2 against-the-mechanism split (report only, prereg): the gated train trades, split by whether the prior 24h
return sign agrees with sign(z) (= -side). Reads the controller's trade files; outcomes are already recorded."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import numpy as np  # noqa: E402
import controller as K  # noqa: E402
from eval.blocks import open_block  # noqa: E402

print('digest', K.verify_eval()[:8])
spec, path, s_sha, p_sha = K._load_candidate('G2_toptrader_fade')
mod = K.load_strategy(path)
ks = [int(k) for k in sys.argv[1:]]
res = {}
with open_block('train', purpose='free-data loop (research_loop_free/b2/crypto): G2 24h-return agreement split (report only)',
                spec_hashes=[p_sha[:16]]) as blk:
    for sym in K.GATE_SYMBOLS:
        m, feats, off = K.load_market(K.symbol_block(blk, sym), sym, mod.WARMUP_DAYS)
        res[sym] = {}
        for k in ks:
            tr = json.loads((K.RUNS / 'G2_toptrader_fade' / f'train_{k}_{sym}.json').read_text())['trades']
            g = {'agree': [], 'disagree': [], 'flat_or_gap': []}
            for t in tr:
                te = int(datetime.fromisoformat(t['entry'].replace('Z', '+00:00')).replace(tzinfo=timezone.utc).timestamp())
                s = int(np.searchsorted(m.t, te)) - 1            # decision bar = entry - 1
                a = int(np.searchsorted(m.t, m.t[s] - 86400))
                if a >= s or m.t[s] - m.t[a] != 86400:
                    g['flat_or_gap'].append(t['r'])
                    continue
                r24 = m.c[s] / m.c[a] - 1
                sz = -t['side']
                g['agree' if np.sign(r24) == sz else ('disagree' if r24 != 0 else 'flat_or_gap')].append(t['r'])
            res[sym][f"Z={K.configs(spec['grid'])[k]['Z']}"] = {
                n: dict(n=len(v), mean_net_r=round(float(np.mean(v)), 3) if v else None) for n, v in g.items()}
print(json.dumps(res, indent=1))
