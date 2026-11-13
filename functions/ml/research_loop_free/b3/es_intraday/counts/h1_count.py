"""H1 count-only check: on_bar fed the dev sessions without the engine (no fills, no stops, no outcomes). A position is
simulated from the bar after an enter until the bar after the strategy's exit, or the session end; count = enters."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from research_loop_free.b3.es_intraday import controller as K  # noqa: E402
from research_loop_free.b3.es_intraday.eval import data  # noqa: E402
from research_loop_free.b3.es_intraday.eval.engine import _bar_dict, load_strategy_class  # noqa: E402

print('digest', K.verify_eval()[:8])
spec, path, s_sha, p_sha = K._load_candidate('H1_es_hour_periodicity')
warm, trade = data.load_split('dev')
out = {}
for cfg in K.configs(spec['grid']):
    st = load_strategy_class(path)(cfg)
    n = 0
    for w, group in ((True, warm), (False, trade)):
        for s in group:
            pos, nxt = None, None   # session end flattens
            for k in range(len(s.b5['slot'])):
                pos = nxt
                a = st.on_bar(_bar_dict(s, k, w), pos)
                if a and a['op'] == 'enter' and pos is None:
                    n += not w
                    nxt = {"side": a["side"]}
                elif a and a['op'] == 'exit':
                    nxt = None
    out[cfg['N']] = n
print(json.dumps(out))
