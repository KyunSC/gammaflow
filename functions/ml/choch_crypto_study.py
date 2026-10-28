"""4-hour change of character (CHoCH) on BTC and ETH, TRAIN block only, against coin-flip twins with MFP Elite costs.

Source: the YouTube video "Claude Tested 100,000 Price Action Strategies" (AI Pathways, z97PnFIPoFg, 12:35-14:21),
as summarised by Sunny on 2026-10-28: the 4h CHoCH was the most robust of ~100,000 price-action versions tested.
The video picked this rule out of a very large search, so its own backtest says little; this is a first look at it
on data nobody in this project has traded. The rule comes from the video and SPEC was written before any Binance bar
was read for it, so there is one a-priori config and nothing is tuned. The other swing lengths are reported as
sensitivity only, and they count in the deflated Sharpe.

    python functions/ml/choch_crypto_study.py                  # 2,000 twins, writes data/mfp_crypto/choch_train.json
    python functions/ml/choch_crypto_study.py --twins 200 --ev-twins 50 --paths 100   # quick look (still logged)

Execution, costs, sizing, the mirror-flat book, twins and controls are mfp_crypto_study's, unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mfp_crypto_study as mfp  # noqa: E402
from crypto_holdout import open_block  # noqa: E402
from mfp_crypto_study import Market, Signal  # noqa: E402

OUT = mfp.OUT / "choch_train.json"
BAR_SECONDS = 4 * 3600

SPEC = dict(
    id="C6",
    title="4h change of character",
    source="YouTube z97PnFIPoFg (AI Pathways, 2026-10-28), 12:35-12:47 and 13:15-14:21, per Sunny's summary",
    rule=("UTC 4h bars (00:00, 04:00, ... from 1m). Swing high at bar j: high above the k bars before it and at least "
          "the k bars after it; swing low mirrored (frontend levels.js swingPivots). A swing is known from the close "
          "of bar j+k. Uptrend: the last two known swing highs and the last two known swing lows both rise. "
          "Bearish CHoCH: in an uptrend, a 4h close below the last known swing low (the last higher low) goes short. "
          "Downtrend and bullish CHoCH mirrored. Each swing fires at most once. No sweep, no trend filter. Stop: "
          "pad x ATR14(4h) beyond the last swing: for a short, the higher of the last known swing high and the "
          "highest high from the broken swing low's bar through the signal bar (a top not yet confirmed as a swing); "
          "distance measured from the signal close. Target: 1 x the stop "
          "distance. Time exit after hold_days, a safety cap the video does not have (on a random walk it binds on <1% "
          "of trades); a trade still open at the block's end closes there, so no bar past the block is read."),
    fixed=dict(bar_hours=4, atr_bars=14, pad_atr=0.1, target_r=1.0, hold_days=20),
    primary=dict(k=2),
    grid=dict(k=[1, 2, 3, 5]),
)


def configs() -> list[dict]:
    return [dict(k=k) for k in SPEC["grid"]["k"]]


def spec_hash(params: dict) -> str:
    body = dict(id=SPEC["id"], rule=SPEC["rule"], fixed=SPEC["fixed"], params=params, execution=mfp.EXECUTION)
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def swing_points(high: np.ndarray, low: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Boolean swing-high and swing-low flags, levels.js semantics: strictly beyond the k bars before, at least the
    k bars after. Bar j's flag is only knowable at the close of bar j + k."""
    n = len(high)
    is_h, is_l = np.zeros(n, bool), np.zeros(n, bool)
    for j in range(k, n - k):
        before, after = slice(j - k, j), slice(j + 1, j + k + 1)
        is_h[j] = (high[j] > high[before]).all() and (high[j] >= high[after]).all()
        is_l[j] = (low[j] < low[before]).all() and (low[j] <= low[after]).all()
    return is_h, is_l


def choch_events(high: np.ndarray, low: np.ndarray, close: np.ndarray, k: int) -> list[tuple[int, int, float]]:
    """(signal bar, side, stop level before the pad) for every CHoCH, using only swings known at the signal close."""
    is_h, is_l = swing_points(high, low, k)
    hs: list[tuple[int, float]] = []
    ls: list[tuple[int, float]] = []
    fired_h = fired_l = -1
    out = []
    for t in range(len(close)):
        j = t - k  # the swing at bar j becomes known at this bar's close
        if j >= 0:
            if is_h[j]:
                hs.append((j, high[j]))
            if is_l[j]:
                ls.append((j, low[j]))
        if len(hs) < 2 or len(ls) < 2:
            continue
        up = hs[-1][1] > hs[-2][1] and ls[-1][1] > ls[-2][1]
        down = hs[-1][1] < hs[-2][1] and ls[-1][1] < ls[-2][1]
        if up and close[t] < ls[-1][1] and fired_l != ls[-1][0]:
            fired_l = ls[-1][0]
            out.append((t, -1, float(max(hs[-1][1], high[ls[-1][0]: t + 1].max()))))
        elif down and close[t] > hs[-1][1] and fired_h != hs[-1][0]:
            fired_h = hs[-1][0]
            out.append((t, 1, float(min(ls[-1][1], low[hs[-1][0]: t + 1].min()))))
    return out


def signals_c6(m: Market, k: int) -> list[Signal]:
    f = SPEC["fixed"]
    b = mfp.aggregate(m, m.t // BAR_SECONDS)
    atr = b.atr(f["atr_bars"])
    out = []
    for t, side, extreme in choch_events(b.h, b.l, b.c, k):
        if not np.isfinite(atr[t]):
            continue
        s = int(b.last[t])
        dist = side * (m.c[s] - extreme) + f["pad_atr"] * atr[t]
        if dist > 0:
            out.append(Signal(s, side, dist, f["target_r"] * dist, mfp.end_by_time(m, s, f["hold_days"] * 86400)))
    return out


def study_symbol(m: Market, n_twins: int) -> tuple[dict, dict]:
    rows, books = {}, {}
    for params in configs():
        key = f"C6 {json.dumps(params, sort_keys=True)}"
        trades = books[key] = mfp.run_book(m, signals_c6(m, **params))
        row = rows[key] = dict(spec="C6", params=params, hash=spec_hash(params), primary=params == SPEC["primary"],
                               book=mfp.describe(m, trades))
        if not trades:
            continue
        rl, rs, dirs = mfp.mirrors(trades)
        ok = ~np.array([t.holed for t in trades])
        row.update(twins=mfp.r_test(rl, rs, dirs, n_twins=n_twins),
                   fair_coin=mfp.r_test(rl, rs, dirs, p_long=0.5, n_twins=n_twins),
                   twins_unholed=mfp.r_test(rl[ok], rs[ok], dirs[ok], n_twins=n_twins),
                   by_side={("long" if s > 0 else "short"): dict(trades=int((dirs == s).sum()),
                                                                 mean_r=float(mfp.taken(rl, rs, dirs)[dirs == s].mean()))
                            for s in (1, -1) if (dirs == s).any()},
                   years=mfp.by_year(m, trades, dirs))
        if row["primary"]:
            coins = [mfp.r_test(rl, rs, mfp.coin_dirs(len(trades), mfp.SEED + 100 + i), n_twins=n_twins, seed=mfp.SEED + i)
                     for i in range(mfp.COIN_CONTROLS)]
            row["controls"] = dict(lookahead=mfp.r_test(rl, rs, mfp.lookahead_dirs(m, trades), n_twins=n_twins),
                                   coin=coins[0], coin_pass_rate=float(np.mean([mfp.passes(c) for c in coins])))
    return rows, books


def verdict(row: dict, alpha: float) -> str:
    """Train-block verdict for the a-priori config, the same bar C1-C5 were held to (DSR is reported beside it). A
    pass only makes it a validation candidate; it is not an edge."""
    if "twins" not in row:
        return "NO TRADES"
    ok = mfp.passes(row["twins"], alpha) and mfp.passes(row["twins_unholed"], alpha)
    return "PASS (validation candidate)" if ok else "FAIL"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--twins", type=int, default=mfp.N_TWINS)
    ap.add_argument("--ev-twins", type=int, default=mfp.N_TWINS)
    ap.add_argument("--paths", type=int, default=mfp.EV_PATHS)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    alpha = 0.05 / len(mfp.SYMBOLS)
    tried = len(configs()) * len(mfp.SYMBOLS)
    results = dict(spec=SPEC, hashes={json.dumps(p): spec_hash(p) for p in configs()}, execution=mfp.EXECUTION,
                   configs_tried=tried, alpha_per_symbol=alpha, n_twins=a.twins, ev_twins=a.ev_twins,
                   ev_paths=a.paths, symbols={})
    purpose = f"C6 4h CHoCH train study (a-priori k=2, {tried} configs incl. sensitivity), twins={a.twins}"
    with open_block("train", purpose=purpose, spec_hashes=[spec_hash(SPEC["primary"])]) as blk:
        markets, books = {}, {}
        for sym in mfp.SYMBOLS:
            m = markets[sym] = Market(sym, blk.bars(sym))
            rows, books[sym] = study_symbol(m, a.twins)
            results["symbols"][sym] = dict(first=mfp.iso(m.t[0]), last=mfp.iso(m.t[-1]), bars=m.n, rows=rows)
        keys = [(s, k) for s in mfp.SYMBOLS for k in books[s]]
        mfp.deflate([results["symbols"][s]["rows"][k] for s, k in keys], [(markets[s], books[s][k]) for s, k in keys])
        for sym, m in markets.items():
            for key, row in results["symbols"][sym]["rows"].items():
                if not row["primary"] or "twins" not in row:
                    continue
                trades = books[sym][key]
                _, _, dirs = mfp.mirrors(trades)
                row["ev"] = mfp.ev_test(mfp.build_book(m, trades), dirs, a.ev_twins, a.paths, a.workers)
                row["verdict"] = verdict(row, alpha)
                t = row["twins"]
                print(f"{sym} {key}: n={t['trades']} net R={t['mean_r']:+.3f} twins={t['twin_mean_r']:+.3f} "
                      f"excess={t['excess']:+.3f} CI=[{t['excess_ci'][0]:+.3f}, {t['excess_ci'][1]:+.3f}] p={t['p']:.3f} "
                      f"DSR={row['dsr']['excess']['dsr']:.2f} EV-over-twins=${row['ev']['ev_over_twins']:.0f} "
                      f"-> {row['verdict']}", flush=True)
    # A generic price-action rule that works on one of two coins trading the same hours is most likely noise: a
    # validation slot needs the a-priori config to pass on both.
    prim = [r for s in results["symbols"].values() for r in s["rows"].values() if r["primary"]]
    results["verdict"] = ("PASS: validation candidate (needs Sunny's approval to spend a slot)"
                          if prim and all(r.get("verdict", "").startswith("PASS") for r in prim) else "FAIL: close it")
    print(results["verdict"])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(results, indent=1, default=float))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
