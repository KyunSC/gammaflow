"""Run only some configs of a candidate through the normal controller path (prereg count-check drops).

    cd functions/ml && ../../.venv/bin/python -B research_loop_free/b2/crypto/run_subset.py G2_toptrader_fade train 0 1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import controller as K  # noqa: E402

_plan = K.plan_run


def main():
    cid, block, keep = sys.argv[1], sys.argv[2], {int(k) for k in sys.argv[3:]}

    def plan_run(*a, **kw):
        todo, k = _plan(*a, **kw)
        return [x for x in todo if x in keep], k

    K.plan_run = plan_run
    return K.cmd_run(cid, block)


if __name__ == '__main__':      # the EV test uses a spawn Pool, which re-imports this file
    sys.exit(main())
