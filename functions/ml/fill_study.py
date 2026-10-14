"""Fill mechanics on the NQ tape: how often a resting target fills on a touch, and what stops really cost.

The backtesters fill brackets on 1m bars. frontend/lib/backtest/engine.js and flybrain/engine.py fill a
target on a touch (optimistic: a resting limit may sit behind the queue); lucid_orb_study.py requires a
tick through (pessimistic: an order placed at entry is usually near the front). Stops are modelled at the
stop price + 1 tick (lucid_orb_study, flybrain SLIPPAGE_TICKS) and market exits at the bar price + 1 tick.
This measures those on Databento NQ trades (GLBX.MDP3 NQ.v.0, RTH 09:25-16:00 ET, side B = buy
aggressor, A = sell aggressor). It measures execution, not a strategy: no entry rule, no selection, no
parameter is fitted to P&L, so it consumes no test window. Nothing on or after holdout.VERIFY_START is
read.

Design (fixed before the first run):
  - sessions: every nq-trades partition before VERIFY_START, front contract only. Sessions with total
    volume < THIN_FRAC x the median are reported but excluded (roll days where NQ.v.0 is the dying
    contract: wide, thin, not what an MNQ trader on the front month sees).
  - brackets: a strategy-free grid. Entries every 15 min from 09:45 to 15:00 ET, both directions, stop
    and target both STOP_PCT% of the entry price away (1:1, rounded to the tick, as lucid_orb_study),
    and, added after the first run, STOP_TICKS fixed widths (the touch-only rate scales with width).
    Entry reference = first print at/after the entry time. Managed print by print until 15:55:00 ET.
  - stop (long; short mirrored): elected by the first print <= stop (CME elects on a trade at the stop).
    Elected stops fill inside the same matching event as the print that elected them (one ts_event: the
    first run found cascades of up to 89 prints sharing a timestamp), so the fill is bounded, in ticks
    worse than the stop:
      elect  the electing print (lower bound: the stop cannot fill better than the book it elected into)
      vwap   size-weighted price of the event's prints from the electing one on (headline: the stop's
             place in the cascade taken as uniform by contract)
      sweep  the worst print of the event (upper bound: the stop filled last)
      next   the first sell-aggressor print after the event (a stop held by the broker, not the exchange)
    The first run headlined max(sweep, next); revised to vwap with elect..sweep bounds once the
    shared-timestamp cascades were seen (a measurement definition, not a fitted parameter). Compared
    with the model's 1 tick and lucid_orb_study's planned stress of 1 + binomial(4, 0.3) ticks.
  - target (long; short mirrored): reached when a print >= target comes before the stop and 15:55.
      through     a print >= target + 1 tick: a resting sell at the target must have filled (price-time
                  priority). Fill is certain.
      touch-only  prints at the target, never through, before the bracket ends (stop or 15:55). Records
                  the buy-aggressor volume printed AT the target in that window: a resting sell fills if
                  that volume >= the queue ahead of it. The queue is unknown without MBO, so the fill
                  rate is reported for queue-ahead Q in QUEUE (0 = front of the queue).
    Each bracket is scored in R under: touch (engine.js / flybrain today), through (lucid_orb_study,
    the proposed A/B fix) and Q-queue (fill iff touch volume >= Q + 1). Exits at 15:55 are marked at
    the last print before 15:55:00. No costs: the R columns isolate the fill rule.
  - market fills: at each grid time, a market buy fills at the first buy-aggressor print at/after it and
    a sell at the first sell-aggressor print; slippage vs the first print (the 1m bar open the models
    use) and, at 15:55:00, vs the last print before it (the 15:54 bar close).
  - CIs: 95% bootstrap over sessions (brackets on one day are not independent), N_BOOT resamples.

Caveats: this is the NQ book; the account trades MNQ on its own book (arbitraged to the same price,
but with different depth and queue). Sizes here are 1-lot-like: a 4-7 MNQ order at $750 risk rarely
exceeds MNQ top-of-book, but larger sizes would walk the book. Days are the 2025-10-24..2026-08-14
tape only.

Usage:  python fill_study.py   (~30 s; writes data/fill_study/results.json and brackets.parquet, both git-ignored)

results.json["stop_slip_pmf"] is the measured stop slippage (ticks, vwap estimate) by ET clock bucket, for a
stress resampler in place of the assumed 1 + binomial(4, 0.3).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from holdout import VERIFY_START  # noqa: E402

ET = "America/New_York"
DATA = HERE / "data"
SOURCE = DATA / "databento" / "nq-trades" / "NQ"
OUT = DATA / "fill_study"

TICK = 0.25
STOP_PCT = (0.20, 0.35, 0.50)
STOP_TICKS = (8, 16, 40)
GRID_FIRST, GRID_LAST, GRID_STEP = 585, 900, 15     # 09:45 .. 15:00 ET, minutes after midnight
END = 955                                            # 15:55:00 ET
QUEUE = (0, 5, 20, 50)
THIN_FRAC = 0.4
N_BOOT = 2000
SEED = 42


def load(parquet: Path) -> dict | None:
    df = pd.read_parquet(parquet, columns=["ts_event", "price", "size", "side", "instrument_id", "sequence"])
    if df.empty:
        return None
    df = df[df["instrument_id"] == df["instrument_id"].mode().iloc[0]].sort_values(["ts_event", "sequence"])
    t = df["ts_event"].dt.tz_convert(ET)
    day = t.iloc[0].normalize()
    assert day < VERIFY_START, f"{parquet.name}: reaches the sealed verify block"
    return dict(
        date=day.date().isoformat(),
        ns=df["ts_event"].astype("int64").to_numpy(),
        sec=((t - day).dt.total_seconds()).to_numpy(),     # seconds after local midnight
        tick=np.rint(df["price"].to_numpy(float) / TICK).astype(np.int64),
        size=df["size"].to_numpy(np.int64),
        side=np.select([df["side"].to_numpy(str) == "B", df["side"].to_numpy(str) == "A"], [1, -1], 0),
    )


def event_end(s: dict, j: int) -> int:
    """Index of the last print in the aggressor event that holds print j (same ts_event)."""
    ns = s["ns"]
    return int(np.searchsorted(ns, ns[j], side="right")) - 1


def bracket(s: dict, i0: int, i_end: int, d: int, dist: int) -> dict:
    """Walk one 1:1 bracket from print i0 (entry reference) to i_end (exclusive), d = +1 long / -1 short."""
    tk, sd, sz = s["tick"], s["side"], s["size"]
    entry = int(tk[i0])
    stop, target = entry - d * dist, entry + d * dist
    seg = tk[i0:i_end] * d                                   # favourable = up
    hit_stop = np.flatnonzero(seg <= stop * d)
    j_stop = i0 + int(hit_stop[0]) if hit_stop.size else i_end
    hit_tgt = np.flatnonzero(seg[: j_stop - i0] >= target * d)
    out = dict(d=d, dist=dist)
    if hit_tgt.size:
        j_t = i0 + int(hit_tgt[0])
        w = slice(j_t, j_stop)
        through = np.flatnonzero(tk[w] * d >= (target + d) * d)
        j_thru = j_t + int(through[0]) if through.size else j_stop
        at = (tk[j_t:j_thru] == target) & (sd[j_t:j_thru] == d)  # buy aggressors lifting a resting sell (long)
        out.update(touch=True, through=bool(through.size), touch_vol=int(sz[j_t:j_thru][at].sum()))
    else:
        out.update(touch=False, through=False, touch_vol=0)
    if j_stop < i_end:
        e = event_end(s, j_stop)
        ev = slice(j_stop, e + 1)
        sweep = int(tk[ev].min() if d > 0 else tk[ev].max())
        vwap = float((tk[ev] * sz[ev]).sum() / sz[ev].sum())
        nxt = np.flatnonzero(sd[e + 1:i_end] == -d)
        nxt_px = int(tk[e + 1 + nxt[0]]) if nxt.size else sweep
        out.update(stopped=True, stop_sec=float(s["sec"][j_stop]), elect=(stop - int(tk[j_stop])) * d,
                   vwap=(stop - vwap) * d, sweep=(stop - sweep) * d, next=(stop - nxt_px) * d)
    else:
        out.update(stopped=False)
    out["mark_r"] = (int(tk[i_end - 1]) - entry) * d / dist     # where an unfilled bracket ends at 15:55
    return out


def r_under(b: dict, q: int | None) -> float:
    """R of one bracket when the target fills on: q=None touch; q=-1 through only; else touch_vol >= q+1."""
    filled = b["touch"] and (q is None or b["through"] or (q >= 0 and b["touch_vol"] >= q + 1))
    if filled:
        return 1.0
    if b["stopped"]:
        return -1.0   # costs isolated: the stop at its level
    return b["mark_r"]


def market(s: dict, i: int, d: int, ref: int) -> int | None:
    """Ticks worse than ref for a market order (d=+1 buy) arriving at print i."""
    k = np.flatnonzero(s["side"][i:i + 5000] == d)
    return None if not k.size else int((s["tick"][i + k[0]] - ref) * d)


def day_rows(s: dict) -> tuple[list[dict], list[dict]]:
    sec, tk = s["sec"], s["tick"]
    i_end = int(np.searchsorted(sec, END * 60))
    if i_end == 0 or i_end >= len(sec):
        return [], []
    brackets, markets = [], []
    for m in range(GRID_FIRST, GRID_LAST + 1, GRID_STEP):
        i0 = int(np.searchsorted(sec, m * 60))
        if i0 >= i_end:
            continue
        for d in (1, -1):
            widths = [(f"{pct:.2f}%", max(1, round(tk[i0] * TICK * pct / 100 / TICK))) for pct in STOP_PCT]
            for label, dist in widths + [(f"{t}t", t) for t in STOP_TICKS]:
                brackets.append(dict(date=s["date"], minute=m, width=label, **bracket(s, i0, i_end, d, dist)))
            markets.append(dict(date=s["date"], minute=m, d=d, kind="open", slip=market(s, i0, d, int(tk[i0]))))
    for d in (1, -1):   # flat at 15:55:00 against the 15:54 bar close
        markets.append(dict(date=s["date"], minute=END, d=-d, kind="close",
                            slip=market(s, i_end, -d, int(tk[i_end - 1]))))
    return brackets, markets


def boot(values: pd.Series, dates: pd.Series, rng) -> tuple[float, float, float]:
    """Mean of values with a 95% CI from resampling whole sessions."""
    g = pd.DataFrame({"v": values.astype(float), "d": dates.to_numpy()}).groupby("d")["v"].agg(["sum", "count"])
    s, c = g["sum"].to_numpy(), g["count"].to_numpy()
    k = rng.integers(0, len(g), (N_BOOT, len(g)))
    lo, hi = np.percentile(s[k].sum(1) / c[k].sum(1), [2.5, 97.5])
    return float(s.sum() / c.sum()), float(lo), float(hi)


def dist_ticks(x: pd.Series) -> dict:
    x = np.ceil(x.astype(float) - 1e-9)   # a vwap between ticks counts as the worse tick in the shares
    return {"n": int(len(x)), "mean": round(float(x.mean()), 3), "p50": float(x.median()),
            "p90": float(x.quantile(0.9)), "p99": float(x.quantile(0.99)), "max": int(x.max()),
            "share": {k: round(float(v), 4) for k, v in
                      {"<=0": (x <= 0).mean(), "1": (x == 1).mean(), "2": (x == 2).mean(),
                       "3-4": x.between(3, 4).mean(), ">=5": (x >= 5).mean()}.items()}}


def main() -> int:
    files = sorted(SOURCE.glob("*.parquet"))
    sessions, vols = [], {}
    for f in files:
        s = load(f)
        if s is None:
            continue
        vols[s["date"]] = int(s["size"].sum())
        sessions.append(s)
    med = float(np.median(list(vols.values())))
    thin = sorted(d for d, v in vols.items() if v < THIN_FRAC * med)
    b_rows, m_rows = [], []
    for s in sessions:
        if s["date"] in thin:
            continue
        b, m = day_rows(s)
        b_rows += b
        m_rows += m
    B, M = pd.DataFrame(b_rows), pd.DataFrame(m_rows)
    rng = np.random.default_rng(SEED)
    n_days = B["date"].nunique()
    print(f"{len(sessions)} sessions {min(vols)}..{max(vols)}; {len(thin)} thin excluded {thin}; "
          f"{n_days} used, {len(B)} brackets")

    res = dict(sessions=n_days, first=B["date"].min(), last=B["date"].max(), thin_excluded=thin,
               brackets=int(len(B)), by_width={})

    # ---- stops
    S = B[B["stopped"]].copy()
    S["clock"] = pd.cut(S["stop_sec"] / 60, [0, 600, 605, 840, 845, 24 * 60], right=False,
                        labels=["09:30-10:00", "10:00-10:05", "10:05-14:00", "14:00-14:05", "14:05-15:55"])
    res["stop"] = {k: dict(**dist_ticks(S[k]), raw_mean=round(float(S[k].mean()), 3),
                           mean_ci=[round(v, 3) for v in boot(S[k], S["date"], rng)])
                   for k in ("elect", "vwap", "sweep", "next")}
    print(f"\nSTOPS n={len(S)} (ticks worse than the stop; model 1, planned stress 1 + binomial(4,0.3) = mean 2.20)")
    for k, x in res["stop"].items():
        print(f"  {k:>5}: mean {x['raw_mean']:5.2f} (95% CI {x['mean_ci'][1]:.2f}..{x['mean_ci'][2]:.2f})  p50 {x['p50']:.0f}"
              f"  p90 {x['p90']:.0f}  p99 {x['p99']:.0f}  max {x['max']}  {x['share']}")
    res["stop_by_clock"] = {}
    for c, g in S.groupby("clock", observed=True):
        res["stop_by_clock"][str(c)] = dict(n=int(len(g)), **{k: round(float(g[k].mean()), 3) for k in ("elect", "vwap", "sweep")},
                                            p99_vwap=round(float(g["vwap"].quantile(.99)), 2))
        print(f"  {c}: n {len(g):>5}  elect {g['elect'].mean():5.2f}  vwap {g['vwap'].mean():5.2f}  sweep {g['sweep'].mean():5.2f}"
              f"  vwap p99 {g['vwap'].quantile(.99):.1f}")
    # empirical stop slippage for a stress resampler (lucid_orb_study I): P(ceil(vwap) = k ticks) by clock bucket
    res["stop_slip_pmf"] = {str(c): {str(int(k)): round(float(v), 5) for k, v in
                                     np.ceil(g["vwap"] - 1e-9).clip(lower=0).value_counts(normalize=True).sort_index().items()}
                            for c, g in S.groupby("clock", observed=True)}
    res["stop_by_width"] = {}
    for w, g in S.groupby("width", sort=False):
        res["stop_by_width"][w] = dict(n=int(len(g)), vwap=round(float(g["vwap"].mean()), 3),
                                       vwap_r=round(float((g["vwap"] / g["dist"]).mean()), 4))
    worst = (S.assign(t=pd.to_datetime(S["stop_sec"], unit="s").dt.strftime("%H:%M:%S"))
             .sort_values("vwap", ascending=False).drop_duplicates(["date", "t"]).head(10))
    res["stop_worst"] = worst[["date", "t", "d", "elect", "vwap", "sweep"]].to_dict("records")
    print("  worst (date, ET time of the electing print, vwap ticks):",
          [(r["date"], r["t"], round(r["vwap"], 1)) for r in res["stop_worst"]])

    # ---- targets
    T = B[B["touch"]]
    only = T[~T["through"]]
    res["target"] = dict(reached=int(len(T)), touch_only=int(len(only)),
                         touch_only_share=boot(~T["through"], T["date"], rng),
                         touch_vol=dict(p25=float(only["touch_vol"].quantile(.25)) if len(only) else None,
                                        p50=float(only["touch_vol"].median()) if len(only) else None,
                                        p75=float(only["touch_vol"].quantile(.75)) if len(only) else None,
                                        zero=round(float((only["touch_vol"] == 0).mean()), 4) if len(only) else None),
                         fill_rate_on_touch={str(q): round(float((only["touch_vol"] >= q + 1).mean()), 4)
                                             for q in QUEUE},
                         touch_only_then_stopped=round(float(only["stopped"].mean()), 4) if len(only) else None)
    tg = res["target"]
    print(f"\nTARGETS reached {tg['reached']}, touch-only {tg['touch_only']} = {tg['touch_only_share'][0]:.2%} "
          f"(95% CI {tg['touch_only_share'][1]:.2%}..{tg['touch_only_share'][2]:.2%}) of target hits")
    print(f"  touch-only volume at the target (contracts): p25 {tg['touch_vol']['p25']}, p50 "
          f"{tg['touch_vol']['p50']}, p75 {tg['touch_vol']['p75']}; zero {tg['touch_vol']['zero']:.1%}")
    print("  fill rate on a touch-only if Q contracts are ahead:", tg["fill_rate_on_touch"])
    print(f"  touch-only brackets that then hit the stop: {tg['touch_only_then_stopped']:.1%}")

    # ---- R by fill rule, per stop size
    print(f"\n{'width':>6} {'n':>6} | {'touch R':>8} {'Q=0':>8} {'Q=5':>8} {'Q=20':>8} {'Q=50':>8} {'through R':>9} "
          f"| {'touch-thru':>10} (95% CI)")
    for w, g in B.groupby("width", sort=False):
        rules = {"touch": None, **{f"Q{q}": q for q in QUEUE}, "through": -1}
        mean_r = {k: float(g.apply(lambda b, q=q: r_under(b, q), axis=1).mean()) for k, q in rules.items()}
        gap = g.apply(lambda b: r_under(b, None) - r_under(b, -1), axis=1)
        diff = boot(gap, g["date"], rng)
        res["by_width"][w] = dict(n=int(len(g)), mean_r={k: round(v, 4) for k, v in mean_r.items()},
                                  touch_minus_through=[round(v, 4) for v in diff],
                                  touch_only_share_of_hits=round(float((~g.loc[g["touch"], "through"]).mean()), 4),
                                  stop_slip_r=res["stop_by_width"].get(w, {}).get("vwap_r"))
        print(f"{w:>6} {len(g):>6} | {mean_r['touch']:>+8.4f} {mean_r['Q0']:>+8.4f} {mean_r['Q5']:>+8.4f} "
              f"{mean_r['Q20']:>+8.4f} {mean_r['Q50']:>+8.4f} {mean_r['through']:>+9.4f} | {diff[0]:>+10.4f} "
              f"({diff[1]:+.4f}..{diff[2]:+.4f}) | touch-only {res['by_width'][w]['touch_only_share_of_hits']:.2%}"
              f" of hits, stop slip {res['by_width'][w]['stop_slip_r']}R")

    # ---- market fills
    res["market"] = {}
    for kind, g in M.dropna(subset=["slip"]).groupby("kind"):
        res["market"][kind] = dist_ticks(g["slip"])
        x = res["market"][kind]
        print(f"\nMARKET {kind:>5} n={x['n']} mean {x['mean']:.2f} ticks vs {'1m open' if kind == 'open' else '15:54 close'}"
              f"  p90 {x['p90']:.0f}  p99 {x['p99']:.0f}  shares {x['share']}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=2, default=float))
    B.to_parquet(OUT / "brackets.parquet")
    print(f"\nwrote {OUT / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
