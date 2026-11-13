"""Single-candle scalp of the frozen NQ IV-wall break (prereg iv_wall_scalp_prereg.json). Information only on spent NQ.

Same trigger as IVGrid("touch", "fixed", 0.4): stop entry at the nearer fresh wall, 09:35-15:30 ET, one trade per wall per
day. Exit with a market order when the candle the fill happened in closes:
    C1_* : the 1m candle (exit at the next 1m open)      C5_* : the 5m candle (exit at the next 5m bar's first 1m open)
    *_nostop : no stop inside the candle                 *_stop10 : stop at wall - d x 0.10 sigma
R unit = 0.10 sigma for all four (a notional stop for the no-stop variants).

    cd functions/ml && ../../.venv/bin/python -B iv_wall_scalp.py parity     # frozen exits must reproduce val2 (n 392)
    cd functions/ml && ../../.venv/bin/python -B iv_wall_scalp.py nq         # 4 variants, dev/val1/val2/fresh + ticks
    cd functions/ml && ../../.venv/bin/python -B iv_wall_scalp.py lucid      # Flex 50K at 1 and 4 MNQ vs random side

Outputs: data/iv_wall/scalp_nq.json, scalp_ticks.json, scalp_lucid.json (+ .log via tee).
"""
from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from iv_wall_grid import IVGrid, OUT, VOL_CSV, _ev
from iv_wall_study import load_vol

FROZEN = {"name": "frozen", "s": 0.4, "candle": None, "live_stop": True, "target": True}
VARIANTS = [
    {"name": "C1_nostop", "s": 0.10, "candle": 1, "live_stop": False, "target": False},
    {"name": "C1_stop10", "s": 0.10, "candle": 1, "live_stop": True, "target": False},
    {"name": "C5_nostop", "s": 0.10, "candle": 5, "live_stop": False, "target": False},
    {"name": "C5_stop10", "s": 0.10, "candle": 5, "live_stop": True, "target": False},
]
TICK_LO, TICK_HI = date(2025, 10, 24), date(2026, 8, 14)
FRESH_LO, FRESH_HI = date(2026, 8, 17), date(2026, 11, 3)
TICK_DIR = OUT.parent / "databento" / "nq-trades" / "NQ"
PAPER_SESSIONS = OUT / "paper" / "sessions.csv"
EV = _ev("NQ")
C, ENG, COSTS, TW, CRIT, DATA = (EV[k] for k in ("config", "engine", "costs", "twins", "criteria", "data"))


class Scalp(IVGrid):
    """IVGrid touch entry with s = 0.10 sigma and no target (exit is the candle close)."""

    def __init__(self, s, vd, vv):
        super().__init__("touch", "fixed", s, vd, vv)

    def _enter(self, w, typ, c, price=None):
        act = super()._enter(w, typ, c, price)
        act["target"] = None
        return act


def make_strat(v, vd, vv):
    return IVGrid("touch", "fixed", v["s"], vd, vv) if v["target"] else Scalp(v["s"], vd, vv)


# --- 1m engine: research_loop_nq engine._run_session + the candle exit + an optional notional stop -----------------

@dataclass
class Pos:
    side: int
    entry_kind: str
    entry_ref: float
    stop: float
    stop_init: float
    target: float | None
    j_entry: int
    at_open: bool
    k_entry: int
    exit_j: int | None


def flat_index(s) -> int | None:
    """1m index of the flat bar's open (first 1m bar of the session's last 5m slot), or None if that bar is missing."""
    b = s.b5
    ks = np.flatnonzero(b["slot"] >= s.flat_slot)
    return int(b["a"][ks[0]]) if len(ks) else None


def planned_exit(s, j: int, k: int, candle: int | None) -> int | None:
    if candle is None:
        return None
    if candle == 1:
        return j + 1 if j + 1 < len(s.o) else None
    return int(s.b5["a"][k + 1]) if k + 1 < len(s.b5["slot"]) else None


def _close(trades, s, si, p: Pos, j: int, kind: str, ref: float, live_stop: bool) -> None:
    trades.append({
        "day": s.day.isoformat(), "si": si, "side": p.side, "entry_kind": p.entry_kind, "entry_ref": p.entry_ref,
        "stop_init": p.stop_init, "target": p.target, "j_entry": p.j_entry, "at_open": p.at_open,
        "entry_mod": int(s.mod[p.j_entry]), "exit_kind": kind, "exit_ref": float(ref), "j_exit": j,
        "exit_mod": int(s.mod[j]), "risk_pts": max(abs(p.entry_ref - p.stop_init), C.TICK),
        "j_plan": p.exit_j, "live_stop": live_stop,
    })


def run_1m(warm, sessions, strat, candle=None, live_stop=True) -> list[dict]:
    trades: list[dict] = []
    for w, group in ((True, warm), (False, sessions)):
        for si, s in enumerate(group):
            _session(s, si, strat, w, trades, candle, live_stop)
    return trades


def _session(s, si, strat, warm, trades, candle, live_stop) -> None:
    b = s.b5
    nb = len(b["slot"])
    pos = pend = act = None
    for k in range(nb):
        a, z = int(b["a"][k]), int(b["b"][k])
        slot = int(b["slot"][k])
        if not warm:
            flat = slot >= s.flat_slot
            if flat:
                pend = None
                if pos is not None:
                    _close(trades, s, si, pos, a, "flat", s.o[a], live_stop)
                    pos = None
                act = None
            elif act is not None:
                op = act.get("op")
                if op == "enter":
                    if pos is None:
                        if act["type"] != "stop":
                            raise RuntimeError(f"unexpected entry type {act}")
                        pend = {**act, "left": act["ttl"]}
                elif op == "exit":
                    pend = None
                    if pos is not None:
                        _close(trades, s, si, pos, a, "market", s.o[a], live_stop)
                        pos = None
                elif op == "stop":
                    if pos is not None:
                        pos.stop = act["price"]
                elif op == "cancel":
                    pend = None
                act = None
            if not flat:
                for j in range(a, z + 1):
                    o, h, l = s.o[j], s.h[j], s.l[j]
                    if pos is not None and pos.exit_j is not None and j >= pos.exit_j:
                        _close(trades, s, si, pos, j, "market", o, live_stop)  # candle close: market at this open
                        pos = None
                        continue
                    if pos is None and pend is not None:
                        f = ENG.entry_fill(o, h, l, pend["side"], pend["type"], float(pend["price"]))
                        if f is None:
                            continue
                        pos = Pos(pend["side"], pend["type"], float(f), pend["stop"], pend["stop"], pend["target"], j,
                                  f == o, k, planned_exit(s, j, k, candle))
                        pend = None
                        r = ENG.check_bar(f, h, l, pos.side, pos.stop, pos.target, allow_target=pos.at_open) if live_stop else None
                    elif pos is not None:
                        first = j == pos.j_entry
                        r = ENG.check_bar(o, h, l, pos.side, pos.stop, pos.target,
                                          allow_target=(not first) or pos.at_open) if live_stop else None
                    else:
                        continue
                    if r is not None:
                        _close(trades, s, si, pos, j, *r, live_stop)
                        pos = None
                if pend is not None:
                    pend["left"] -= 1
                    if pend["left"] <= 0:
                        pend = None
        bar = ENG._bar_dict(s, k, warm)
        pd_ = None if pos is None else {"side": pos.side, "entry_px": pos.entry_ref, "stop": pos.stop,
                                        "target": pos.target, "bars_held": k - pos.k_entry}
        out = strat.on_bar(bar, pd_)
        if warm or out is None:
            continue
        out = ENG.normalize(out, float(b["c"][k]), pd_)
        if k + 1 < nb and int(b["slot"][k + 1]) < s.flat_slot:
            act = out
        elif out.get("op") == "exit":
            act = None
    if pos is not None and not warm:
        _close(trades, s, si, pos, len(s.c) - 1, "flat", s.c[-1], live_stop)


# --- twins ---------------------------------------------------------------------------------------------------------

def _scalp_twin(s, t: dict, d: int) -> dict:
    """The same trade taken on side d under the scalp's own rules: same fill minute and price, same candle exit,
    mirrored stop at the same distance if the variant has one."""
    ref, risk = t["entry_ref"], t["risk_pts"]
    stop = ref - d * risk
    j0 = t["j_entry"]
    fl = flat_index(s)
    plan = t["j_plan"]
    cands = [x for x in (plan, fl) if x is not None]
    j_end = min(cands) if cands else None
    end_kind = "flat" if j_end is not None and j_end == fl and (plan is None or fl <= plan) else "market"
    last = (j_end - 1) if j_end is not None else len(s.o) - 1
    if t["live_stop"]:
        for j in range(j0, last + 1):
            first = j == j0
            o = ref if (first and not t["at_open"]) else s.o[j]
            r = ENG.check_bar(o, s.h[j], s.l[j], d, stop, None, allow_target=False)
            if r is not None:
                return {**t, "side": d, "stop_init": stop, "exit_kind": r[0], "exit_ref": float(r[1]), "j_exit": j,
                        "exit_mod": int(s.mod[j])}
    if j_end is None:
        jx = len(s.c) - 1
        return {**t, "side": d, "stop_init": stop, "exit_kind": "flat", "exit_ref": float(s.c[-1]), "j_exit": jx,
                "exit_mod": int(s.mod[jx])}
    return {**t, "side": d, "stop_init": stop, "exit_kind": end_kind, "exit_ref": float(s.o[j_end]), "j_exit": j_end,
            "exit_mod": int(s.mod[j_end])}


def twin_trades(sessions, trades, v) -> tuple[list, list]:
    if v["target"]:  # frozen exits: the evaluator's twins
        return ([TW._one(sessions[t["si"]], t, 1) for t in trades], [TW._one(sessions[t["si"]], t, -1) for t in trades])
    return ([_scalp_twin(sessions[t["si"]], t, 1) for t in trades], [_scalp_twin(sessions[t["si"]], t, -1) for t in trades])


def check_twin_identity(sessions, trades, v) -> int:
    """The twin on the real side must reproduce the real trade (same rules); returns the number of mismatches."""
    if v["target"]:
        return 0
    bad = 0
    for t in trades:
        u = _scalp_twin(sessions[t["si"]], t, t["side"])
        if u["exit_kind"] != t["exit_kind"] or abs(u["exit_ref"] - t["exit_ref"]) > 1e-9 or u["j_exit"] != t["j_exit"]:
            bad += 1
    return bad


# --- metrics -------------------------------------------------------------------------------------------------------

def sigma_today() -> tuple[float, str]:
    df = pd.read_csv(PAPER_SESSIONS)
    df = df.dropna(subset=["sigma"])
    return float(df["sigma"].iloc[-1]), str(df["date"].iloc[-1])


def drawdown(r: np.ndarray, days: np.ndarray) -> dict:
    if not len(r):
        return {"max_dd_r": 0.0, "from": None, "to": None, "longest_losing_streak": 0}
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    dd = peak - eq
    i = int(dd.argmax())
    pk = int(np.flatnonzero(eq[:i + 1] >= peak[i] - 1e-12)[0]) if dd[i] > 0 and (eq[:i + 1] >= peak[i] - 1e-12).any() else None
    streak = best = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    return {"max_dd_r": float(dd[i]), "from": None if pk is None else str(days[pk]), "to": str(days[i]),
            "longest_losing_streak": best}


def metrics(parts: list[dict], v: dict, sig_today: float, n_trials: int = 1, twins: bool = True) -> dict:
    tr = [t for p in parts for t in p["trades"]]
    sess = [d for p in parts for d in p["sess"]]
    if not tr:
        return {"trades": 0}
    base, stress = COSTS.apply(tr, "base"), COSTS.apply(tr, "stress")
    r, usd, rs = base["r"], base["usd"], stress["r"]
    days = np.array([t["day"] for t in tr], dtype=object).astype(str)
    sides = np.array([t["side"] for t in tr])
    risk = np.array([t["risk_pts"] for t in tr])
    gross_pts = base["gross_pts"]
    if twins:
        rl = np.concatenate([p["rl"] for p in parts])
        rsh = np.concatenate([p["rsh"] for p in parts])
        tw = TW.twin_test(r, rl, rsh, sides=list(sides))
    else:
        tw = {"p": float("nan"), "p_coin": float("nan"), "twin_mean": float("nan")}
    m = CRIT.summarize(r, usd, rs, days, sess, tw, n_trials)
    cost_usd = gross_pts * C.POINT_VALUE - usd
    unit_today = v["s"] * sig_today * C.POINT_VALUE
    hold = np.array([t["exit_mod"] - t["entry_mod"] for t in tr], dtype=float)
    years = len(sess) / 252.0
    m.update({
        "trades_per_year": len(tr) / years if years else float("nan"),
        "gross_r": float((gross_pts / risk).mean()),
        "gross_pts": float(gross_pts.mean()),
        "risk_pts_median": float(np.median(risk)),
        "today_cost_r": float((gross_pts / risk - cost_usd / unit_today).mean()),
        "cost_r_mean": float((cost_usd / (risk * C.POINT_VALUE)).mean()),
        "exit_kinds": {k: int(sum(t["exit_kind"] == k for t in tr)) for k in ("market", "stop", "target", "flat")},
        "hold_min_mean": float(hold.mean()),
        "long_r": float(r[sides > 0].mean()) if (sides > 0).any() else float("nan"),
        "short_r": float(r[sides < 0].mean()) if (sides < 0).any() else float("nan"),
        "n_long": int((sides > 0).sum()),
        "edge_over_twins": float(r.mean() - tw["twin_mean"]) if twins else float("nan"),
        **drawdown(r, days),
    })
    return m


def line(name, m):
    if not m.get("trades"):
        return f"{name:10s} n=0"
    tw = m["twin"]
    return (f"{name:10s} n={m['trades']:4d} ({m['trades_per_year']:5.1f}/yr) gross={m['gross_r']:+.3f} net={m['mean_r_base']:+.3f} "
            f"CI[{m['ci_base'][0]:+.3f},{m['ci_base'][1]:+.3f}] stress={m['mean_r_stress']:+.3f} today={m['today_cost_r']:+.3f} "
            f"win={m['win_rate']:.2f} edge={m['edge_over_twins']:+.3f} p={tw['p']:.4f} DD={m['max_dd_r']:.1f}R "
            f"L/S {m['long_r']:+.2f}/{m['short_r']:+.2f} hold={m['hold_min_mean']:.1f}m")


def run_part(warm, trade, v, vd, vv) -> dict:
    strat = make_strat(v, vd, vv)
    tr = run_1m(warm, trade, strat, v["candle"], v["live_stop"])
    lg, sh = twin_trades(trade, tr, v)
    bad = check_twin_identity(trade, tr, v)
    if bad:
        raise RuntimeError(f"{v['name']}: {bad} twins on the real side do not reproduce the real trade")
    return {"trades": tr, "sess": [s.day.isoformat() for s in trade], "lg": lg, "sh": sh,
            "rl": COSTS.apply(lg, "base")["r"], "rsh": COSTS.apply(sh, "base")["r"], "meta": strat.meta}


# --- commands ------------------------------------------------------------------------------------------------------

def parity():
    vd, vv = load_vol(VOL_CSV["NQ"])
    warm, trade = DATA.load_split("val2")
    mine = run_1m(warm, trade, IVGrid("touch", "fixed", 0.4, vd, vv))
    ref = ENG.run(warm, trade, IVGrid("touch", "fixed", 0.4, vd, vv))["trades"]
    keys = ("day", "side", "entry_ref", "stop_init", "target", "j_entry", "exit_kind", "exit_ref", "j_exit", "risk_pts")
    same = len(mine) == len(ref) and all(all(a[k] == b[k] for k in keys) for a, b in zip(mine, ref))
    r = COSTS.apply(mine, "base")["r"]
    saved = json.loads((OUT / "grid_NQ_val2.json").read_text())["metrics"]
    print(f"parity: mine n={len(mine)} R={r.mean():+.4f} | engine n={len(ref)} | saved n={saved['trades']} "
          f"R={saved['mean_r_base']:+.4f} | trade-by-trade identical: {same}")
    if not (same and len(mine) == saved["trades"] and abs(r.mean() - saved["mean_r_base"]) < 1e-9):
        raise SystemExit("PARITY FAILED")
    print("PARITY OK")


def fresh_split():
    ses = DATA.load_window(FRESH_LO - timedelta(days=70), FRESH_HI)
    first = next(i for i, s in enumerate(ses) if s.day >= FRESH_LO)
    return ses[max(0, first - C.WARMUP_SESSIONS - 10):first], ses[first:]


def nq():
    vd, vv = load_vol(VOL_CSV["NQ"])
    sig, sig_day = sigma_today()
    print(f"sigma_today {sig:.2f} ({sig_day}); 0.10 sigma = {0.1 * sig:.1f} pts, 0.4 sigma = {0.4 * sig:.1f} pts", flush=True)
    configs = [FROZEN] + VARIANTS
    parts = {}
    for split in ("dev", "val1", "val2"):
        warm, trade = DATA.load_split(split)
        for v in configs:
            parts[(split, v["name"])] = run_part(warm, trade, v, vd, vv)
        print(f"{split} done", flush=True)
    warm, trade = fresh_split()
    for v in configs:
        parts[("fresh", v["name"])] = run_part(warm, trade, v, vd, vv)
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "sigma_today": sig, "sigma_today_date": sig_day,
           "prereg": "iv_wall_scalp_prereg.json", "status": "SPENT NQ: information only (fresh = information, ~12 trigger days)",
           "variants": {}}
    for v in configs:
        res = {}
        for split in ("dev", "val1", "val2", "fresh"):
            res[split] = metrics([parts[(split, v["name"])]], v, sig, len(VARIANTS))
        res["pooled_2019_26"] = metrics([parts[("val1", v["name"])], parts[("val2", v["name"])]], v, sig, len(VARIANTS))
        res["pooled_2011_26"] = metrics([parts[(sp, v["name"])] for sp in ("dev", "val1", "val2")], v, sig, len(VARIANTS))
        res["fresh_trades"] = [{k: t[k] for k in ("day", "side", "entry_ref", "exit_kind", "exit_ref", "risk_pts", "entry_mod",
                                                  "exit_mod")} for t in parts[("fresh", v["name"])]["trades"]]
        out["variants"][v["name"]] = {"config": v, **res}
        print(f"\n== {v['name']}")
        for k in ("dev", "val1", "val2", "pooled_2019_26", "pooled_2011_26", "fresh"):
            print(line(k, res[k]))
        print("by year", {y: (d["n"], round(d["mean_r"], 3)) for y, d in res["pooled_2011_26"]["by_year"].items()})
    (OUT / "scalp_nq.json").write_text(json.dumps(out, indent=1, default=float))
    ticks(parts, vd, vv, sig)


# --- tick replay ---------------------------------------------------------------------------------------------------

def load_prints(s) -> tuple[np.ndarray, np.ndarray] | None:
    f = TICK_DIR / f"{s.day.isoformat()}_{(s.day + timedelta(days=1)).isoformat()}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f, columns=["ts_event", "price", "instrument_id"]).reset_index(drop=True)
    df = df[df["instrument_id"] == s.inst].sort_values("ts_event", kind="stable")
    if df.empty:
        return None
    return df["ts_event"].astype("int64").to_numpy(), df["price"].to_numpy(dtype=float)


def _first(mask: np.ndarray) -> int | None:
    i = int(mask.argmax()) if len(mask) else 0
    return i if len(mask) and mask[i] else None


def run_ticks(warm, sessions, prints, strat, v) -> list[dict]:
    """Same trigger and 5m decisions; fills and exits on Databento prints. prints[day] = (t_ns, px)."""
    trades = []
    for s in warm:
        for k in range(len(s.b5["slot"])):
            strat.on_bar(ENG._bar_dict(s, k, True), None)
    for si, s in enumerate(sessions):
        T, P = prints[s.day]
        b = s.b5
        nb = len(b["slot"])
        starts = b["t"].astype(np.int64) * 1_000_000_000
        pos = act = None
        for k in range(nb):
            slot = int(b["slot"][k])
            t0 = int(starts[k])
            t1 = int(starts[k + 1]) if k + 1 < nb else t0 + 300 * 10**9
            i0, i1 = int(np.searchsorted(T, t0)), int(np.searchsorted(T, t1))
            if slot >= s.flat_slot:
                act = None
                if pos is not None:
                    i = min(i0, len(P) - 1)
                    trades.append(_tick_close(s, si, pos, T[i], "flat", P[i], v))
                    pos = None
            else:
                pend = act if (act is not None and act.get("op") == "enter" and pos is None) else None
                act = None
                i = i0
                if pend is not None:
                    d, px = pend["side"], float(pend["price"])
                    seg = P[i0:i1]
                    f = _first(seg >= px if d > 0 else seg <= px)
                    if f is not None:
                        i = i0 + f
                        tf = int(T[i])
                        if v["candle"] == 1:
                            ex = (tf // 60_000_000_000 + 1) * 60_000_000_000
                        elif v["candle"] == 5:
                            ex = t1
                        else:
                            ex = None
                        pos = {"side": d, "entry_ref": float(P[i]), "t_entry": tf, "exit_t": ex, "k_entry": k,
                               "stop": pend["stop"], "target": pend["target"]}
                        i += 1
                if pos is not None:
                    pos, closed = _tick_walk(s, si, pos, T, P, i, i1, v)
                    if closed is not None:
                        trades.append(closed)
            bar = ENG._bar_dict(s, k, False)
            pd_ = None if pos is None else {"side": pos["side"], "entry_px": pos["entry_ref"], "stop": pos["stop"],
                                            "target": pos["target"], "bars_held": k - pos["k_entry"]}
            out = strat.on_bar(bar, pd_)
            if out is None:
                continue
            out = ENG.normalize(out, float(b["c"][k]), pd_)
            if k + 1 < nb and int(b["slot"][k + 1]) < s.flat_slot:
                act = out
        if pos is not None:
            trades.append(_tick_close(s, si, pos, T[-1], "flat", P[-1], v))
    return trades


def _mod(t_ns: int) -> int:
    ts = pd.Timestamp(t_ns, tz="UTC").tz_convert(C.TZ)
    return ts.hour * 60 + ts.minute


def _tick_close(s, si, pos, t_ns, kind, px, v) -> dict:
    return {"day": s.day.isoformat(), "si": si, "side": pos["side"], "entry_kind": "stop", "entry_ref": pos["entry_ref"],
            "stop_init": pos["stop"], "target": pos["target"], "entry_mod": _mod(pos["t_entry"]), "exit_kind": kind,
            "exit_ref": float(px), "exit_mod": _mod(int(t_ns)), "risk_pts": max(abs(pos["entry_ref"] - pos["stop"]), C.TICK),
            "hold_s": (int(t_ns) - pos["t_entry"]) / 1e9}


def _tick_walk(s, si, pos, T, P, i, i1, v):
    """Walk prints [i, i1) of the current 5m bar with a position open. Returns (pos or None, closed trade or None)."""
    if i >= i1:
        return pos, None
    d, seg = pos["side"], P[i:i1]
    cands = []
    if pos["exit_t"] is not None:
        e = int(np.searchsorted(T, pos["exit_t"]))
        if e < i1:
            cands.append((max(e, i) - i, 1, "market"))
    if v["live_stop"]:
        f = _first(seg <= pos["stop"] if d > 0 else seg >= pos["stop"])
        if f is not None:
            cands.append((f, 0, "stop"))
    if pos["target"] is not None:
        f = _first(seg >= pos["target"] + C.TICK if d > 0 else seg <= pos["target"] - C.TICK)
        if f is not None:
            cands.append((f, 2, "target"))
    if not cands:
        return pos, None
    f, _, kind = min(cands)
    px = pos["target"] if kind == "target" else P[i + f]
    return None, _tick_close(s, si, pos, T[i + f], kind, px, v)


def ticks(parts, vd, vv, sig):
    warm_all, trade_all = DATA.load_split("val2")
    win = [s for s in trade_all if TICK_LO <= s.day <= TICK_HI]
    prints, missing = {}, []
    for s in win:
        p = load_prints(s)
        if p is None:
            missing.append(s.day.isoformat())
        else:
            prints[s.day] = p
    first = trade_all.index(win[0])
    warm = trade_all[max(0, first - 30):first]
    covered = [s for s in win if s.day in prints]
    if missing:  # a gap breaks the HV chain; drop it from both engines instead of feeding a partial day
        print(f"tick window: {len(missing)} sessions without prints dropped: {missing[:8]}...", flush=True)
    covered_days = {s.day.isoformat() for s in covered}
    out = {"ran": datetime.now().isoformat(timespec="seconds"), "window": [TICK_LO.isoformat(), TICK_HI.isoformat()],
           "sessions": len(covered), "missing_sessions": missing, "variants": {}}
    print(f"\n== tick replay {TICK_LO}..{TICK_HI}: {len(covered)} sessions", flush=True)
    for v in [FROZEN] + VARIANTS:
        strat = make_strat(v, vd, vv)
        # feed every session (no prints needed for warm/no-trade decisions) so the HV chain matches the 1m run
        tt = run_ticks(warm, win, {**{s.day: (np.zeros(0, np.int64), np.zeros(0)) for s in win}, **prints}, strat, v)
        for d, mt in strat.meta.items():
            m1 = parts[("val2", v["name"])]["meta"].get(d)
            if m1 is not None and abs(m1["sigma"] - mt["sigma"]) > 1e-9:
                raise RuntimeError(f"sigma mismatch {d}")
        tt = [t for t in tt if t["day"] in covered_days]
        t1 = [t for t in parts[("val2", v["name"])]["trades"] if t["day"] in covered_days]
        r_tick = COSTS.apply(tt, "base")["r"] if tt else np.zeros(0)
        r_1m = COSTS.apply(t1, "base")["r"] if t1 else np.zeros(0)
        rs_tick = COSTS.apply(tt, "stress")["r"] if tt else np.zeros(0)
        n = len(t1)
        b = (r_tick.sum() - r_1m.sum()) / n if n else float("nan")
        # paired per-session bootstrap of b
        days = sorted(covered_days)
        pos = {d: i for i, d in enumerate(days)}
        st, s1 = np.zeros(len(days)), np.zeros(len(days))
        for t, x in zip(tt, r_tick):
            st[pos[t["day"]]] += x
        for t, x in zip(t1, r_1m):
            s1[pos[t["day"]]] += x
        c1 = np.zeros(len(days))
        for t in t1:
            c1[pos[t["day"]]] += 1
        rng = np.random.default_rng(C.SEED)
        idx = rng.integers(0, len(days), size=(C.N_BOOT, len(days)))
        bs = (st[idx] - s1[idx]).sum(1) / np.maximum(c1[idx].sum(1), 1)
        k1 = {(t["day"], t["side"]): t["exit_kind"] for t in t1}
        kt = {(t["day"], t["side"]): t["exit_kind"] for t in tt}
        common = set(k1) & set(kt)
        differ = sum(k1[x] != kt[x] for x in common)
        row = {"n_1m": n, "n_tick": len(tt), "r_1m": float(r_1m.mean()) if n else float("nan"),
               "r_tick": float(r_tick.mean()) if len(tt) else float("nan"),
               "r_tick_stress": float(rs_tick.mean()) if len(tt) else float("nan"),
               "b": float(b), "b_ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
               "same_trades": len(common), "exit_kind_differs": differ,
               "exit_kinds_tick": {k: int(sum(t["exit_kind"] == k for t in tt)) for k in ("market", "stop", "target", "flat")},
               "exit_kinds_1m": {k: int(sum(t["exit_kind"] == k for t in t1)) for k in ("market", "stop", "target", "flat")},
               "hold_s_mean_tick": float(np.mean([t["hold_s"] for t in tt])) if tt else float("nan")}
        out["variants"][v["name"]] = row
        print(f"{v['name']:10s} 1m n={n} R={row['r_1m']:+.3f} | ticks n={len(tt)} R={row['r_tick']:+.3f} "
              f"(stress {row['r_tick_stress']:+.3f}) | b={b:+.3f} CI[{row['b_ci'][0]:+.3f},{row['b_ci'][1]:+.3f}] "
              f"| exit kind differs {differ}/{len(common)} | hold {row['hold_s_mean_tick']:.0f}s", flush=True)
    (OUT / "scalp_ticks.json").write_text(json.dumps(out, indent=1, default=float))


# --- Lucid ---------------------------------------------------------------------------------------------------------

def _prop_job(args):
    from flybrain.prop import run_prop
    res, time, plan, paths, seed = args
    b = run_prop(res, time, plan=plan, initial_capital=50000, paths=paths, seed=seed,
                 keep_attempts=False, replay_history=False)["bootstrap"]
    return {k: float(b[k]) for k in ("ev", "passRate", "pPayout", "meanTake", "medianDaysToPass")}


def lucid(paths: int, seeds: int):
    import iv_wall_lucid_today as LT
    from flybrain.prop import resolve_plan
    plan = resolve_plan("flex", "50k", True)
    vd, vv = load_vol(VOL_CSV["NQ"])
    sig, sig_day = sigma_today()
    warm, trade = DATA.load_split("val2")
    LT._S["trade"] = trade
    cells = [(FROZEN, 1)] + [(v, n) for v in VARIANTS for n in (1, 4)]
    jobs, keys = [], []
    for v, n in cells:
        p = run_part(warm, trade, v, vd, vv)
        tr = p["trades"]
        risk = n * v["s"] * sig * C.POINT_VALUE
        real = COSTS.apply(tr, "base")["usd"]
        ul, us = COSTS.apply(p["lg"], "base")["usd"], COSTS.apply(p["sh"], "base")["usd"]
        res, time = LT.series(tr, real, risk)
        jobs.append((res, time, plan, paths, 42)); keys.append((v["name"], n, 0, risk))
        for sd in range(1, seeds + 1):
            c = np.random.default_rng(sd).random(len(tr)) < 0.5
            tw = [a if x else z for x, a, z in zip(c, p["lg"], p["sh"])]
            res, time = LT.series(tw, np.where(c, ul, us), risk)
            jobs.append((res, time, plan, paths, 42 + sd)); keys.append((v["name"], n, sd, risk))
    print(f"{len(jobs)} prop runs, sigma_today {sig:.1f}", flush=True)
    rows = {}
    with ProcessPoolExecutor() as ex:
        for (name, n, sd, risk), r in zip(keys, ex.map(_prop_job, jobs, chunksize=2)):
            c = rows.setdefault((name, n), {"variant": name, "mnq": n, "risk_usd": risk, "coin_runs": []})
            if sd == 0:
                c["real"] = r
            else:
                c["coin_runs"].append(r)
    out_rows = []
    for c in rows.values():
        runs = c.pop("coin_runs")
        c["coin"] = {k: float(np.nanmean([x[k] for x in runs])) for k in runs[0]}
        c["coin"]["ev_sd"] = float(np.std([x["ev"] for x in runs], ddof=1))
        c["edge"] = c["real"]["ev"] - c["coin"]["ev"]
        out_rows.append(c)
        print(f"{c['variant']:10s} {c['mnq']} MNQ (${c['risk_usd']:.0f}/trade): EV {c['real']['ev']:+6.0f} pass {c['real']['passRate']:.0%} "
              f"payout {c['real']['pPayout']:.0%} | coin EV {c['coin']['ev']:+6.0f} (sd {c['coin']['ev_sd']:.0f}) | edge {c['edge']:+6.0f}",
              flush=True)
    (OUT / "scalp_lucid.json").write_text(json.dumps({"ran": datetime.now().isoformat(timespec="seconds"), "sigma_today": sig,
                                                      "sigma_today_date": sig_day, "paths": paths, "seeds": seeds,
                                                      "plan": "lucid flex 50k dll", "trades": "NQ val2 (spent: information)",
                                                      "rows": out_rows}, indent=1, default=float))


# --- forward journal -------------------------------------------------------------------------------------------------

PAPER = OUT / "scalp_paper" / "trades.csv"
PAPER_COLS = ["variant", "date", "source", "side", "entry_et", "entry", "exit_kind", "exit_et", "exit", "risk_pts",
              "sigma", "gross_pts", "net_r_base", "net_r_stress", "net_usd_1mnq", "logged_at"]


def _et(mod: int) -> str:
    return f"{mod // 60:02d}:{mod % 60:02d}"


def paper():
    """Append every variant's trades from 2026-08-17 on Databento 1m bars on disk (append-only, no rewrites)."""
    vd, vv = load_vol(VOL_CSV["NQ"])
    ses = DATA.load_window(FRESH_LO - timedelta(days=70), date.today())
    first = next(i for i, s in enumerate(ses) if s.day >= FRESH_LO)
    warm, trade = ses[max(0, first - C.WARMUP_SESSIONS - 10):first], ses[first:]
    old = pd.read_csv(PAPER) if PAPER.exists() else pd.DataFrame(columns=PAPER_COLS)
    have = set(zip(old["variant"], old["date"], old["entry_et"]))
    last_day = old["date"].max() if len(old) else None
    rows, now = [], datetime.now().isoformat(timespec="seconds")
    for v in VARIANTS:
        strat = make_strat(v, vd, vv)
        tr = run_1m(warm, trade, strat, v["candle"], v["live_stop"])
        if not tr:
            continue
        base, stress = COSTS.apply(tr, "base"), COSTS.apply(tr, "stress")
        for t, r, rs, u, g in zip(tr, base["r"], stress["r"], base["usd"], base["gross_pts"]):
            key = (v["name"], t["day"], _et(t["entry_mod"]))
            if key in have or (last_day is not None and t["day"] <= last_day):
                continue  # append-only: sessions already journalled are never rewritten
            rows.append({"variant": v["name"], "date": t["day"], "source": "databento", "side": t["side"],
                         "entry_et": _et(t["entry_mod"]), "entry": t["entry_ref"], "exit_kind": t["exit_kind"],
                         "exit_et": _et(t["exit_mod"]), "exit": t["exit_ref"], "risk_pts": round(t["risk_pts"], 2),
                         "sigma": round(strat.meta[t["day"]]["sigma"], 2), "gross_pts": float(g), "net_r_base": round(float(r), 4),
                         "net_r_stress": round(float(rs), 4), "net_usd_1mnq": round(float(u), 2), "logged_at": now})
    PAPER.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows, columns=PAPER_COLS).sort_values(["date", "variant"], kind="stable")
    new.to_csv(PAPER, mode="a", header=not PAPER.exists(), index=False)
    allr = pd.concat([old, new]) if len(old) else new
    print(f"appended {len(new)} rows (bars through {trade[-1].day}); journal {len(allr)} rows")
    for name, g in allr.groupby("variant"):
        print(f"  {name:10s} n={len(g):3d} net R={g['net_r_base'].mean():+.3f} stress={g['net_r_stress'].mean():+.3f} "
              f"$/MNQ total={g['net_usd_1mnq'].sum():+.0f}  ({len(g)}/100 toward the gate)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("parity")
    sub.add_parser("nq")
    sub.add_parser("paper")
    lp = sub.add_parser("lucid")
    lp.add_argument("--paths", type=int, default=2000)
    lp.add_argument("--seeds", type=int, default=40)
    a = ap.parse_args()
    {"parity": parity, "nq": nq, "paper": paper}.get(a.cmd, lambda: lucid(a.paths, a.seeds))()
