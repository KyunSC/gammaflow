"""Does the frozen NQ IV-wall break depend on the hour? Rules: iv_wall_hours_prereg.json.

Part A: frozen trades by entry hour, and exact reruns with the order window restricted inside RTH.
Part B: the same OCO resting overnight (18:00 ET -> 09:30) on 1m Globex bars.

SPENT DATA, INFORMATION ONLY; the frozen rule is not changed.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_hours.py

Output: data/iv_wall/hours.json
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from iv_wall_grid import OUT, TARGET_R, VOL_CSV, IVGrid, _ev
from iv_wall_study import load_vol

ML = Path(__file__).resolve().parent
PREREG = ML / "iv_wall_hours_prereg.json"
COIN_SEEDS, BOOTS, S_MULT = 40, 10_000, 0.4
SPLITS = ("dev", "val1", "val2")
BUCKETS = [(575, 630), (630, 690), (690, 750), (750, 810), (810, 870), (870, 936)]
STOP_AT = [630, 690, 750, 810, 870]        # no new order after this ET minute
START_AT = [600, 630, 690, 750, 810]       # first order live from this ET minute
ON_BUCKETS = [("18:00-02:00", lambda m: m >= 1080 or m < 120), ("02:00-08:00", lambda m: 120 <= m < 480),
              ("08:00-09:30", lambda m: 480 <= m < 570)]


def hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


class IVHours(IVGrid):
    """Frozen rule, but an order is only placed on decisions in slots [first, last]. Walls touched outside die as usual."""

    def __init__(self, first, last, vd, vv):
        super().__init__("touch", "fixed", S_MULT, vd, vv)
        self.fs, self.ls = first, last

    def on_bar(self, bar, pos):
        out = super().on_bar(bar, pos)
        if out is not None and out.get("op") == "enter" and not (self.fs <= bar["slot"] <= self.ls):
            return None
        return out


def net_r(ev, trades, scen="base"):
    return ev["costs"].apply(trades, scen)["r"] if trades else np.zeros(0)


def coin_r(ev, paths, trades):
    """Mean net R of the same entries taken in a random direction (40 seeds). paths: si -> session-like."""
    if not trades:
        return float("nan")
    rl = net_r(ev, [ev["twins"]._one(paths[t["si"]], t, 1) for t in trades])
    rs = net_r(ev, [ev["twins"]._one(paths[t["si"]], t, -1) for t in trades])
    return rl, rs


def coin_mean(rl, rs):
    return float(np.mean([np.where(np.random.default_rng(k).random(len(rl)) < 0.5, rl, rs).mean()
                          for k in range(1, COIN_SEEDS + 1)]))


def summarize(r, rs, rl, rsh, kinds, years, rng):
    n = len(r)
    if n == 0:
        return {"n": 0}
    bs = rng.choice(r, (BOOTS, n)).mean(1) if n > 1 else np.array([r[0]])
    c = coin_mean(rl, rsh)
    return {"n": n, "per_year": n / years, "mean_r": float(r.mean()), "stress_r": float(rs.mean()),
            "ci": [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))], "r_per_year": float(r.sum() / years),
            "total_r": float(r.sum()), "coin_r": c, "edge": float(r.mean() - c), "win": float((r > 0).mean()),
            "exits": pd.Series(kinds).value_counts().to_dict()}


def paired(a_days, a_r, b_days, b_r, days, rng):
    """Per-session R sum of a minus b over `days`, with a session bootstrap CI of the total."""
    da = pd.Series(a_r).groupby(list(a_days)).sum() if len(a_r) else pd.Series(dtype=float)
    db = pd.Series(b_r).groupby(list(b_days)).sum() if len(b_r) else pd.Series(dtype=float)
    d = (da.reindex(days).fillna(0) - db.reindex(days).fillna(0)).to_numpy()
    return d


def ci_total(d, rng):
    bs = rng.choice(d, (BOOTS, len(d))).sum(1)
    return [float(np.quantile(bs, .025)), float(np.quantile(bs, .975))]


# --- overnight ------------------------------------------------------------------------------------------------

def sigma_table(sessions, vd, vv):
    """sigma / prior close for every session, by the frozen formula (IVWall._new_day) without the open-inside test."""
    rets, last, meta, prev_day = deque(maxlen=20), None, {}, None
    for s in sessions:
        pc = s.prev_close
        if pc is not None and last is not None:
            rets.append(math.log(pc / last))
        last = pc
        pd_, prev_day = prev_day, s.day
        if pc is None or len(rets) < 20:
            continue
        i = bisect.bisect_left(vd, s.day) - 1
        if i < 0 or (s.day - vd[i]).days > 7:
            continue
        sig = 0.5 * (pc * vv[i] / 100.0 / math.sqrt(252) + pc * float(np.std(np.array(rets), ddof=1)))
        meta[s.day.isoformat()] = {"sigma": sig, "pc": pc, "inside": bool(pc - sig < s.o[0] < pc + sig),
                                   "prev_day": pd_, "vol_late": pd_ is not None and vd[i] > pd_}
    return meta


def overnight_sim(E, p, n_on, flat_j, si, day, sig, pc):
    """OCO stop entries at both walls over the first n_on bars of path p; exits run on to flat_j (exit at its open)."""
    orders = []
    for d in (1, -1):
        wall = pc + d * sig
        stop = wall - d * S_MULT * sig
        tgt = wall + d * TARGET_R * abs(wall - stop)
        orders.append({"side": d, "px": E.snap(wall, up=d > 0), "stop": E.snap(stop, up=d < 0), "target": E.snap(tgt, up=d > 0)})
    out, used, j, n = [], set(), 0, len(p.o)
    while j < n_on and len(used) < 2:
        hits = [(o, E.entry_fill(p.o[j], p.h[j], p.l[j], o["side"], "stop", o["px"])) for o in orders if o["side"] not in used]
        hits = [(o, f) for o, f in hits if f is not None]
        if not hits:
            j += 1
            continue
        hits.sort(key=lambda x: abs(x[0]["px"] - p.o[j]))
        o, f = hits[0]
        d = o["side"]
        used.add(d)
        at_open = f == p.o[j]
        t = {"day": day, "si": si, "side": d, "entry_kind": "stop", "entry_ref": float(f), "stop_init": o["stop"],
             "target": o["target"], "j_entry": j, "at_open": at_open, "entry_mod": int(p.mod[j]),
             "risk_pts": max(abs(f - o["stop"]), 0.25), "gap_through_target": False}
        jx = j
        if at_open and d * (f - o["target"]) >= 0:   # gapped past the target: the bracket's limit fills at once, flat
            r = ("target", f)
            t["gap_through_target"] = True
        else:
            r = E.check_bar(f, p.h[j], p.l[j], d, o["stop"], o["target"], allow_target=at_open)
        while r is None:
            jx += 1
            if jx >= n:
                r, jx = ("flat", p.c[-1]), n - 1
                break
            if jx >= flat_j:
                r = ("flat", p.o[jx])
                break
            r = E.check_bar(p.o[jx], p.h[jx], p.l[jx], d, o["stop"], o["target"], allow_target=True)
        t.update(exit_kind=r[0], exit_ref=float(r[1]), j_exit=jx, exit_mod=int(p.mod[jx]), exit_in_rth=jx >= n_on)
        out.append(t)
        j = jx + 1
    return out


def load_raw(ev, split):
    C, D = ev["config"], ev["data"]
    lo, hi = C.SPLITS[split]
    raw = D._raw(lo - timedelta(days=60), hi, C.PRODUCT)
    raw = raw[~raw.index.duplicated()].sort_index()
    et = raw.index.tz_convert(C.TZ)
    return {"t": (raw.index.asi8 // 1_000_000_000).astype(np.int64), "mod": np.asarray(et.hour * 60 + et.minute).astype(np.int32),
            "inst": raw["instrument_id"].to_numpy(), "o": raw["open"].to_numpy(float), "h": raw["high"].to_numpy(float),
            "l": raw["low"].to_numpy(float), "c": raw["close"].to_numpy(float)}


def one_split(ev, split, vd, vv, rng):
    E, C = ev["engine"], ev["config"]
    warm, trade = ev["data"].load_split(split)
    days = [s.day.isoformat() for s in trade]
    years = len(trade) / 252
    res = {"sessions": len(trade), "years": years, "days": days}

    # frozen + windows
    def run(first, last):
        st = IVHours(first, last, vd, vv)
        tr = E.run(warm, trade, st)["trades"]
        return st, tr
    strat, base = run(0, 71)
    res["frozen"] = base
    res["windows"] = {}
    for m in STOP_AT:
        res["windows"][f"stop_{hm(m)}"] = run(0, (m - 575) // 5 - 1)[1]
    for m in START_AT:
        res["windows"][f"start_{hm(m)}"] = run((m - 575) // 5, 71)[1]
    res["rth_paths"] = dict(enumerate(trade))

    # overnight
    meta = sigma_table(warm + trade, vd, vv)
    for d, m in strat.meta.items():
        assert abs(meta[d]["sigma"] - m["sigma"]) < 1e-9 and meta[d]["inside"], d
    assert sum(m["inside"] for d, m in meta.items() if d in set(days)) == sum(d in set(days) for d in strat.meta)
    raw = load_raw(ev, split)
    paths, hold, f930, skipped = {}, [], [], {"vol_late": 0, "no_bars": 0, "no_sigma": 0}
    elig = 0
    for si, s in enumerate(trade):
        m = meta.get(s.day.isoformat())
        if m is None:
            skipped["no_sigma"] += 1
            continue
        if m["vol_late"]:
            skipped["vol_late"] += 1
            continue
        t0 = int(pd.Timestamp(m["prev_day"]).tz_localize(C.TZ).replace(hour=18).tz_convert("UTC").timestamp())
        a, b = np.searchsorted(raw["t"], t0), np.searchsorted(raw["t"], int(s.t[0]))
        w = np.arange(a, b)
        w = w[raw["inst"][w] == s.inst]
        if not len(w):
            skipped["no_bars"] += 1
            continue
        elig += 1
        p = SimpleNamespace(o=np.concatenate([raw["o"][w], s.o]), h=np.concatenate([raw["h"][w], s.h]),
                            l=np.concatenate([raw["l"][w], s.l]), c=np.concatenate([raw["c"][w], s.c]),
                            mod=np.concatenate([raw["mod"][w], s.mod]))
        n_on = len(w)
        fl = np.flatnonzero(s.mod >= s.close_mod - 5)
        flat_j = n_on + (int(fl[0]) if len(fl) else len(s.o))
        th = overnight_sim(E, p, n_on, flat_j, si, s.day.isoformat(), m["sigma"], m["pc"])
        if th:
            paths[si] = p
            for t in th:
                t["inside"] = m["inside"]
            hold += th
            t9 = overnight_sim(E, p, n_on, n_on, si, s.day.isoformat(), m["sigma"], m["pc"])
            for t in t9:
                t["inside"] = m["inside"]
            f930 += t9
    res.update(on_paths=paths, on_hold=hold, on_flat930=f930, on_skipped=skipped, on_eligible=elig,
               on_touch_days=len({t["day"] for t in hold}),
               open_outside_days=sum(not m["inside"] for d, m in meta.items() if d in set(days)))

    # all-day = overnight HOLD + frozen trades not blocked by it
    by_si = {}
    for t in hold:
        by_si.setdefault(t["si"], []).append(t)
    kept, dropped = [], []
    for t in base:
        on = by_si.get(t["si"], [])
        ok = True
        for e in on:
            if e["side"] == t["side"]:
                ok = False
            elif e["exit_in_rth"] and not (t["entry_mod"] - 570) // 5 > (e["exit_mod"] - 570) // 5:
                ok = False
        (kept if ok else dropped).append(t)
    res["allday_kept"], res["allday_dropped"] = kept, dropped
    return res


def main():
    ev = _ev("NQ")
    vd, vv = load_vol(VOL_CSV["NQ"])
    rng = np.random.default_rng(20261110)
    S = {sp: one_split(ev, sp, vd, vv, rng) for sp in SPLITS}
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "prereg_sha256": hashlib.sha256(PREREG.read_bytes()).hexdigest(),
           "splits": {sp: {"sessions": S[sp]["sessions"], "years": S[sp]["years"], "first": S[sp]["days"][0], "last": S[sp]["days"][-1]}
                      for sp in SPLITS}}

    def pack(key, pathkey, scopes):
        """Per-trade arrays for trade list `key` over the given splits."""
        r, rs, rl, rsh, kinds, days, mods, sides, extra = [], [], [], [], [], [], [], [], []
        for sp in scopes:
            tr = key(S[sp])
            if not tr:
                continue
            a, b = coin_r(ev, S[sp][pathkey], tr)
            r.append(net_r(ev, tr)); rs.append(net_r(ev, tr, "stress")); rl.append(a); rsh.append(b)
            kinds += [t["exit_kind"] for t in tr]; days += [t["day"] for t in tr]; mods += [t["entry_mod"] for t in tr]
            sides += [t["side"] for t in tr]; extra += tr
        cat = lambda x: np.concatenate(x) if x else np.zeros(0)
        return {"r": cat(r), "rs": cat(rs), "rl": cat(rl), "rsh": cat(rsh), "kinds": np.array(kinds), "days": np.array(days),
                "mods": np.array(mods), "sides": np.array(sides), "tr": extra}

    def summ(P, years, mask=None):
        m = np.ones(len(P["r"]), bool) if mask is None else mask
        return summarize(P["r"][m], P["rs"][m], P["rl"][m], P["rsh"][m], P["kinds"][m], years, rng)

    SC = {"all": SPLITS, "2019_26": ("val1", "val2"), "dev": ("dev",), "val1": ("val1",), "val2": ("val2",)}
    yrs = {k: sum(S[sp]["years"] for sp in v) for k, v in SC.items()}
    alldays = {k: [d for sp in v for d in S[sp]["days"]] for k, v in SC.items()}

    # ---- Part A
    A = {"frozen": {}, "buckets": [], "windows": []}
    F = {k: pack(lambda s: s["frozen"], "rth_paths", v) for k, v in SC.items()}
    for k in SC:
        A["frozen"][k] = summ(F[k], yrs[k])
    for lo, hi in BUCKETS:
        row = {"from": hm(lo), "to": hm(hi if hi < 936 else 935)}
        for k in SC:
            row[k] = summ(F[k], yrs[k], (F[k]["mods"] >= lo) & (F[k]["mods"] < hi))
        row["long_n"] = int(((F["all"]["mods"] >= lo) & (F["all"]["mods"] < hi) & (F["all"]["sides"] > 0)).sum())
        A["buckets"].append(row)
    # permutation p: do bucket means differ more than chance (labels shuffled within year)?
    P = F["all"]
    lab = np.searchsorted([b[1] for b in BUCKETS], P["mods"], side="right")
    yr = np.array([d[:4] for d in P["days"]])

    def stat(l):
        return sum((l == b).sum() * (P["r"][l == b].mean() - P["r"].mean()) ** 2 for b in range(len(BUCKETS)) if (l == b).any())
    obs, ge = stat(lab), 0
    for _ in range(5000):
        l2 = lab.copy()
        for y in np.unique(yr):
            ix = np.flatnonzero(yr == y)
            l2[ix] = rng.permutation(lab[ix])
        ge += stat(l2) >= obs
    A["bucket_perm_p"] = (1 + ge) / 5001
    for name in list(S["dev"]["windows"]):
        row = {"name": name}
        for k in SC:
            W = pack(lambda s: s["windows"][name], "rth_paths", SC[k])
            row[k] = summ(W, yrs[k])
            d = paired(W["days"], W["r"], F[k]["days"], F[k]["r"], alldays[k], rng)
            row[k]["paired_total"] = float(d.sum())
            row[k]["paired_ci"] = ci_total(d, rng)
            row[k]["paired_per_year"] = float(d.sum() / yrs[k])
        A["windows"].append(row)
    out["rth"] = A

    # ---- Part B
    B = {"counts": {sp: {"eligible_sessions": S[sp]["on_eligible"], "touch_days": S[sp]["on_touch_days"],
                         "skipped": S[sp]["on_skipped"], "open_outside_days": S[sp]["open_outside_days"]} for sp in SPLITS}}
    for var, key in (("hold", "on_hold"), ("flat930", "on_flat930")):
        B[var] = {}
        for k in SC:
            O = pack(lambda s, key=key: s[key], "on_paths", SC[k])
            B[var][k] = summ(O, yrs[k])
            if k in ("all", "2019_26"):
                ins = np.array([t["inside"] for t in O["tr"]])
                B[var][k]["open_inside"] = summ(O, yrs[k], ins)
                B[var][k]["open_outside"] = summ(O, yrs[k], ~ins)
                B[var][k]["long"] = summ(O, yrs[k], O["sides"] > 0)
                B[var][k]["short"] = summ(O, yrs[k], O["sides"] < 0)
                B[var][k]["by_entry"] = [{"bucket": nm, **summ(O, yrs[k], np.array([f(m) for m in O["mods"]]))} for nm, f in ON_BUCKETS]
                oth = np.array([not any(f(m) for _, f in ON_BUCKETS) for m in O["mods"]])
                B[var][k]["by_entry"].append({"bucket": "other (holiday gap)", **summ(O, yrs[k], oth)})
                B[var][k]["gap_through_target"] = int(sum(t["gap_through_target"] for t in O["tr"]))
                B[var][k]["exit_in_rth"] = int(sum(t["exit_in_rth"] for t in O["tr"]))
                B[var][k]["risk_pts_median"] = float(np.median([t["risk_pts"] for t in O["tr"]]))
    B["allday"] = {}
    for k in SC:
        O = pack(lambda s: s["on_hold"], "on_paths", SC[k])
        K = pack(lambda s: s["allday_kept"], "rth_paths", SC[k])
        r = np.concatenate([O["r"], K["r"]])
        days = np.concatenate([O["days"], K["days"]])
        d = paired(days, r, F[k]["days"], F[k]["r"], alldays[k], rng)
        nd = sum(len(S[sp]["allday_dropped"]) for sp in SC[k])
        dr = float(sum(net_r(ev, S[sp]["allday_dropped"]).sum() for sp in SC[k]))
        B["allday"][k] = {"n": len(r), "per_year": len(r) / yrs[k], "mean_r": float(r.mean()), "r_per_year": float(r.sum() / yrs[k]),
                          "stress_r": float(np.concatenate([O["rs"], K["rs"]]).mean()),
                          "paired_total": float(d.sum()), "paired_ci": ci_total(d, rng), "paired_per_year": float(d.sum() / yrs[k]),
                          "frozen_dropped": nd, "frozen_dropped_r": dr}
    out["overnight"] = B

    # by year
    O = pack(lambda s: s["on_hold"], "on_paths", SPLITS)
    O9 = pack(lambda s: s["on_flat930"], "on_paths", SPLITS)
    rows = []
    for y in sorted({d[:4] for d in alldays["all"]}):
        f = lambda Pk: (int((np.char.startswith(Pk["days"].astype(str), y)).sum()),
                        float(Pk["r"][np.char.startswith(Pk["days"].astype(str), y)].sum()))
        am = F["all"]["mods"]
        fy = np.char.startswith(F["all"]["days"].astype(str), y)
        rows.append({"year": int(y), "frozen_n": f(F["all"])[0], "frozen_r": f(F["all"])[1], "on_n": f(O)[0], "on_r": f(O)[1],
                     "on930_r": f(O9)[1], "am_n": int((fy & (am < 690)).sum()), "am_r": float(F["all"]["r"][fy & (am < 690)].sum()),
                     "pm_n": int((fy & (am >= 690)).sum()), "pm_r": float(F["all"]["r"][fy & (am >= 690)].sum())})
    out["by_year"] = rows
    (OUT / "hours.json").write_text(json.dumps(out, indent=1, default=str))

    # ---- print
    def line(lab, x):
        if not x.get("n"):
            return f"{lab:26s} n   0"
        return (f"{lab:26s} n {x['n']:4d} ({x['per_year']:5.1f}/yr) mean {x['mean_r']:+.3f}R CI [{x['ci'][0]:+.3f},{x['ci'][1]:+.3f}] "
                f"stress {x['stress_r']:+.3f} R/yr {x['r_per_year']:+6.2f} coin {x['coin_r']:+.3f} edge {x['edge']:+.3f} win {x['win']:.0%} {x['exits']}")
    for k in ("all", "2019_26"):
        print(f"\n===== {k} ({yrs[k]:.1f} yr) =====")
        print(line("frozen", A["frozen"][k]))
        for b in A["buckets"]:
            print(line(f"  entry {b['from']}-{b['to']}", b[k]), " | dev/val1/val2", *[f"{b[s]['mean_r']:+.2f}({b[s]['n']})" if b[s].get("n") else "na" for s in SPLITS])
        for w in A["windows"]:
            x = w[k]
            print(line(f"  {w['name']}", x), f"| paired {x['paired_total']:+.1f}R CI [{x['paired_ci'][0]:+.1f},{x['paired_ci'][1]:+.1f}]",
                  "signs", *[f"{w[s]['paired_total']:+.1f}" for s in SPLITS])
        for var in ("hold", "flat930"):
            x = B[var][k]
            print(line(f"overnight {var}", x), f"| gap>target {x['gap_through_target']} exit in RTH {x['exit_in_rth']} risk med {x['risk_pts_median']:.0f}")
            for nm in ("open_inside", "open_outside", "long", "short"):
                print(line(f"    {nm}", x[nm]))
            for e in x["by_entry"]:
                print(line(f"    entry {e['bucket']}", e))
        x = B["allday"][k]
        print(f"all-day: n {x['n']} mean {x['mean_r']:+.3f} stress {x['stress_r']:+.3f} R/yr {x['r_per_year']:+.2f} | paired vs frozen {x['paired_total']:+.1f}R "
              f"CI [{x['paired_ci'][0]:+.1f},{x['paired_ci'][1]:+.1f}] dropped frozen {x['frozen_dropped']} ({x['frozen_dropped_r']:+.1f}R)")
    print(f"\nbucket permutation p (2011-26) {A['bucket_perm_p']:.3f}")
    for sp in SPLITS:
        print(sp, line("frozen", A["frozen"][sp]))
        print(sp, line("overnight hold", B["hold"][sp]))
        print(sp, line("overnight flat930", B["flat930"][sp]), B["counts"][sp])
        x = B["allday"][sp]
        print(sp, f"all-day paired {x['paired_total']:+.1f} CI [{x['paired_ci'][0]:+.1f},{x['paired_ci'][1]:+.1f}]")
    for y in rows:
        print(y)


if __name__ == "__main__":
    main()
