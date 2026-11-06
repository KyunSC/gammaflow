"""How does the frozen NQ IV-wall break do with a news filter? Rules: iv_wall_news_prereg.json.

SPENT DATA, INFORMATION ONLY: val1 2019-21 and val2 2022-26 picked the strategy; the frozen rules are not changed.
Variants: A all trades; B1 skip high-impact news days; B2 skip days with a high-impact release inside RTH;
C flat 5 minutes before / no entries until 15 minutes after each RTH high-impact release (engine run).

    cd functions/ml && ../../.venv/bin/python -B iv_wall_news.py

Output: data/iv_wall/news_filter.json
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from iv_wall_grid import OUT, VOL_CSV, IVGrid, _ev
from iv_wall_study import load_vol

ML = Path(__file__).resolve().parent
PREREG = ML / "iv_wall_news_prereg.json"
NEWS = ML / "research_loop_nq" / "eval" / "news.json"
BEFORE, AFTER, BAR = 5, 15, 5
COIN_SEEDS, PERMS, BOOTS = 40, 20_000, 10_000


class NewsFlat(IVGrid):
    """Frozen IVGrid; flat and no orders while the next 5m bar overlaps [event - 5m, event + 15m)."""

    def on_bar(self, bar, pos):
        act = super().on_bar(bar, pos)
        lo, hi = bar["mod"] + BAR, bar["mod"] + 2 * BAR
        if any(lo < e + AFTER and hi > e - BEFORE for e in bar["news"]):
            if pos is not None:
                return {"op": "exit"}
            return None
        return act


def run(ev, split, strat):
    warm, trade = ev["data"].load_split(split)
    tr = ev["engine"].run(warm, trade, strat)["trades"]
    risk = np.array([t["risk_pts"] * 2.0 for t in tr])
    r = np.asarray(ev["costs"].apply(tr, "base")["usd"]) / risk
    rs = np.asarray(ev["costs"].apply(tr, "stress")["usd"]) / risk
    rl = np.asarray(ev["costs"].apply([ev["twins"]._one(trade[t["si"]], t, 1) for t in tr], "base")["usd"]) / risk
    rsh = np.asarray(ev["costs"].apply([ev["twins"]._one(trade[t["si"]], t, -1) for t in tr], "base")["usd"]) / risk
    rows = []
    for k, t in enumerate(tr):
        s = trade[t["si"]]
        rows.append({"window": split, "day": t["day"], "year": int(t["day"][:4]), "side": t["side"],
                     "entry_mod": t["entry_mod"], "exit_mod": t["exit_mod"], "exit_kind": t["exit_kind"],
                     "news_day": s.news_day, "rth_news": bool(s.news), "r": r[k], "r_stress": rs[k],
                     "r_long": rl[k], "r_short": rsh[k]})
    sessions = pd.DataFrame([{"window": split, "day": s.day.isoformat(), "year": s.day.year, "news_day": s.news_day,
                              "rth_news": bool(s.news)} for s in trade])
    return pd.DataFrame(rows), sessions


def coin(df):
    if len(df) == 0:
        return float("nan")
    return float(np.mean([np.where(np.random.default_rng(seed).random(len(df)) < 0.5, df["r_long"], df["r_short"]).mean()
                          for seed in range(1, COIN_SEEDS + 1)]))


def summary(df, n_years):
    return {"n": int(len(df)), "mean_r": float(df["r"].mean()), "stress_r": float(df["r_stress"].mean()),
            "total_r": float(df["r"].sum()), "r_per_year": float(df["r"].sum() / n_years),
            "trades_per_year": float(len(df) / n_years), "coin_r": coin(df),
            "edge_over_coin": float(df["r"].mean() - coin(df)) if len(df) else float("nan"),
            "win_rate": float((df["r"] > 0).mean())}


def day_split(df, col, rng):
    """Mean R on flagged vs unflagged days, within-year permutation p (two-sided), bootstrap CI of the difference."""
    lab = df[col].to_numpy(bool)
    r = df["r"].to_numpy()
    diff = r[lab].mean() - r[~lab].mean()
    groups = [np.flatnonzero(df["year"].to_numpy() == y) for y in df["year"].unique()]
    null = np.empty(PERMS)
    for i in range(PERMS):
        p = lab.copy()
        for g in groups:
            p[g] = rng.permutation(p[g])
        null[i] = r[p].mean() - r[~p].mean()
    bd = rng.choice(r[lab], (BOOTS, lab.sum())).mean(1) - rng.choice(r[~lab], (BOOTS, (~lab).sum())).mean(1)
    return {"n_flag": int(lab.sum()), "n_clear": int((~lab).sum()), "r_flag": float(r[lab].mean()),
            "r_clear": float(r[~lab].mean()), "diff_flag_minus_clear": float(diff),
            "ci": [float(np.quantile(bd, .025)), float(np.quantile(bd, .975))],
            "p_two_sided": float(((np.abs(null) >= abs(diff)).sum() + 1) / (PERMS + 1))}


def paired_c(a, c, sessions, rng):
    """Per-session sum of net R, C minus A, bootstrapped over sessions."""
    da = a.groupby("day")["r"].sum()
    dc = c.groupby("day")["r"].sum()
    d = (dc.reindex(sessions["day"]).fillna(0) - da.reindex(sessions["day"]).fillna(0)).to_numpy()
    bs = rng.choice(d, (BOOTS, len(d))).sum(1)
    touched = d != 0
    return {"total_diff_r": float(d.sum()), "ci": [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))],
            "sessions_changed": int(touched.sum()), "sessions_better": int((d > 0).sum()),
            "sessions_worse": int((d < 0).sum())}


def main():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    A, C, S = [], [], []
    for split in ("val1", "val2"):
        a, s = run(ev, split, IVGrid("touch", "fixed", 0.4, vd, vv))
        c, _ = run(ev, split, NewsFlat("touch", "fixed", 0.4, vd, vv))
        A.append(a), C.append(c), S.append(s)
        print(f"{split}: A {len(a)} trades, C {len(c)} trades", flush=True)
    A, C, S = pd.concat(A, ignore_index=True), pd.concat(C, ignore_index=True), pd.concat(S, ignore_index=True)
    assert S["news_day"].notna().all(), "news calendar does not cover every session"
    A["news_day"] = A["news_day"].astype(bool)
    rng = np.random.default_rng(20261105)
    out = {"ran": datetime.now().isoformat(timespec="seconds"),
           "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "sessions": {"n": int(len(S)), "news_days": int(S["news_day"].sum()), "rth_news_days": int(S["rth_news"].sum())}}
    for scope, mask_a, mask_c, mask_s in [("pooled", slice(None), slice(None), slice(None))] + [
            (w, A["window"] == w, C["window"] == w, S["window"] == w) for w in ("val1", "val2")]:
        a, c, s = A.loc[mask_a], C.loc[mask_c], S.loc[mask_s]
        ny = len(s) / 252
        res = {"A_all": summary(a, ny), "B1_skip_news_days": summary(a[~a["news_day"]], ny),
               "B2_skip_rth_news_days": summary(a[~a["rth_news"]], ny), "C_flat_for_news": summary(c, ny),
               "B1_test": day_split(a, "news_day", rng), "B2_test": day_split(a, "rth_news", rng),
               "C_test": paired_c(a, c, s, rng)}
        out[scope] = res
    # per year, per exit kind on news days
    yr = []
    for y, g in A.groupby("year"):
        cy = C[C["year"] == y]
        yr.append({"year": int(y), "A": float(g["r"].sum()), "B1": float(g.loc[~g["news_day"], "r"].sum()),
                   "B2": float(g.loc[~g["rth_news"], "r"].sum()), "C": float(cy["r"].sum()),
                   "news_r": float(g.loc[g["news_day"], "r"].sum()), "n_news": int(g["news_day"].sum()), "n": int(len(g))})
    out["by_year"] = yr
    out["exit_mix"] = {col: A.groupby(col)["exit_kind"].value_counts().unstack(fill_value=0).to_dict("index")
                       for col in ("news_day", "rth_news")}
    out["news_day_by_side"] = A.groupby(["news_day", "side"])["r"].agg(["size", "mean"]).reset_index().to_dict("records")
    out["c_exit_kinds"] = C["exit_kind"].value_counts().to_dict()
    # forward journal
    news = json.loads(NEWS.read_text())
    lo, hi = (date.fromisoformat(x) for x in news["news_days_coverage"])
    nd, rth = set(news["news_days"]), news["rth"]
    fw = pd.read_csv(OUT / "paper" / "trades.csv")
    tags = []
    for _, t in fw.iterrows():
        d = date.fromisoformat(t["date"])
        cov = lo <= d <= hi
        tags.append({"date": t["date"], "entry_et": t["entry_et"], "exit_et": t["exit_et"], "r_net": t["r_net"],
                     "news_day": (t["date"] in nd) if cov else None, "rth_news": rth.get(t["date"], []) if cov else None})
    out["forward"] = tags
    (OUT / "news_filter.json").write_text(json.dumps(out, indent=1, default=str))
    for scope in ("pooled", "val1", "val2"):
        print(f"\n== {scope}")
        for k in ("A_all", "B1_skip_news_days", "B2_skip_rth_news_days", "C_flat_for_news"):
            x = out[scope][k]
            print(f"  {k:22s} n {x['n']:3d} ({x['trades_per_year']:4.1f}/yr)  mean {x['mean_r']:+.3f}R  stress {x['stress_r']:+.3f}  "
                  f"R/yr {x['r_per_year']:+5.2f}  coin {x['coin_r']:+.3f}  edge {x['edge_over_coin']:+.3f}  win {x['win_rate']:.0%}")
        for k in ("B1_test", "B2_test"):
            x = out[scope][k]
            print(f"  {k}: flagged {x['n_flag']} {x['r_flag']:+.3f}R vs clear {x['n_clear']} {x['r_clear']:+.3f}R  "
                  f"diff {x['diff_flag_minus_clear']:+.3f} CI [{x['ci'][0]:+.3f}, {x['ci'][1]:+.3f}]  p {x['p_two_sided']:.3f}")
        x = out[scope]["C_test"]
        print(f"  C_test: total {x['total_diff_r']:+.2f}R CI [{x['ci'][0]:+.2f}, {x['ci'][1]:+.2f}]  sessions changed "
              f"{x['sessions_changed']} (better {x['sessions_better']}, worse {x['sessions_worse']})")
    print("\nby year:", *(f"\n  {y['year']}: A {y['A']:+6.2f}  B1 {y['B1']:+6.2f}  B2 {y['B2']:+6.2f}  C {y['C']:+6.2f}  "
                          f"news-day trades {y['n_news']}/{y['n']} sum {y['news_r']:+.2f}" for y in yr))
    print("C exit kinds:", out["c_exit_kinds"])
    print("forward:", *(f"\n  {t['date']} {t['r_net']:+.3f}R news_day {t['news_day']} rth {t['rth_news']}" for t in tags))


if __name__ == "__main__":
    main()
