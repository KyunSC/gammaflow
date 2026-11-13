"""C6F: PR #16's 4h change of character (CHoCH) on CME NQ and ES futures, 2011-2021, swing holds, no prop-firm rules.
A frozen one-look test against coin-flip twins.

The rule is choch_rule.choch_events, a verbatim copy of PR #16 (functions/ml/choch_crypto_study.py, spec C6). SPEC below
was written before any 2011-2021 bar was read for this rule; nothing is tuned. k = 2 is the a-priori swing length;
k = 1, 3, 5 are sensitivity only (reported, and counted in the deflated Sharpe, never in the verdict).

    python choch_futures_swing.py --check      # month coverage, contract segments and rolls only; no signals or trades
    python choch_futures_swing.py --confirm    # THE one look: writes swing_prereg.json + swing.lock, then loads bars

--confirm refuses when data/choch_futures/swing.lock exists. Any --confirm run consumes the look, including one with a
reduced --twins (the knob only changes Monte Carlo precision, not the rule).

Reused, not reinvented:
  choch_rule                 swing_points / choch_events (PR #16, unchanged)
  orb15_2r_study             PT_USD, TICK, COMM_SIDE, FUT_BARS, MIN_PRICE, missing_months, and trade()'s fill
                             conventions (leg() below is trade() made multi-day; see its docstring)
  open_ema_trail_study       contract_segments (a flip back to an older instrument_id starts a new segment), file_span
  close_auction_study        block_idx (moving-block bootstrap indices, as mfp_crypto_study.r_test uses)
  PR #16 mfp_crypto_study    run_book's mirror-flat book, mirrors / taken / excess / coin / r_test / passes, by_year,
                             lookahead_dirs, daily / deflate: copied below with their semantics unchanged (source notes
                             on each). PR #16 lives only in .claude/worktrees/pr-16, so they are copied, not imported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from choch_rule import choch_events  # noqa: E402
from close_auction_study import block_idx  # noqa: E402
from open_ema_trail_study import contract_segments, file_span  # noqa: E402
from orb15_2r_study import COMM_SIDE, FUT_BARS, MIN_PRICE, PT_USD, TICK  # noqa: E402
from orb15_2r_study import missing_months as orb_missing_months  # noqa: E402

OUT = HERE / "data" / "choch_futures"
PRODUCTS = ("NQ", "ES")
START = date(2011, 1, 3)          # first UTC day read
END_EXCL = date(2022, 1, 1)       # 2021-12-31 inclusive (UTC)
BAR_SECONDS = 4 * 3600
DAY = 86400

SPEC = dict(
    id="C6F",
    title="4h change of character on CME NQ/ES futures, swing holds, no prop-firm rules",
    source=("PR #16 spec C6 (functions/ml/choch_crypto_study.py, YouTube z97PnFIPoFg) moved to CME futures; the rule "
            "is choch_rule.py, a verbatim copy of PR #16's swing_points / choch_events"),
    data=("Databento GLBX.MDP3 fut-ohlcv-1m-cont NQ.v.0 / ES.v.0 (continuous front month by volume), native index "
          "points, every Globex 1m bar (not RTH-only), UTC bar starts in [2011-01-03 00:00, 2022-01-01 00:00). Refuse "
          "to run if any month 2011-01..2021-12 is missing. MIN_PRICE guard (NQ 1000, ES 500)."),
    bars=("UTC 4h bins (t // 14400) built from the 1m bars of ONE contract segment (a run of one instrument_id; a flip "
          "back to an older instrument starts a new segment). Swing state and ATR start fresh at each roll; no 4h bar "
          "spans a roll. A bin with no 1m bars does not exist (weekends, halts); nothing is fabricated."),
    rule=("choch_rule.choch_events(high, low, close, k) on the segment's 4h bars. The signal is at the 4h close (the "
          "close of the bin's last 1m bar); entry at the open of the next 1m bar of the same segment + 1 tick adverse; "
          "no such bar -> skip."),
    stop=("dist = side x (signal close - extreme) + 0.1 x ATR14 (4h, simple mean of true range over the 14 bins ending "
          "at the signal bin, within the segment; the first bin's true range is its high - low; fewer than 14 bins -> "
          "skip). Measured from the signal close as in PR #16, applied from the entry fill: stop = entry - side x dist. "
          "Target = entry + side x 1 x dist. Skip if dist <= 1 tick. Stop and target are not rounded to the tick grid."),
    exits=("On 1m bars from the entry bar, in order: open through the stop (after the entry bar) -> fill at the open "
           "- 1 tick; low/high through the stop -> stop - 1 tick; a tick through the target -> target, no slip; a bar "
           "touching both -> stop. Otherwise: 20-day time cap (close of the last 1m bar starting before entry bar "
           "start + 20 days, i.e. closing by entry + 20 days) - 1 tick; or the last 1m bar of the contract segment "
           "(forced roll exit) - 1 tick; or the last bar of the window - 1 tick. The exit reason is recorded "
           "(stop, target, time, roll, window_end)."),
    book=("One position at a time per product and config, PR #16's mirror-flat book: every signal is simulated long "
          "AND short from the same entry, stop distance, target and exit rules; a signal is taken only when both "
          "mirrors of the previous trade are flat (its entry bar is after the later of the two exit bars), otherwise "
          "it is dropped. The strategy and every twin therefore share the same trade list, and a twin's flip cannot "
          "change which later signals are dropped."),
    costs=("1 micro (MNQ $2/pt, MES $5/pt). net R = (pnl_points x $/pt - 2 x $0.50) / (dist x $/pt); slippage is in "
           "the fill prices. gross R = pnl_points / dist is reported beside it."),
    configs="k = 2 a-priori (primary); k = 1, 3, 5 sensitivity only (reported and counted in the deflated Sharpe).",
    statistics=("Per product and config: mean net R; 2,000 coin-flip twins drawing each trade's direction with P(long) "
                "= the strategy's long share (fair coin P = 0.5 reported too), exact on the mirrors; p = (1 + #twins "
                "with mean >= strategy mean) / (1 + twins); 95% moving-block bootstrap CI (blocks of 10 consecutive "
                "trades, 4,000 resamples) of the excess = strategy R - the twins' expected R on the same trade. Also "
                "by-year excess, by-side mean R, exit-reason counts, median hold hours, gross R, a planted look-ahead "
                "control and 200 fair-coin controls on the primary, and the deflated Sharpe of daily R over all 8 "
                "config x product trials."),
    decision=("alpha = 0.025 per product. PASS only if k = 2 has twin p < 0.025 AND excess CI lower bound > 0 on BOTH "
              "NQ and ES. Otherwise FAIL. One verdict line."),
    one_look=("--confirm writes data/choch_futures/swing_prereg.json (SPEC, spec hash, sha256 of choch_rule.py and "
              "choch_futures_swing.py) and swing.lock before any bar is loaded, and refuses if swing.lock exists. "
              "Results go to swing_results.json."),
    fixed=dict(bar_seconds=BAR_SECONDS, atr_bars=14, pad_atr=0.1, target_r=1.0, hold_days=20, tick=TICK,
               entry_slip_ticks=1, stop_slip_ticks=1, close_exit_slip_ticks=1, comm_side=COMM_SIDE, pt_usd=PT_USD,
               window=[START.isoformat(), "2021-12-31"]),
    primary=dict(k=2),
    grid=dict(k=[1, 2, 3, 5]),
    n_twins=2000,
    alpha_per_product=0.025,
)
F = SPEC["fixed"]

N_TWINS = SPEC["n_twins"]
ALPHA = SPEC["alpha_per_product"]
R_BOOT = 4000        # mfp_crypto_study.R_BOOT
R_BOOT_BLOCK = 10    # mfp_crypto_study.R_BOOT_BLOCK
SEED = 7             # mfp_crypto_study.SEED
LOOKAHEAD_FRAC = 0.25
COIN_CONTROLS = 200


def configs() -> list[dict]:
    return [dict(k=k) for k in SPEC["grid"]["k"]]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def code_hashes() -> dict:
    return {"choch_rule.py": sha256_file(HERE / "choch_rule.py"),
            "choch_futures_swing.py": sha256_file(Path(__file__).resolve())}


def spec_hash() -> str:
    body = json.dumps(dict(spec=SPEC, code=code_hashes()), sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def iso(t) -> str:
    return pd.Timestamp(int(t), unit="s", tz="UTC").isoformat()


# ---------------------------------------------------------------- tape

@dataclass
class Tape:
    """1m bars of one product in time order. t = UTC epoch seconds of the bar start; seg = contract segment id."""
    product: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    seg: np.ndarray
    iid: np.ndarray | None = None

    def __post_init__(self):
        self.t = np.asarray(self.t, np.int64)
        self.o, self.h, self.l, self.c = (np.asarray(x, float) for x in (self.o, self.h, self.l, self.c))
        self.seg = np.asarray(self.seg)
        self.n = len(self.t)

    def segments(self) -> list[tuple[int, int]]:
        """[a, b) of each contract segment."""
        a = run_starts(self.seg)
        return list(zip(a.tolist(), np.r_[a[1:], self.n].tolist()))


def run_starts(key: np.ndarray) -> np.ndarray:
    """Index of the first element of each run of equal values (mfp_crypto_study.run_starts)."""
    return np.r_[0, np.flatnonzero(np.diff(key)) + 1] if len(key) else np.zeros(0, int)


def load_globex(product: str) -> Tape:
    """Every Globex 1m bar of the continuous front month in the window, native points, one segment id per run of one
    instrument_id. Based on orb15_2r_study.load_fut without its RTH filter and mixed-contract-day drop."""
    files = [f for f in sorted((FUT_BARS / product).glob("*.parquet"))
             if (sp := file_span(f)) and sp[0] < END_EXCL and sp[1] > START]
    if not files:
        raise FileNotFoundError(f"no bars in {FUT_BARS / product}")
    cols = ["open", "high", "low", "close", "instrument_id"]
    bars = pd.concat([pd.read_parquet(f, columns=cols) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    bars = bars[(bars.index >= pd.Timestamp(START, tz="UTC")) & (bars.index < pd.Timestamp(END_EXCL, tz="UTC"))]
    assert bars.low.min() > MIN_PRICE[product], f"{product}: prices below {MIN_PRICE[product]}, not index points"
    t = np.asarray((bars.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1), np.int64)
    seg = contract_segments(bars.instrument_id).to_numpy()
    return Tape(product, t, bars.open.to_numpy(), bars.high.to_numpy(), bars.low.to_numpy(), bars.close.to_numpy(),
                seg, bars.instrument_id.to_numpy())


def missing_months(product: str) -> list[str]:
    """Months of 2011-01..2021-12 without a converted file (orb15_2r_study.missing_months, same window)."""
    return orb_missing_months(product)


# ---------------------------------------------------------------- 4h bars and signals

@dataclass
class Bins:
    """4h bins of one segment; first/last are 1m indices into the tape."""
    key: np.ndarray
    first: np.ndarray
    last: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray

    def atr(self, n: int) -> np.ndarray:
        """Simple mean of the last n true ranges (mfp_crypto_study.Bars.atr); the first bin's TR is its range."""
        prev = np.r_[np.nan, self.c[:-1]]
        tr = np.fmax(self.h - self.l, np.fmax(np.abs(self.h - prev), np.abs(self.l - prev)))
        return pd.Series(tr).rolling(n).mean().to_numpy()


def bins_4h(tp: Tape, a: int, b: int) -> Bins:
    key = tp.t[a:b] // BAR_SECONDS
    f = run_starts(key)
    first = f + a
    last = np.r_[first[1:] - 1, b - 1]
    return Bins(key[f], first, last, np.maximum.reduceat(tp.h[a:b], f), np.minimum.reduceat(tp.l[a:b], f), tp.c[last])


@dataclass
class Signal:
    sig: int        # 1m index of the signal bin's last bar (its close is the signal close)
    entry: int      # sig + 1, same segment
    side: int
    dist: float     # stop distance in points; target = TARGET_R x dist
    end: int        # last 1m index the trade may be held through
    end_why: str    # exit reason if neither stop nor target fills: time / roll / window_end


def signals(tp: Tape, k: int) -> tuple[list[Signal], dict]:
    """CHoCH signals of every segment, plus counts of events skipped and why."""
    out, skipped = [], dict(atr_warmup=0, no_entry_bar=0, dist_le_tick=0)
    for a, b in tp.segments():
        bn = bins_4h(tp, a, b)
        atr = bn.atr(F["atr_bars"])
        for tb, side, extreme in choch_events(bn.h, bn.l, bn.c, k):
            if not np.isfinite(atr[tb]):
                skipped["atr_warmup"] += 1
                continue
            s = int(bn.last[tb])
            if s + 1 >= b:
                skipped["no_entry_bar"] += 1
                continue
            dist = side * (tp.c[s] - extreme) + F["pad_atr"] * atr[tb]
            if dist <= TICK:
                skipped["dist_le_tick"] += 1
                continue
            e = s + 1
            time_end = int(np.searchsorted(tp.t, tp.t[e] + F["hold_days"] * DAY, side="left")) - 1
            if time_end < b - 1:
                end, why = time_end, "time"
            else:
                end, why = b - 1, "window_end" if b == tp.n else "roll"
            out.append(Signal(s, e, int(side), float(dist), end, why))
    return out, skipped


# ---------------------------------------------------------------- execution

@dataclass
class Leg:
    side: int
    exit: int
    why: str
    pts: float      # P&L in points for this side (positive = profit)
    entry_px: float
    exit_px: float


def leg(tp: Tape, sg: Signal, side: int) -> Leg:
    """One side of a signal, orb15_2r_study.trade() run over several days: prices are mirrored (x = -price for a
    short) so one long rule covers both. Entry = entry bar open + 1 tick; stop = entry - dist, target = entry + dist.
    Bar by bar from the entry bar: open <= stop after the entry bar -> open - 1 tick; low <= stop -> stop - 1 tick;
    high >= target + 1 tick -> target; stop first. Otherwise flat at the close of sg.end - 1 tick."""
    sl = slice(sg.entry, sg.end + 1)
    if side > 0:
        O, H, L, C = tp.o[sl], tp.h[sl], tp.l[sl], tp.c[sl]
    else:
        O, H, L, C = -tp.o[sl], -tp.l[sl], -tp.h[sl], -tp.c[sl]
    entry = O[0] + TICK
    stop, target = entry - sg.dist, entry + F["target_r"] * sg.dist
    hit_s = L <= stop
    hit = hit_s | (H >= target + TICK)
    if hit.any():
        j = int(np.argmax(hit))
        if hit_s[j]:
            px = O[j] - TICK if j > 0 and O[j] <= stop else stop - TICK
            why = "stop"
        else:
            px, why = target, "target"
    else:
        j = len(O) - 1
        px, why = C[j] - TICK, sg.end_why
    return Leg(side, sg.entry + j, why, float(px - entry), float(side * entry), float(side * px))


@dataclass
class Trade:
    sig: Signal
    legs: dict

    @property
    def exit(self) -> int:
        return max(self.legs[1].exit, self.legs[-1].exit)


def run_book(tp: Tape, sigs: list[Signal]) -> tuple[list[Trade], int]:
    """mfp_crypto_study.run_book: signals in time order, taken only when both mirrors of the last trade are flat
    (entry bar strictly after the later exit bar). Returns the trades and the number of signals dropped."""
    out, busy, dropped = [], -1, 0
    for sg in sorted(sigs, key=lambda s: s.sig):
        if sg.entry <= busy:
            dropped += 1
            continue
        tr = Trade(sg, {s: leg(tp, sg, s) for s in (1, -1)})
        out.append(tr)
        busy = tr.exit
    return out, dropped


def net_r(pts: float, dist: float, pt: float) -> float:
    return (pts * pt - 2 * COMM_SIDE) / (dist * pt)


# ---------------------------------------------------------------- twin tests (PR #16 mfp_crypto_study, copied)

def mirrors(trades: list[Trade], pt: float, gross: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-trade R of the long and the short mirror, and the strategy's sides (mfp_crypto_study.mirrors)."""
    f = (lambda lg, d: lg.pts / d) if gross else (lambda lg, d: net_r(lg.pts, d, pt))
    rl = np.array([f(t.legs[1], t.sig.dist) for t in trades])
    rs = np.array([f(t.legs[-1], t.sig.dist) for t in trades])
    return rl, rs, np.array([t.sig.side for t in trades])


def long_share(dirs: np.ndarray) -> float:
    return float((dirs > 0).mean())


def taken(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray) -> np.ndarray:
    return np.where(dirs > 0, rl, rs)


def excess(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray, p_long: float) -> np.ndarray:
    """Net R per trade over the twins' expectation on that same trade."""
    return taken(rl, rs, dirs) - (p_long * rl + (1 - p_long) * rs)


def coin(rng: np.random.Generator, shape, p_long: float) -> np.ndarray:
    return np.where(rng.random(shape) < p_long, 1, -1)


def r_test(rl: np.ndarray, rs: np.ndarray, dirs: np.ndarray, p_long: float | None = None, n_twins: int = N_TWINS,
           seed: int = SEED) -> dict:
    """mfp_crypto_study.r_test unchanged: mean R of `dirs` against twins drawing each trade's side with
    P(long) = p_long (default: dirs' long share); block-bootstrap CI of the excess over trades."""
    n = len(dirs)
    if n == 0:
        return dict(trades=0)
    pl = long_share(dirs) if p_long is None else p_long
    r = taken(rl, rs, dirs)
    rng = np.random.default_rng(seed)
    twin = taken(rl, rs, coin(rng, (n_twins, n), pl)).mean(1)
    ex = excess(rl, rs, dirs, pl)
    boot = ex[block_idx(n, R_BOOT, min(R_BOOT_BLOCK, n), rng)].mean(1)
    return dict(trades=n, p_long=pl, mean_r=float(r.mean()), twin_mean_r=float(twin.mean()),
                twin_p95=float(np.quantile(twin, 0.95)), excess=float(ex.mean()),
                excess_ci=[float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
                p=float((1 + (twin >= r.mean()).sum()) / (1 + n_twins)))


def passes(t: dict, alpha: float = ALPHA) -> bool:
    return t.get("trades", 0) > 0 and t["p"] < alpha and t["excess_ci"][0] > 0


def lookahead_dirs(tp: Tape, trades: list[Trade], frac: float = LOOKAHEAD_FRAC) -> np.ndarray:
    """Planted bug (mfp_crypto_study.lookahead_dirs): the side of the price `frac` of the way to the hold limit."""
    e = np.array([t.sig.entry for t in trades])
    later = e + (frac * (np.array([t.sig.end for t in trades]) - e)).astype(int)
    return np.where(tp.c[later] >= tp.o[e], 1, -1)


# ---------------------------------------------------------------- reporting

def by_year(tp: Tape, trades: list[Trade], rl, rs, dirs) -> dict:
    r, ex = taken(rl, rs, dirs), excess(rl, rs, dirs, long_share(dirs))
    yr = pd.to_datetime(tp.t[[t.sig.entry for t in trades]], unit="s", utc=True).year.to_numpy()
    return {int(y): dict(trades=int((yr == y).sum()), mean_r=float(r[yr == y].mean()), excess=float(ex[yr == y].mean()))
            for y in np.unique(yr)}


def describe(tp: Tape, trades: list[Trade], n_signals: int, dropped: int, skipped: dict) -> dict:
    base = dict(signals=n_signals, dropped_in_trade=dropped, skipped=skipped, trades=len(trades))
    if not trades:
        return base
    legs = [t.legs[t.sig.side] for t in trades]
    hold_h = np.array([(tp.t[lg.exit] - tp.t[t.sig.entry]) / 3600 for t, lg in zip(trades, legs)])
    dists = np.array([t.sig.dist for t in trades])
    return dict(base, long_share=long_share(np.array([t.sig.side for t in trades])), median_hold_h=float(np.median(hold_h)),
                median_dist_pts=float(np.median(dists)), cost_r_median=float(np.median(2 * COMM_SIDE / (dists * PT_USD[tp.product]))),
                exits=pd.Series([lg.why for lg in legs]).value_counts().to_dict(),
                first_entry=iso(tp.t[trades[0].sig.entry]), last_exit=iso(tp.t[max(t.exit for t in trades)]))


def daily(tp: Tape, trades: list[Trade], per_trade: np.ndarray) -> np.ndarray:
    """mfp_crypto_study.daily: per-trade values summed by UTC exit day over every day of the tape."""
    d0 = tp.t[0] // DAY
    out = np.zeros(int(tp.t[-1] // DAY - d0) + 1)
    if trades:
        np.add.at(out, np.array([tp.t[t.legs[t.sig.side].exit] // DAY for t in trades]) - d0, per_trade)
    return out


def deflate(rows: list[dict], books: list[tuple[Tape, list[Trade]]]) -> None:
    """mfp_crypto_study.deflate: deflated Sharpe of each config's daily net R (and R over the twins) against every
    config x product tried."""
    from flybrain.stats import deflated_sharpe, sharpe_inference
    series = {"raw": [], "excess": []}
    for tp, trades in books:
        if trades:
            rl, rs, dirs = mirrors(trades, PT_USD[tp.product])
            series["raw"].append(daily(tp, trades, taken(rl, rs, dirs)))
            series["excess"].append(daily(tp, trades, excess(rl, rs, dirs, long_share(dirs))))
        else:
            series["raw"].append(daily(tp, [], np.array([])))
            series["excess"].append(daily(tp, [], np.array([])))
    for name, xs in series.items():
        infs = [sharpe_inference(x.tolist(), ppy=365) for x in xs]
        trials = [i["sr"] for i in infs]
        for row, inf in zip(rows, infs):
            row.setdefault("dsr", {})[name] = dict(sharpe=inf["sharpe"], **deflated_sharpe(inf, trials))


# ---------------------------------------------------------------- study

def study_product(tp: Tape, n_twins: int) -> tuple[dict, dict]:
    pt = PT_USD[tp.product]
    rows, books = {}, {}
    for params in configs():
        key = f"k={params['k']}"
        sigs, skipped = signals(tp, **params)
        trades, dropped = run_book(tp, sigs)
        books[key] = trades
        row = rows[key] = dict(params=params, primary=params == SPEC["primary"],
                               book=describe(tp, trades, len(sigs), dropped, skipped))
        if not trades:
            continue
        rl, rs, dirs = mirrors(trades, pt)
        gl, gs, _ = mirrors(trades, pt, gross=True)
        row.update(twins=r_test(rl, rs, dirs, n_twins=n_twins),
                   fair_coin=r_test(rl, rs, dirs, p_long=0.5, n_twins=n_twins),
                   gross=r_test(gl, gs, dirs, n_twins=n_twins),
                   by_side={("long" if s > 0 else "short"): dict(trades=int((dirs == s).sum()),
                                                                 mean_r=float(taken(rl, rs, dirs)[dirs == s].mean()))
                            for s in (1, -1) if (dirs == s).any()},
                   years=by_year(tp, trades, rl, rs, dirs))
        if row["primary"]:
            coins = [r_test(rl, rs, coin(np.random.default_rng(SEED + 100 + i), len(trades), 0.5), n_twins=n_twins,
                            seed=SEED + i) for i in range(COIN_CONTROLS)]
            row["controls"] = dict(lookahead=r_test(rl, rs, lookahead_dirs(tp, trades), n_twins=n_twins),
                                   coin=coins[0], coin_pass_rate=float(np.mean([passes(c) for c in coins])))
    return rows, books


def verdict(results: dict) -> str:
    prim = [results["products"][p]["rows"][f"k={SPEC['primary']['k']}"] for p in PRODUCTS if p in results["products"]]
    ok = len(prim) == len(PRODUCTS) and all("twins" in r and passes(r["twins"]) for r in prim)
    return "PASS" if ok else "FAIL"


def run_study(tapes: dict, n_twins: int = N_TWINS) -> dict:
    results = dict(spec_id=SPEC["id"], n_twins=n_twins, alpha_per_product=ALPHA, configs_tried=len(configs()) * len(tapes),
                   products={})
    all_books = {}
    for p, tp in tapes.items():
        rows, all_books[p] = study_product(tp, n_twins)
        results["products"][p] = dict(first=iso(tp.t[0]), last=iso(tp.t[-1]), bars=tp.n, segments=len(tp.segments()),
                                      rows=rows)
    keys = [(p, k) for p in tapes for k in all_books[p]]
    deflate([results["products"][p]["rows"][k] for p, k in keys], [(tapes[p], all_books[p][k]) for p, k in keys])
    results["verdict"] = verdict(results)
    return results


def print_summary(results: dict) -> None:
    for p, pr in results["products"].items():
        for key, row in pr["rows"].items():
            b = row["book"]
            if "twins" not in row:
                print(f"{p} {key}: no trades ({b})")
                continue
            t, fc = row["twins"], row["fair_coin"]
            print(f"{p} {key}{' (primary)' if row['primary'] else ''}: n={t['trades']} long={b['long_share']:.0%} "
                  f"net R={t['mean_r']:+.3f} gross R={row['gross']['mean_r']:+.3f} twins={t['twin_mean_r']:+.3f} "
                  f"excess={t['excess']:+.3f} CI=[{t['excess_ci'][0]:+.3f}, {t['excess_ci'][1]:+.3f}] p={t['p']:.3f} "
                  f"(fair coin p={fc['p']:.3f}) DSR={row['dsr']['excess']['dsr']:.2f} hold={b['median_hold_h']:.0f}h "
                  f"exits={b['exits']} dropped={b['dropped_in_trade']}")
            if row["primary"]:
                print("    by year excess: " + " ".join(f"{y}:{v['excess']:+.2f}({v['trades']})" for y, v in row["years"].items()))
                print("    by side: " + " ".join(f"{s} {v['mean_r']:+.3f} ({v['trades']})" for s, v in row["by_side"].items()))
                c = row["controls"]
                print(f"    controls: look-ahead p={c['lookahead']['p']:.3f} excess={c['lookahead']['excess']:+.3f}; "
                      f"fair-coin pass rate {c['coin_pass_rate']:.1%}")
    print(f"VERDICT C6F k={SPEC['primary']['k']} (p < {ALPHA} and excess CI > 0 on both NQ and ES): {results['verdict']}")


# ---------------------------------------------------------------- one look

def check(load=load_globex, missing=missing_months) -> int:
    """Coverage and rolls only: no 4h bars, signals or trades."""
    bad = False
    for p in PRODUCTS:
        miss = missing(p)
        print(f"{p}: {'missing ' + str(len(miss)) + ' months: ' + ', '.join(miss[:12]) if miss else 'all 132 months present'}")
        bad |= bool(miss)
    if bad:
        print("Data incomplete; --confirm would refuse.")
        return 2
    for p in PRODUCTS:
        tp = load(p)
        segs = tp.segments()
        seen, flips = set(), 0
        print(f"\n{p}: {tp.n:,} 1m bars {iso(tp.t[0])} -> {iso(tp.t[-1])}, {len(segs)} contract segments")
        for a, b in segs:
            iid = int(tp.iid[a]) if tp.iid is not None else None
            flip = iid in seen
            flips += flip
            seen.add(iid)
            days = (tp.t[b - 1] - tp.t[a]) / DAY
            print(f"  seg {int(tp.seg[a]):>3} iid {iid} {iso(tp.t[a])} -> {iso(tp.t[b - 1])} {b - a:>7,} bars "
                  f"{days:6.1f} d{'  FLIP-BACK' if flip else ''}{'  SHORT' if days < 1 else ''}")
        print(f"  flip-backs to an older instrument: {flips}; segments shorter than 1 day: "
              f"{sum((tp.t[b - 1] - tp.t[a]) < DAY for a, b in segs)}")
    print("\n--check: coverage and rolls only; no signals or trades computed.")
    return 0


def confirm(out_dir: Path = OUT, n_twins: int = N_TWINS, load=load_globex, missing=missing_months) -> int:
    lock = out_dir / "swing.lock"
    if lock.exists():
        print(f"swing.lock exists ({lock.read_text().strip()}); refusing a second look")
        return 3
    miss = {p: missing(p) for p in PRODUCTS}
    if any(miss.values()):
        print(f"missing months, refusing (no lock written): { {p: m for p, m in miss.items() if m} }")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    h = spec_hash()
    prereg = dict(spec=SPEC, spec_hash=h, sha256=code_hashes(), n_twins=n_twins, written_utc=now,
                  note="written before any bar was loaded")
    (out_dir / "swing_prereg.json").write_text(json.dumps(prereg, indent=1, default=str))
    with open(lock, "x") as fh:  # exclusive create: two concurrent runs cannot both pass
        fh.write(f"C6F one look started {now} spec_hash {h} twins {n_twins}\n")
    tapes = {p: load(p) for p in PRODUCTS}
    results = run_study(tapes, n_twins)
    results.update(spec_hash=h, sha256=prereg["sha256"])
    (out_dir / "swing_results.json").write_text(json.dumps(results, indent=1, default=float))
    print_summary(results)
    with open(lock, "a") as fh:
        fh.write(f"finished {datetime.now(timezone.utc).isoformat()} verdict {results['verdict']}\n")
    print(f"wrote {out_dir / 'swing_results.json'}")
    return 0


def main(argv=None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--confirm", action="store_true", help="THE one look at 2011-2021 (writes the lock first)")
    g.add_argument("--check", action="store_true", help="month coverage, segments and rolls only")
    ap.add_argument("--twins", type=int, default=N_TWINS, help="twin draws (default: the frozen 2,000)")
    a = ap.parse_args(argv)
    if a.check:
        return check()
    return confirm(OUT, a.twins)


if __name__ == "__main__":
    raise SystemExit(main())
