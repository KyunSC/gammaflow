"""H2 per-UTC-hour mean net R (prereg against_the_mechanism) from the gated train run's trade files; no new data look."""
import json
import sys
from datetime import datetime
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import numpy as np  # noqa: E402
import controller as K  # noqa: E402

for sym in K.GATE_SYMBOLS:
    for k, N in enumerate((1, 7, 30)):
        tr = json.loads((K.RUNS / 'H2_crypto_hour_periodicity' / f'train_{k}_{sym}.json').read_text())['trades']
        h = np.array([datetime.fromisoformat(t['entry']).hour for t in tr])
        r = np.array([t['r'] for t in tr])
        per = {int(x): round(float(r[h == x].mean()), 3) for x in range(24)}
        fund = np.isin(h, [0, 8, 16])
        print(sym, f'N={N}', 'funding-hours', round(float(r[fund].mean()), 4), 'other', round(float(r[~fund].mean()), 4))
        print('   ', per)
