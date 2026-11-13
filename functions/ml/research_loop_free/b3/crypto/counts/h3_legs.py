"""H3 long/short legs (prereg against_the_mechanism) from the gated train run's trade files; no new data look."""
import json
import sys
from pathlib import Path
CRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CRY))
import numpy as np  # noqa: E402
import controller as K  # noqa: E402

for sym in K.GATE_SYMBOLS:
    for k, L in enumerate((7, 14, 28)):
        tr = json.loads((K.RUNS / 'H3_crypto_tsmom' / f'train_{k}_{sym}.json').read_text())['trades']
        legs = {s: [t['r'] for t in tr if t['side'] == s] for s in (1, -1)}
        print(sym, f'L={L}', {('long' if s == 1 else 'short'): (len(v), round(float(np.mean(v)), 3)) for s, v in legs.items()})
