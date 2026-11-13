"""F5 count-only check: qualifying weekends per symbol and m, signal inputs only (no prices after Mon 00:00 used)."""
import sys
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import numpy as np
import controller as K
from eval.blocks import open_block
from eval.engine import aggregate

print('digest', K.verify_eval()[:8])
DAY = 86400
with open_block('train', purpose='free-data loop (research_loop_free/crypto): F5 weekend fade COUNT-ONLY check (signal inputs before Mon 00:00 UTC; no outcomes)') as blk:
    for sym in K.GATE_SYMBOLS:
        m, feats, off = K.load_market(K.symbol_block(blk, sym), sym, 40)
        d = aggregate(m, m.t // DAY)
        dday = m.t[d.first] // DAY
        full = (d.last - d.first + 1) == 1440
        idx = {int(t): i for i, t in enumerate(m.t)}
        cnt = {0.5: 0, 1.0: 0, 1.5: 0}; weeks = 0
        t0 = m.t[off]
        for mon in range(int(t0 // DAY), int(m.t[-1] // DAY) + 1):
            if (mon + 3) % 7 != 0:      # 1970-01-01 Thursday -> Monday when (day+3)%7==0
                continue
            weeks += 1
            fri = (mon - 3) * DAY + 21 * 3600
            i_f, i_s = idx.get(fri), idx.get(mon * DAY - 60)
            if i_f is None or i_s is None:
                continue
            j = np.searchsorted(dday, mon - 3)       # Friday's daily index; returns over 30 days ending Thursday
            if j < 31 or not full[j - 31:j].all() or dday[j - 1] - dday[j - 31] != 30:
                continue
            r = np.diff(np.log(d.c[j - 31:j]))
            sd_px = float(np.std(r, ddof=1)) * m.o[i_f]
            move = m.c[i_s] - m.o[i_f]
            for k in cnt:
                if abs(move) >= k * sd_px:
                    cnt[k] += 1
        print(sym, 'Mondays in train', weeks, 'qualifying', cnt)
