"""Does the frozen NQ IV-wall break do better when dealers are short gamma? Rules: iv_wall_gamma_prereg.json.

SPENT DATA, INFORMATION ONLY: val1 2019-21 and val2 2022-26 picked the strategy, so this split cannot validate a
filter and the frozen rules are not changed. It also tags every forward journal trade with the live QQQ regime.

Regime = sign of QQQ net GEX (sum over the stored key levels) in the latest snapshot at or before the entry bar's
start, same ET session. Historical: ThetaData rebuild of the live calculator. Forward: the live Supabase rows.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_gamma.py            # one-look split + forward tags
    cd functions/ml && ../../.venv/bin/python -B iv_wall_gamma.py --forward  # forward tags only (run each evening)

Output: data/iv_wall/gamma_split.json, data/iv_wall/paper/gamma.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from iv_wall_grid import OUT, VOL_CSV, IVGrid, _ev
from iv_wall_study import load_vol

ML = Path(__file__).resolve().parent
PREREG = ML / "iv_wall_gamma_prereg.json"
TD = [ML / "data" / "thetadata_gex" / f for f in ("qqq_gex_snapshots_2016_2021.parquet", "qqq_gex_snapshots.parquet")]
PAPER = OUT / "paper"
NY = "America/New_York"
COIN_SEEDS = 40
PERMS, BOOTS = 20_000, 10_000
FORWARD_FROM = "2026-08-17"


def td_snapshots() -> pd.DataFrame:
    d = pd.concat([pd.read_parquet(f, columns=["computed_at", "net_gex"]) for f in TD], ignore_index=True)
    d["t"] = pd.to_datetime(d["computed_at"], utc=True)
    return d.drop_duplicates("t").sort_values("t")[["t", "net_gex"]].reset_index(drop=True)


def live_snapshots(since: str = FORWARD_FROM) -> pd.DataFrame:
    """QQQ net GEX per live snapshot from Supabase REST (same aggregation as build_dataset's SQL reader)."""
    import build_dataset as B
    creds = B.load_supabase_rest_creds()
    if creds is None:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
    base, key = creds
    ge = B._rest_get(base, key, "gamma_exposure", {"select": "id,computed_at", "symbol": "eq.QQQ",
                                                   "computed_at": f"gte.{since}", "order": "id.asc"})
    if not ge:
        return pd.DataFrame(columns=["t", "net_gex"])
    lo = min(r["id"] for r in ge)
    gl = B._rest_get(base, key, "gamma_levels", {"select": "id,gamma_exposure_id,gex",
                                                 "gamma_exposure_id": f"gte.{lo}", "order": "id.asc"})
    net = pd.DataFrame(gl).assign(gex=lambda x: pd.to_numeric(x["gex"], errors="coerce")) \
        .groupby("gamma_exposure_id")["gex"].sum()
    d = pd.DataFrame(ge)
    d["t"] = pd.to_datetime(d["computed_at"], utc=True)
    d["net_gex"] = d["id"].map(net)
    return d.dropna(subset=["net_gex"]).sort_values("t")[["t", "net_gex"]].reset_index(drop=True)


def regime_at(snaps: pd.DataFrame, when: pd.Timestamp):
    """(net_gex, snapshot time) of the latest same-ET-day snapshot at or before `when`, else (nan, None)."""
    i = snaps["t"].searchsorted(when, side="right") - 1
    if i < 0:
        return np.nan, None
    t = snaps["t"].iloc[i]
    if t.tz_convert(NY).date() != when.tz_convert(NY).date():
        return np.nan, None
    return float(snaps["net_gex"].iloc[i]), t


def window_trades(ev, split, vd, vv):
    warm, trade = ev["data"].load_split(split)
    tr = ev["engine"].run(warm, trade, IVGrid("touch", "fixed", 0.4, vd, vv))["trades"]
    risk = np.array([t["risk_pts"] * 2.0 for t in tr])
    real = np.asarray(ev["costs"].apply(tr, "base")["usd"]) / risk
    lg = [ev["twins"]._one(trade[t["si"]], t, 1) for t in tr]
    sh = [ev["twins"]._one(trade[t["si"]], t, -1) for t in tr]
    rl = np.asarray(ev["costs"].apply(lg, "base")["usd"]) / risk
    rs = np.asarray(ev["costs"].apply(sh, "base")["usd"]) / risk
    rows = []
    for k, t in enumerate(tr):
        s = trade[t["si"]]
        rows.append({"window": split, "entry": pd.Timestamp(int(s.t[t["j_entry"]]), unit="s", tz="UTC"),
                     "side": "long" if t["side"] > 0 else "short", "exit_kind": t["exit_kind"], "r": real[k],
                     "r_long": rl[k], "r_short": rs[k]})
    return rows


def coin_mean(df, mask):
    """Mean net R of random-direction twins over the masked trades, averaged over COIN_SEEDS seeds."""
    out = []
    for seed in range(1, COIN_SEEDS + 1):
        c = np.random.default_rng(seed).random(len(df)) < 0.5
        r = np.where(c, df["r_long"], df["r_short"])
        out.append(r[mask].mean())
    return float(np.mean(out))


def boot_ci(x, rng):
    m = rng.choice(x, (BOOTS, len(x))).mean(1)
    return [float(np.quantile(m, .025)), float(np.quantile(m, .975))]


def split_stats(df, rng):
    neg, pos = df["regime"] == "neg", df["regime"] == "pos"
    rn, rp = df.loc[neg, "r"].to_numpy(), df.loc[pos, "r"].to_numpy()
    diff = rn.mean() - rp.mean()
    years = df["entry"].dt.tz_convert(NY).dt.year.to_numpy()
    lab = neg.to_numpy()
    r = df["r"].to_numpy()
    groups = [np.flatnonzero(years == y) for y in np.unique(years)]
    hits = 0
    for _ in range(PERMS):
        p = lab.copy()
        for g in groups:
            p[g] = rng.permutation(p[g])
        hits += (r[p].mean() - r[~p].mean()) >= diff
    bd = rng.choice(rn, (BOOTS, len(rn))).mean(1) - rng.choice(rp, (BOOTS, len(rp))).mean(1)
    coin_all, coin_n, coin_p = coin_mean(df, np.ones(len(df), bool)), coin_mean(df, neg.to_numpy()), coin_mean(df, pos.to_numpy())
    return {
        "n": int(len(df)), "n_neg": int(neg.sum()), "n_pos": int(pos.sum()),
        "r_all": float(r.mean()), "r_neg": float(rn.mean()), "r_pos": float(rp.mean()),
        "ci_neg": boot_ci(rn, rng), "ci_pos": boot_ci(rp, rng),
        "diff": float(diff), "ci_diff": [float(np.quantile(bd, .025)), float(np.quantile(bd, .975))],
        "p_within_year": float((hits + 1) / (PERMS + 1)),
        "coin_all": coin_all, "coin_neg": coin_n, "coin_pos": coin_p,
        "edge_all": float(r.mean() - coin_all), "edge_neg": float(rn.mean() - coin_n), "edge_pos": float(rp.mean() - coin_p),
    }


def breakdown(df):
    out = {}
    for name, key in (("side", df["side"]), ("year", df["entry"].dt.tz_convert(NY).dt.year), ("exit", df["exit_kind"])):
        g = df.groupby([key, df["regime"]])["r"].agg(["size", "mean"]).reset_index()
        g.columns = [name, "regime", "n", "r"]
        out[name] = g.to_dict("records")
    return out


def one_look():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    td = td_snapshots()
    df = pd.DataFrame(window_trades(ev, "val1", vd, vv) + window_trades(ev, "val2", vd, vv))
    got = [regime_at(td, t) for t in df["entry"]]
    df["net_gex"] = [g for g, _ in got]
    df["regime"] = np.where(df["net_gex"].isna(), "unknown", np.where(df["net_gex"] < 0, "neg", "pos"))
    known = df[df["regime"] != "unknown"].reset_index(drop=True)
    rng = np.random.default_rng(20261105)
    res = {"pooled": split_stats(known, rng)}
    for w in ("val1", "val2"):
        res[w] = split_stats(known[known["window"] == w].reset_index(drop=True), rng)
    p = res["pooled"]
    verdict = (p["diff"] > 0 and p["p_within_year"] < 0.05 and res["val1"]["diff"] > 0 and res["val2"]["diff"] > 0
               and p["edge_neg"] > p["edge_all"])
    out = {"ran": datetime.now().isoformat(timespec="seconds"),
           "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "unknown_regime": int((df["regime"] == "unknown").sum()), **res,
           "breakdown": breakdown(known), "worth_tracking": bool(verdict)}
    for k in ("pooled", "val1", "val2"):
        s = res[k]
        print(f"{k:6s} n {s['n']:3d}  neg {s['n_neg']:3d} {s['r_neg']:+.3f}R  pos {s['n_pos']:3d} {s['r_pos']:+.3f}R  "
              f"diff {s['diff']:+.3f} CI [{s['ci_diff'][0]:+.3f}, {s['ci_diff'][1]:+.3f}]  p(within-year) {s['p_within_year']:.3f}  "
              f"coin neg {s['coin_neg']:+.3f} pos {s['coin_pos']:+.3f}  edge neg {s['edge_neg']:+.3f} pos {s['edge_pos']:+.3f} "
              f"all {s['edge_all']:+.3f}", flush=True)
    print(f"unknown regime: {out['unknown_regime']}  worth tracking: {verdict}", flush=True)
    return out, td


def forward(td=None):
    tr = pd.read_csv(PAPER / "trades.csv")
    live = live_snapshots()
    td = td_snapshots() if td is None else td
    rows = []
    for _, t in tr.iterrows():
        when = pd.Timestamp(t["entry_et"]).tz_localize(NY).tz_convert("UTC")
        g, at = regime_at(live, when)
        gt, _ = regime_at(td, when)
        rows.append({"date": t["date"], "entry_et": t["entry_et"], "side": t["side"], "r_net": t["r_net"],
                     "live_net_gex": g, "live_snapshot_et": at.tz_convert(NY).strftime("%Y-%m-%d %H:%M") if at is not None else "",
                     "regime": "unknown" if np.isnan(g) else ("neg" if g < 0 else "pos"),
                     "td_regime": "" if np.isnan(gt) else ("neg" if gt < 0 else "pos")})
    f = pd.DataFrame(rows)
    f.to_csv(PAPER / "gamma.csv", index=False)
    # live vs ThetaData label agreement on every 5m ThetaData snapshot inside the live coverage
    ov = td[td["t"] >= pd.Timestamp(FORWARD_FROM, tz=NY)]
    agree = [(np.sign(g) == np.sign(regime_at(live, t)[0])) for t, g in zip(ov["t"], ov["net_gex"])
             if not np.isnan(regime_at(live, t)[0])]
    print(f"forward trades tagged: {len(f)}  (live regime vs ThetaData rebuild agree on "
          f"{np.mean(agree):.0%} of {len(agree)} overlapping snapshots)" if agree else "no overlap", flush=True)
    for reg, g in f.groupby("regime"):
        print(f"  {reg}: {len(g)} trades, mean {g['r_net'].mean():+.3f}R, sum {g['r_net'].sum():+.2f}R", flush=True)
    return f, (float(np.mean(agree)) if agree else None, len(agree))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--forward", action="store_true", help="only tag forward journal trades")
    a = ap.parse_args()
    if a.forward:
        forward()
    else:
        out, td = one_look()
        f, (agree, n_agree) = forward(td)
        out["forward"] = {"tags": f.to_dict("records"), "live_vs_td_agree": agree, "overlap_snapshots": n_agree}
        (OUT / "gamma_split.json").write_text(json.dumps(out, indent=1, default=str))
