"""H1 per-hour and per-leg mean net R (prereg against_the_mechanism) from the gated dev run's trade files; no new look."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
import numpy as np  # noqa: E402
from research_loop_free.b3.es_intraday import controller as K  # noqa: E402

for k, N in enumerate((1, 5, 20)):
    tr = json.loads((K.RUNS / 'H1_es_hour_periodicity' / f'dev_{k}.json').read_text())['trades']
    r = np.array([t['r_base'] for t in tr])
    mod = np.array([t['entry_mod'] for t in tr])
    side = np.array([t['side'] for t in tr])
    hours = {f"{m // 60}:00": (int((mod == m).sum()), round(float(r[mod == m].mean()), 3)) for m in (600, 660, 720, 780, 840, 900)}
    print(f'N={N}', 'long', (int((side == 1).sum()), round(float(r[side == 1].mean()), 3)),
          'short', (int((side == -1).sum()), round(float(r[side == -1].mean()), 3)))
    print('   ', hours)
