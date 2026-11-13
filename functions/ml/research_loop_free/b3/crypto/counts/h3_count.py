"""H3 count-only check: signals() per asset and L on train, plus the non-overlapping count (a signal is skipped while
the previous one's ~24h window is open; no outcomes: stops/targets are ignored, so this is an upper bound on overlap)."""
import json
import sys
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import controller as K  # noqa: E402
from eval.blocks import open_block  # noqa: E402

print('digest', K.verify_eval()[:8])
spec, path, s_sha, p_sha = K._load_candidate('H3_crypto_tsmom')
mod = K.load_strategy(path)
with open_block('train', purpose='free-data loop (research_loop_free/b3/crypto): H3 crypto TSMOM COUNT-ONLY check (signals only; no outcomes)',
                spec_hashes=[p_sha[:16]]) as blk:
    for sym in K.GATE_SYMBOLS:
        m, feats, off = K.load_market(K.symbol_block(blk, sym), sym, mod.WARMUP_DAYS)
        out = {}
        for cfg in K.configs(spec['grid']):
            s = sorted((x for x in mod.signals(m, feats, cfg) if x.sig >= off), key=lambda x: x.sig)
            busy, n_nov = -1, 0
            for x in s:
                if x.sig + 1 > busy:
                    n_nov += 1
                    busy = x.end
            out[cfg['L']] = dict(signals=len(s), non_overlapping_max=n_nov)
        print(sym, json.dumps(out))
