"""Strategy registry. Same ids and parameter names as the JS registry, so a run config is portable between
the browser and Python."""
from .base import Param, Strategy
from .research import GexRegime, GexWallFade, MlSignal
from .ta import BbReversion, SmaCross, VwapReversion

STRATEGIES: dict[str, Strategy] = {s.id: s for s in (SmaCross(), BbReversion(), VwapReversion(), GexWallFade(),
                                                      GexRegime(), MlSignal())}

# In the JS registry but not ported yet: they need lib/levels.js zone scoring and the rule-builder AST.
NOT_PORTED = ("srLevels", "custom")


def get_strategy(sid: str) -> Strategy:
    try:
        return STRATEGIES[sid]
    except KeyError:
        hint = " (JS only for now)" if sid in NOT_PORTED else ""
        raise KeyError(f"unknown strategy {sid!r}{hint}; have {sorted(STRATEGIES)}") from None


__all__ = ["Param", "Strategy", "STRATEGIES", "NOT_PORTED", "get_strategy"]
