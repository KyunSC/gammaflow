"""F6 mechanism check (report only, not traded): 60-minute return INTO each qualifying print, signed by -side
(positive = price drifted against the crowded side before the print, as the mechanism needs). Also the 4h return after
entry signed by side (gross direction, no costs) for reference."""
import json
import sys
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import numpy as np  # noqa: E402
import controller as K  # noqa: E402
from eval.blocks import open_block  # noqa: E402

print('digest', K.verify_eval()[:8])
spec, path, s_sha, p_sha = K._load_candidate('F6_funding_print')
mod = K.load_strategy(path)
res = {}
with open_block('train', purpose='free-data loop (research_loop_free/crypto): F6 mechanism check (pre-print drift; report only)',
                spec_hashes=[p_sha[:16]]) as blk:
    for sym in K.GATE_SYMBOLS:
        m, feats, off = K.load_market(K.symbol_block(blk, sym), sym, mod.WARMUP_DAYS)
        res[sym] = {}
        for cfg in K.configs(spec['grid']):
            pre, post = [], []
            for x in mod.signals(m, feats, cfg):
                if x.sig < off or x.sig < 60:
                    continue
                a = x.sig - 60
                if m.t[x.sig] - m.t[a] != 3600:
                    continue
                pre.append(-x.side * (m.c[x.sig - 1] / m.o[a] - 1) * 1e4)
                post.append(x.side * (m.c[x.end] / m.o[x.sig + 1] - 1) * 1e4)
            pre, post = np.array(pre), np.array(post)
            res[sym][cfg['q']] = dict(n=len(pre), pre_bps_mean=round(float(pre.mean()), 2),
                                      pre_bps_se=round(float(pre.std(ddof=1) / np.sqrt(len(pre))), 2),
                                      post4h_bps_mean=round(float(post.mean()), 2))
print(json.dumps(res, indent=1))
