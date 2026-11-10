"""GammaFlow backtest engine, Python edition.

A line-for-line port of frontend/lib/backtest (engine, costs, risk rules, metrics, Sharpe inference) so the
research scripts and the browser backtester can be checked against each other. See README.md.

    from backtest import Dataset, run_backtest
    ds = Dataset.from_json("frontend/public/backtest/qqq_5m.json")
    res = run_backtest(ds, "smaCross", {"fast": 10, "slow": 50}, risk={"flat_at_session_end": True})
    res.metrics["sharpe"], res.trades_frame()
"""
from .dataset import Dataset
from .engine import DEFAULT_COSTS, DEFAULT_RISK, BacktestResult, Exit, Instrument, Trade, run_backtest, summarize
from .strategies import STRATEGIES, Strategy, get_strategy

__all__ = ["Dataset", "run_backtest", "summarize", "BacktestResult", "Trade", "Exit", "Instrument",
           "DEFAULT_COSTS", "DEFAULT_RISK", "STRATEGIES", "Strategy", "get_strategy"]
