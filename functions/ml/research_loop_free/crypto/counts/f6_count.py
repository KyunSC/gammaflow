"""F6 count-only check: signals() per asset and q on train (no execution, no outcomes)."""
import json
import sys
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import controller as K  # noqa: E402
from eval.blocks import open_block  # noqa: E402

print('digest', K.verify_eval()[:8])
spec, path, s_sha, p_sha = K._load_candidate('F6_funding_print')
mod = K.load_strategy(path)
with open_block('train', purpose='free-data loop (research_loop_free/crypto): F6 funding print COUNT-ONLY check (signals only; no outcomes)',
                spec_hashes=[p_sha[:16]]) as blk:
    for sym in K.GATE_SYMBOLS:
        m, feats, off = K.load_market(K.symbol_block(blk, sym), sym, mod.WARMUP_DAYS)
        out = {}
        for cfg in K.configs(spec['grid']):
            s = [x for x in mod.signals(m, feats, cfg) if x.sig >= off]
            out[cfg['q']] = (len(s), sum(x.side == 1 for x in s))
        print(sym, json.dumps({str(k): v for k, v in out.items()}))
