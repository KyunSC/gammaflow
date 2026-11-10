"""Command line: run one backtest and print the headline numbers.

    cd functions/ml
    python -m backtest --data ../../frontend/public/backtest/qqq_5m.json --strategy smaCross \
        --param fast=10 --param slow=50 --stop-pct 0.5 --flat-at-close --news high --trades trades.csv

`--config run.json` takes {"strategy", "params", "costs", "risk", "window"} in the same snake_case keys as
run_backtest; flags given on the command line override it.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

from . import STRATEGIES, Dataset, run_backtest


def _value(text: str):
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _hhmm(text: str) -> int:
    try:
        h, m = (int(x) for x in text.split(":"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"use HH:MM, e.g. 16:45, got {text!r}")
    minute = h * 60 + m
    if not (0 <= h < 24 and 0 <= m < 60 and minute > 0):
        raise argparse.ArgumentTypeError("use a time after 00:00 and before 24:00, e.g. 16:45")
    return minute


def _finite(x):
    """JSON has no NaN or Infinity: write them as null (and their sign as a string, so +inf is not lost)."""
    if isinstance(x, float) and not math.isfinite(x):
        return None if math.isnan(x) else ("Infinity" if x > 0 else "-Infinity")
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_finite(v) for v in x]
    return x


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backtest", description="GammaFlow backtest engine (Python)")
    ap.add_argument("--data", required=True, help="research dataset JSON (frontend/public/backtest/*.json format)")
    ap.add_argument("--config", help="JSON run config: strategy, params, costs, risk, window")
    ap.add_argument("--strategy", help=f"one of {', '.join(sorted(STRATEGIES))}")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="strategy parameter (repeat)")
    ap.add_argument("--slippage-bps", type=float)
    ap.add_argument("--commission", type=float, help="dollars per side")
    ap.add_argument("--capital", type=float)
    ap.add_argument("--stop-pct", type=float)
    ap.add_argument("--target-pct", type=float)
    ap.add_argument("--max-bars", type=int)
    ap.add_argument("--flat-at-close", action="store_true")
    ap.add_argument("--flat-by", type=_hhmm, metavar="HH:MM", help="be flat by this ET time (prop rule)")
    ap.add_argument("--long-only", action="store_true")
    ap.add_argument("--news", metavar="IMPACT[:BEFORE:AFTER]", help="flat through scheduled news, e.g. high:5:15")
    ap.add_argument("--window", nargs=2, type=int, metavar=("START", "END"), help="trade only bars START..END")
    ap.add_argument("--trades", metavar="CSV", help="write the trade list here")
    ap.add_argument("--json", action="store_true", help="print metrics as JSON")
    a = ap.parse_args(argv)

    cfg = {}
    if a.config:
        with open(a.config) as f:
            cfg = json.load(f)
        unknown = set(cfg) - {"strategy", "params", "costs", "risk", "window"}
        if unknown:
            ap.error(f"unknown config keys {sorted(unknown)}")
    strategy = a.strategy or cfg.get("strategy")
    if not strategy:
        ap.error("--strategy or a config with 'strategy' is required")
    params = {**cfg.get("params", {}), **dict(_split(kv, ap) for kv in a.param)}
    costs = dict(cfg.get("costs", {}))
    risk = dict(cfg.get("risk", {}))
    for key, val in (("slippage_bps", a.slippage_bps), ("commission_per_trade", a.commission),
                     ("initial_capital", a.capital)):
        if val is not None:
            costs[key] = val
    for key, val in (("stop_pct", a.stop_pct), ("target_pct", a.target_pct), ("max_bars", a.max_bars),
                     ("flat_by_et", a.flat_by)):
        if val is not None:
            risk[key] = val
    if a.flat_at_close:
        risk["flat_at_session_end"] = True
    if a.long_only:
        risk["allow_short"] = False
    if a.news:
        impact, *win = a.news.split(":")
        if len(win) > 2:
            ap.error(f"--news wants IMPACT[:BEFORE[:AFTER]], got {a.news!r}")
        try:
            mins = [float(x) for x in win]
        except ValueError:
            ap.error(f"--news minutes must be numbers, got {a.news!r}")
        risk["news_blackout"] = dict(impact=impact, **dict(zip(("before_min", "after_min"), mins)))
    window = tuple(a.window) if a.window else cfg.get("window")

    try:
        ds = Dataset.from_json(a.data)
    except (OSError, KeyError, ValueError, TypeError) as e:
        ap.error(f"cannot load {a.data}: {e}")
    try:
        res = run_backtest(ds, strategy, params, costs, risk, window)
    except (KeyError, ValueError, TypeError, OverflowError) as e:
        ap.error(str(e).strip('"'))
    m = res.metrics
    if a.json:
        out = {k: v for k, v in m.items() if k != "dd_curve"}
        print(json.dumps(_finite(out), indent=2, allow_nan=False))
    else:
        inf = m["inference"]
        if ds.synthetic:
            print("NOTE: synthetic dataset, not market data")
        print(f"{ds.symbol} {ds.interval}  {len(ds):,} bars  {strategy} {res.config['params']}")
        print(f"trades {m['n_trades']}  hit {m['hit_rate']:.1%}  PF {m['profit_factor']:.2f}  "
              f"expectancy ${m['expectancy']:,.2f}  exposure {m['exposure']:.1%}")
        print(f"return {m['total_return']:+.2%}  max DD {m['max_dd']:.2%}  Sharpe {m['sharpe']:.2f} "
              f"(95% CI {inf['ci'][0]:.2f} to {inf['ci'][1]:.2f}, PSR {inf['psr']:.2f})")
        print(f"{res.elapsed_ms:.0f} ms")
    if a.trades:
        res.trades_frame().to_csv(a.trades, index=False)
    return 0


def _split(kv: str, ap):
    if "=" not in kv:
        ap.error(f"--param wants KEY=VALUE, got {kv!r}")
    k, v = kv.split("=", 1)
    return k, _value(v)


if __name__ == "__main__":
    sys.exit(main())
