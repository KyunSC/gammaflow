"""Historical replay without end-of-era truncation (question #4 of the real-tape prop loop).

The step-4 historical replay (`replay.hist_seqs` on `run_plan.era_idx(era)`) runs each start day only on the days
of its own era, so an account that starts in the last ~250 days of an era is cut at the era end. If it is still
open it is either dropped (eval-open, an outcome-dependent drop of slow evaluators) or counted funded-open with
only the take paid so far. Long-lived plans (LucidDirect, Alpha Direct) lose most.

Fix (`cont_seq`): an account's era label comes from its START day, but it keeps trading on the following real days
(across era boundaries) until it ends or reaches the horizon; only the end of the data truncates. The data end
is the end of the last era in `run_plan.ERAS` (2026-08-14), the same day set as the old pooled replay, so NQ and
ES stop together (the 55 NQ `2026-ext` sessions are not used). For starts whose account cannot run a full horizon
before the data end, two treatments:
  (a) `drop`: drop those starts BY START DATE (start position + horizon > number of days), outcome-independent;
  (b) `hybrid`: complete the missing days with moving blocks (20 days) drawn from the start era's own days under
      the same date-keyed coin; labelled hybrid (real path, then bootstrap).
Accounts open at the horizon itself are handled exactly as the bootstrap does (eval-open dropped, funded-open at
the take so far); `boot_check` measures how often that happens and the EV at horizon 500.

Read-only use of replay / run_plan / realdays / flybrain.prop; nothing here edits shared code.

  ../../.venv/bin/python prop_realtape/hist_fix.py [plan_id ...] [--workers 2]
  ../../.venv/bin/python prop_realtape/hist_fix.py --table          # writes data/prop_realtape/hist_fix/table.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

PKG = Path(__file__).resolve().parent
sys.path[:0] = [str(PKG), str(PKG.parent)]
import lucid_structure as L  # noqa: E402
import replay as RP  # noqa: E402
import run_plan as RPL  # noqa: E402
from flybrain.prop import simulate_account  # noqa: E402

HERE = PKG.parent
SRC = HERE / "data" / "prop_realtape"
OUT = SRC / "hist_fix"
VIEWS = ("pooled",) + RPL.ERAS
OPEN = ("eval-open", "funded-open")
LONG_LIVED = ("luciddirect_150k", "alpha_direct_50k", "lucidflex_50k", "topstep_cons_nofee_50k_nodll")
_G: dict = {}


# ---- sequences --------------------------------------------------------------------------------------------------
def cont_seq(order: np.ndarray, p: int, horizon: int = RP.HORIZON) -> np.ndarray:
    """Day indices for the account starting at position p of the ordered day pool `order`: the next real days,
    across era boundaries, up to the horizon. Only the end of `order` truncates."""
    return order[p:p + horizon]


def era_seq(order: np.ndarray, p: int, era_end: int, horizon: int = RP.HORIZON) -> np.ndarray:
    """The OLD replay's sequence: also stops at the end of the start's era (position era_end, exclusive)."""
    return order[p:min(p + horizon, era_end)]


def hybrid_seq(order: np.ndarray, p: int, era_pos: np.ndarray, rng, horizon: int = RP.HORIZON,
               block: int = RP.BLOCK) -> tuple[np.ndarray, int]:
    """cont_seq, completed to the full horizon with moving blocks from the start era's positions `era_pos` (block
    bootstrap as replay.block_seqs). Returns (day indices, number of real days)."""
    real = order[p:p + horizon]
    need = horizon - len(real)
    if need <= 0:
        return real, len(real)
    m = len(era_pos)
    nb = math.ceil(need / block)
    b = rng.integers(0, max(1, m - block + 1), nb)
    pos = (b[:, None] + np.arange(block)[None, :]).ravel()[:need] % m
    return np.r_[real, order[era_pos[pos]]], len(real)


def ids(d: np.ndarray, sides: np.ndarray) -> np.ndarray:
    return 2 * d + sides[d]


def sim(table: dict, seq_ids: np.ndarray, plan: dict) -> dict:
    """One account on the given id sequence; keeps eval-open accounts and records the sequence length."""
    m = len(seq_ids)
    a = simulate_account(table, lambda k: int(seq_ids[k]) if k < m else -1, plan)
    a["seq_len"] = m
    return a


# ---- summaries --------------------------------------------------------------------------------------------------
def summ(accs: list, plan: dict, fee: float, horizon: int = RP.HORIZON) -> dict:
    """replay.summarize / run_plan.apex_summarize on the resolved accounts (eval-open dropped, as replay.run),
    plus truncation shares over all accounts: truncated = still open with fewer than `horizon` days available;
    horizon_open = still open after the full horizon (as in the bootstrap)."""
    f = RPL.apex_summarize if "_apex" in plan else (lambda d, p: RP.summarize(d, p, fee))
    n_all = len(accs)
    out_ = np.array([a["outcome"] for a in accs], dtype="<U16")
    short = np.array([a["seq_len"] < horizon for a in accs], dtype=bool)
    is_open = np.isin(out_, OPEN)
    trunc = is_open & short
    done = [a for a in accs if a["outcome"] != "eval-open"]
    s = f(done, plan)
    keep = [a for a, t in zip(accs, trunc) if a["outcome"] != "eval-open" and not t]
    s.update(n_all=n_all, trunc_share=float(trunc.mean()), trunc_eval_open=float((trunc & (out_ == "eval-open")).mean()),
             trunc_funded_open=float((trunc & (out_ == "funded-open")).mean()),
             horizon_open=float((is_open & ~short).mean()),
             horizon_eval_open=float((~short & (out_ == "eval-open")).mean()),
             ev_wo_trunc=f(keep, plan)["ev"] if keep else float("nan"))
    if accs and all("synth_used" in a for a in accs):
        s["synth_used"] = float(np.mean([a["synth_used"] for a in accs]))
    return s


def agg(rows: list, t: float = RPL.T63) -> dict:
    """run_plan.agg (EV, CI across coins, rates) plus the mean of every truncation field."""
    a = RPL.agg(rows, t)
    for k in ("n_all", "trunc_share", "trunc_eval_open", "trunc_funded_open", "horizon_open", "horizon_eval_open",
              "ev_wo_trunc", "synth_used", "eval_open_at_h", "funded_open_at_h"):
        if k in rows[0]:
            a[k] = float(np.nanmean([r[k] for r in rows]))
    return a


# ---- per-coin historical job ------------------------------------------------------------------------------------
def pool_layout(days, eras=RPL.ERAS):
    """Ordered day pool (all days in `eras`, date order), each position's era, and each era's [lo, hi) positions."""
    order = np.flatnonzero(days["era"].isin(eras).to_numpy())
    era = days["era"].to_numpy()[order]
    bounds = {e: (int(np.flatnonzero(era == e)[0]), int(np.flatnonzero(era == e)[-1]) + 1) for e in eras if (era == e).any()}
    return order, era, bounds


def hist_coin(table, plan, fee, days, coin: int, horizon: int = RP.HORIZON, old: bool = True,
              hybrid: bool = True, eras=RPL.ERAS) -> dict:
    """All historical views for one coin sequence: {view: {variant: summ}}.

    variants: old (each era cut at its own end; pooled = the whole pool, as run_plan), cont (fix, end-of-data
    truncated, all starts), drop (fix, starts that cannot reach the horizon dropped by start date), hybrid (fix,
    late starts completed with same-era blocks)."""
    order, era, bounds = pool_layout(days, eras)
    sides = RP.coin_sides(days["date"].tolist(), coin)
    N = len(order)
    cont = [sim(table, ids(cont_seq(order, p, horizon), sides), plan) for p in range(N)]
    for a in cont:
        a["synth_used"] = False
    res = {v: {} for v in VIEWS if v == "pooled" or v in bounds}
    starts = {"pooled": np.arange(N), **{e: np.arange(*bounds[e]) for e in bounds}}
    late = np.arange(N) + horizon > N
    hyb = list(cont)
    if hybrid:
        for p in np.flatnonzero(late):
            lo, hi = bounds[era[p]]
            rng = np.random.default_rng([7919, coin, int(p), horizon])
            d, n_real = hybrid_seq(order, int(p), np.arange(lo, hi), rng, horizon)
            a = sim(table, ids(d, sides), plan)
            a["synth_used"] = a["daysUsed"] > n_real
            hyb[p] = a
    for v, st in starts.items():
        r = res[v]
        r["cont"] = summ([cont[p] for p in st], plan, fee, horizon)
        r["drop"] = summ([cont[p] for p in st if not late[p]], plan, fee, horizon)
        if hybrid:
            r["hybrid"] = summ([hyb[p] for p in st], plan, fee, horizon)
        if old:
            if v == "pooled":
                r["old"] = r["cont"]
            else:
                end = bounds[v][1]
                oa = [cont[p] if p + horizon <= end else sim(table, ids(era_seq(order, p, end, horizon), sides), plan)
                      for p in st]
                r["old"] = summ(oa, plan, fee, horizon)
        r["n_starts"] = int(len(st))
        r["n_starts_drop"] = int((~late[st]).sum())
    return res


def boot_coin(table, plan, fee, days, coin: int, paths: int, horizons=(250, 500), eras=RPL.ERAS) -> dict:
    """Paired horizon check for the moving-block bootstrap (replay.block_seqs' law): one block sequence of the
    longest horizon per path, prefixes for the shorter ones. Per view and horizon: summ + open shares at that
    horizon (eval-open dropped, funded-open valued at the take so far)."""
    sides = RP.coin_sides(days["date"].tolist(), coin)
    H = max(horizons)
    out = {}
    for v in ("pooled",) + tuple(eras):
        idx = np.flatnonzero((days["era"].isin(eras) if v == "pooled" else days["era"] == v).to_numpy())
        if not len(idx):
            continue
        seqs = list(RP.block_seqs(idx, sides, paths, horizon=H, seed=5000 + coin))
        out[v] = {}
        prev = None
        for h in sorted(horizons):
            accs = []
            for j, s in enumerate(seqs):
                if prev is not None and prev[j]["outcome"] not in OPEN:      # closed earlier: same account
                    a = dict(prev[j], seq_len=h)
                else:
                    a = sim(table, s[:h], plan)
                accs.append(a)
            s_ = summ(accs, plan, fee, h + 1)          # every account "short" -> trunc fields = open-at-horizon
            s_["eval_open_at_h"] = s_.pop("trunc_eval_open")
            s_["funded_open_at_h"] = s_.pop("trunc_funded_open")
            out[v][f"h{h}"] = s_
            prev = accs
    return out


def block_coin(table, plan, fee, days, coin: int, paths: int, blocks=(20, 60, 125, 250), eras=RPL.ERAS) -> dict:
    """Residual-gap diagnostic: moving-block bootstrap EV (horizon 250) at longer blocks. Block 250 draws one
    contiguous real window per account (the historical replay without its start-date weighting); if EV falls as
    the block grows, regime persistence beyond 20 days, not truncation, separates hist from the bootstrap."""
    sides = RP.coin_sides(days["date"].tolist(), coin)
    out = {}
    for v in ("pooled",) + tuple(eras):
        idx = np.flatnonzero((days["era"].isin(eras) if v == "pooled" else days["era"] == v).to_numpy())
        out[v] = {f"b{b}": summ([sim(table, s, plan) for s in RP.block_seqs(idx, sides, paths, block=b, seed=7000 + coin)],
                                plan, fee) for b in blocks}
    return out


# ---- driver -----------------------------------------------------------------------------------------------------
def _job(args):
    key, kind, coin, kw = args
    days, table, plan, fee = _G[key]
    if kind == "hist":
        return hist_coin(table, plan, fee, days, coin, **kw)
    if kind == "block":
        return block_coin(table, plan, fee, days, coin, **kw)
    return boot_coin(table, plan, fee, days, coin, **kw)


def t975(n: int) -> float:
    """t(0.975, n - 1) for the CI across n coin sequences."""
    from scipy.stats import t as student
    return float(student.ppf(0.975, n - 1))


def collect(rows: list, t: float | None = None) -> dict:
    """Per-coin {view: {variant: summ}} -> {view: {variant: agg}}; t defaults to t(0.975, coins - 1)."""
    t = t975(len(rows)) if t is None else t
    out = {}
    for v in rows[0]:
        out[v] = {}
        for var, x in rows[0][v].items():
            out[v][var] = agg([r[v][var] for r in rows], t) if isinstance(x, dict) else x
    return out


def check_frozen(state: dict):
    sha = hashlib.sha256((PKG / "realdays.py").read_bytes()).hexdigest()
    assert sha == state["frozen"]["realdays_sha256"], "realdays.py changed since the freeze"
    return sha


def run_one(plan_id: str, workers: int = 2, coins: int = RPL.N_COIN, boot_coins: int = 64, boot_paths: int = 2000,
            h_long: int = 500, block_paths: int = 1000) -> dict:
    state = json.loads((SRC / "state.json").read_text())
    sha = check_frozen(state)
    entry = next(e for e in state["plans_queue"] if e["id"] == plan_id)
    plan, h = RPL.resolve(entry)
    fee = plan["_apex"]["price"] if "_apex" in plan else L.fee_of(plan)
    old_json = json.loads((SRC / "results" / f"{plan_id}.json").read_text())
    res = dict(plan_id=plan_id, plan=entry["plan"], firm=entry["firm"], provisional=bool(entry.get("provisional")),
               fee_flat=fee, horizon=RP.HORIZON, realdays_sha256=sha, coins=coins,
               boot_check=dict(coins=boot_coins, paths=boot_paths, horizons=[RP.HORIZON, h_long]),
               block_check=dict(coins=boot_coins, paths=block_paths, blocks=[20, 60, 125, 250]))
    t0 = time.time()
    ctx = mp.get_context("fork")
    for prod in ("NQ", "ES"):
        days, dr, table = RPL.cell_table(plan, h, prod, "0935", "fixed")
        key = (plan_id, prod)
        _G[key] = (days, table, plan, fee)
        with ctx.Pool(workers) as pool:
            hist = collect(pool.map(_job, [(key, "hist", c, {}) for c in range(coins)]))
            boot = collect(pool.map(_job, [(key, "boot", c, dict(paths=boot_paths, horizons=(RP.HORIZON, h_long)))
                                           for c in range(boot_coins)]))
            blk = collect(pool.map(_job, [(key, "block", c, dict(paths=block_paths)) for c in range(boot_coins)]))
            h500 = None
            if plan_id in LONG_LIVED:
                h500 = collect(pool.map(_job, [(key, "hist", c, dict(horizon=h_long, old=False, hybrid=False))
                                               for c in range(coins)]))
        _G.pop(key)
        r = {}
        for v in VIEWS:
            r[v] = dict(boot_official=old_json[f"headline_{prod}"][v]["boot"],
                        hist_official=old_json[f"headline_{prod}"][v]["hist"], **hist[v],
                        boot_h250=boot[v][f"h{RP.HORIZON}"], boot_h500=boot[v][f"h{h_long}"], block=blk[v])
            if h500 is not None:
                r[v]["drop_h500"] = h500[v]["drop"]
                r[v]["cont_h500"] = h500[v]["cont"]
                r[v]["n_starts_drop_h500"] = h500[v]["n_starts_drop"]
        res[prod] = r
        print(f"[{time.time() - t0:5.0f}s] {plan_id} {prod}",
              {v: (round(r[v]['old']['ev'], 1), round(r[v]['drop']['ev'], 1), round(r[v]['hybrid']['ev'], 1))
               for v in VIEWS}, flush=True)
    res["runtime_s"] = round(time.time() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{plan_id}.json").write_text(json.dumps(res, indent=1, default=float))
    return res


# ---- before / after table ---------------------------------------------------------------------------------------
def fee_variants(plan_id: str, fee: float) -> dict:
    """Derived one-off-fee prices: EV at the promo price = EV at `fee` + (fee - promo price) on identical accounts.
    Promo prices come from firms.js through prop_prices (only one-off-fee plans: Lucid, MFF)."""
    import prop_prices as P
    e = next(x for x in json.loads((SRC / "state.json").read_text())["plans_queue"] if x["id"] == plan_id)
    if e["firm"] not in ("lucid", "mff"):
        return {}
    plan = P.find(e["firm"], e["plan"])
    return {f"promo{round(plan['promoPct'] * 100)}": round(fee - P.price(plan, "promo"), 2)} if plan.get("promoPct") else {}


def table() -> dict:
    state = json.loads((SRC / "state.json").read_text())
    rows = []
    for e in state["plans_queue"]:
        f = OUT / f"{e['id']}.json"
        if not f.exists():
            continue
        r = json.loads(f.read_text())
        add = fee_variants(e["id"], r["fee_flat"])
        for prod in ("NQ", "ES"):
            for v in VIEWS:
                x = r[prod][v]
                row = dict(plan=e["id"], product=prod, view=v, provisional=r["provisional"],
                           boot=x["boot_official"]["ev"], old_hist=x["old"]["ev"], old_hist_official=x["hist_official"]["ev"],
                           cont=x["cont"]["ev"], drop=x["drop"]["ev"], drop_ci=x["drop"]["ev_ci"], hybrid=x["hybrid"]["ev"],
                           hybrid_ci=x["hybrid"]["ev_ci"],
                           old_trunc=x["old"]["trunc_share"], old_trunc_eval_open=x["old"]["trunc_eval_open"],
                           old_ev_wo_trunc=x["old"]["ev_wo_trunc"], cont_trunc=x["cont"]["trunc_share"],
                           drop_trunc=x["drop"]["trunc_share"], hybrid_synth=x["hybrid"].get("synth_used"),
                           horizon_open_drop=x["drop"]["horizon_open"],
                           days_boot=x["boot_official"]["days_used"], days_old=x["old"]["days_used"],
                           days_drop=x["drop"]["days_used"], days_hybrid=x["hybrid"]["days_used"],
                           n_starts=x["n_starts"], n_starts_drop=x["n_starts_drop"],
                           boot_h250=x["boot_h250"]["ev"], boot_h500=x["boot_h500"]["ev"],
                           boot_open_250=x["boot_h250"]["eval_open_at_h"] + x["boot_h250"]["funded_open_at_h"],
                           boot_funded_open_250=x["boot_h250"]["funded_open_at_h"],
                           boot_open_500=x["boot_h500"]["eval_open_at_h"] + x["boot_h500"]["funded_open_at_h"],
                           drop_h500=x.get("drop_h500", {}).get("ev"), n_starts_drop_h500=x.get("n_starts_drop_h500"),
                           **{f"block{k[1:]}": b["ev"] for k, b in x["block"].items()})
                for k, d in add.items():
                    row[k] = {c: (row[c] + d if row[c] is not None else None)
                              for c in ("boot", "old_hist", "drop", "hybrid", "boot_h500", "drop_h500")}
                rows.append(row)
    (OUT / "table.json").write_text(json.dumps(rows, indent=1, default=float))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plans", nargs="*")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--coins", type=int, default=RPL.N_COIN)
    ap.add_argument("--boot-coins", type=int, default=64)
    ap.add_argument("--boot-paths", type=int, default=2000)
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    if a.table:
        rows = table()
        print("wrote table.json", len(rows), "rows")
        return
    state = json.loads((SRC / "state.json").read_text())
    for pid in a.plans or [e["id"] for e in state["plans_queue"]]:
        run_one(pid, min(a.workers, 2), a.coins, a.boot_coins, a.boot_paths)


if __name__ == "__main__":
    main()
