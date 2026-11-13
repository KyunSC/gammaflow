"""Real-tape coin-flip replay of prop plans (plan: prop_realtape/PLAN.md, steps 3-4).

Pipeline, per plan x product x entry x stop scheme:
  1. `day_results`: for every day and both sides, one 1:1 bracket entered at the entry bar's open
       * stop S ticks below (long) / above (short) the entry; target T = S ticks, filled only on a tick THROUGH it
         (bar high >= T + 1), at T; a bar touching both fills the stop (stop first);
       * stop fill = the worse of the stop and the bar's open (gap), then the measured stop slip
         (lucid_structure.SLIP_T/SLIP_P, one draw per day and side, fixed by `slip_seed`);
       * flat-by: the open of the first bar at or after the plan's `flatByEt` (default 16:10 ET; NYSE half days
         13:10), or the last bar's close if the tape ends first; market exits pay ENTRY_SLIP_TICKS like the entry;
       * costs: commission per side x contracts, ENTRY_SLIP_TICKS adverse on entry (lucid_structure convention).
  2. `equity_bars` + `compress`: the trade's 1m equity path in $ relative to the day start, compressed per the
     plan (`compress_mode`: one bar for EOD drawdown; running-max record segments for an intraday trail, merged
     further only when there is no DLL). flybrain.prop.run_stage credits a bar's hi before its lo, so compressed
     bars give the same breach / DLL decisions as the 1m bars (only the gap-fill open can differ). The exit bar is
     split in path order: a stop exit (stop first) is open -> stop; a target exit is open -> low -> target.
  3. A day table in `flybrain.prop.build_day_table` layout with day id 2*i (long) / 2*i+1 (short), so a direction
     rule is a lookup, replayed unchanged by `flybrain.prop.simulate_account`:
       * block bootstrap (block 20 trading days, horizon 250) under each of 64 seeded coin sequences;
       * historical: every start day in order, run to the end of the tape;
       * EV per attempt = take - cost, exactly as lucid_structure.score (eval-open attempts are dropped).
Read-only use of lucid_structure / flybrain; nothing here edits shared code.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lucid_structure as L  # noqa: E402
from flybrain.prop import attempt_cost, simulate_account  # noqa: E402

TICK_USD = {"NQ": 0.50, "ES": 1.25}       # MNQ, MES
DEFAULT_FLAT = 16 * 60 + 10
HALF_FLAT = 13 * 60 + 10
BLOCK, HORIZON = 20, 250
EXIT = {"stop": 0, "target": 1, "flat": 2}


@dataclass
class Bracket:
    st: int            # stop ticks
    n: int             # contracts
    tick_usd: float
    comm: float        # per side per contract
    flat_mod: int      # ET minute


def trade(o, h, l, c, et, b: Bracket, slip: float, half: bool = False):
    """One long bracket on bars already mirrored for the side. Returns (exit code, exit index, fill ticks)."""
    S, T = b.st, b.st
    flat = min(b.flat_mod, HALF_FLAT) if half else b.flat_mod
    stop_k = np.flatnonzero(l <= -S)
    tgt_k = np.flatnonzero(h >= T + 1)
    flat_k = np.flatnonzero(et >= flat)
    first = lambda a: int(a[0]) if len(a) else None
    ks, kt, kf = first(stop_k), first(tgt_k), first(flat_k)
    cand = [x for x in (ks, kt, kf) if x is not None]
    if not cand:                                                # tape ends before flat-by: out at the last close
        return EXIT["flat"], len(o) - 1, float(c[-1]) - L.ENTRY_SLIP_TICKS, True
    k = min(cand)
    if kf == k:                                                 # flat-by bar: out at its open, before it trades
        return EXIT["flat"], k, float(o[k]) - L.ENTRY_SLIP_TICKS, False
    if ks == k:                                                 # stop first, also when the target is on the same bar
        return EXIT["stop"], k, float(min(-S, o[k])) - slip, False
    return EXIT["target"], k, float(T), False


def equity_bars(o, h, l, c, code, k, fill, at_close, b: Bracket):
    """Per-bar (open, hi, lo, close) $ equity of the day, relative to the day start, ending at the exit."""
    u = b.n * b.tick_usd
    cin = b.comm * b.n + L.ENTRY_SLIP_TICKS * b.tick_usd * b.n
    net = fill * u - cin - b.comm * b.n
    eq = lambda x: x * u - cin
    if code == EXIT["flat"] and not at_close:
        # bars 0..k-1 fully held, exit at bar k's open
        bo, bh, bl, bc = eq(o[:k]), eq(h[:k]), eq(l[:k]), eq(c[:k])
        tail = [(eq(o[k]), eq(o[k]), net, net)]
    elif code == EXIT["flat"]:
        bo, bh, bl, bc = eq(o[:k + 1]), eq(h[:k + 1]), eq(l[:k + 1]), eq(c[:k + 1])
        tail = [(net, net, net, net)]
    elif code == EXIT["stop"]:
        bo, bh, bl, bc = eq(o[:k]), eq(h[:k]), eq(l[:k]), eq(c[:k])
        tail = [(eq(o[k]), eq(o[k]), net, net)]
    else:
        bo, bh, bl, bc = eq(o[:k]), eq(h[:k]), eq(l[:k]), eq(c[:k])
        tail = [(eq(o[k]), eq(o[k]), eq(min(l[k], o[k])), eq(min(l[k], o[k]))), (net, net, net, net)]
    first = np.array([[-cin, -cin, -cin, -cin]])            # entry: commission + entry slip paid at the open
    body = np.stack([bo, bh, bl, bc], 1) if len(bo) else np.empty((0, 4))
    return np.vstack([first, body, np.array(tail)])


def compress_mode(plan: dict) -> str:
    """'eod': no intraday trail in any stage; 'merge': intraday trail, no DLL; 'records': intraday trail + DLL."""
    intraday = "intraday" in (plan.get("evalDrawdown"), plan.get("fundedDrawdown"))
    if not intraday:
        return "eod"
    return "records" if plan.get("dailyLossLimit") else "merge"


def compress(bars: np.ndarray, mode: str = "records") -> np.ndarray:
    """Compression for run_stage (hi credited before lo within a bar). Rows: open, hi, lo, close.

    * eod: one bar (first open, max hi, min lo, last close). The threshold and DLL level are fixed during the
      day, so the first crossing decides the same event (DLL is checked first in both).
    * records: segments at each new running-max hi. Inside a segment the peak does not move, so breach and DLL
      decisions match the 1m bars.
    * merge: records, then a segment merges into the next while its lo >= the next lo. Exact without a DLL; with
      a DLL it is not (an early DLL freeze would see a later, higher peak), hence the mode split.
    Every mode also starts a new bar where a bar opens below all lows since the last cut, so the open used as the
    gap-fill price on a breach or DLL freeze is the crossing bar's own open (review finding 5).
    """
    o, hi, lo = bars[:, 0], bars[:, 1], bars[:, 2]
    if mode == "eod":
        # threshold and DLL level are fixed all day: a new bar only where the open gaps below every earlier low,
        # so a gap-fill on a breach / DLL freeze uses the right open
        prior_lo = np.minimum.accumulate(np.r_[np.inf, lo[:-1]])
        starts = np.flatnonzero(o < prior_lo)               # bar 0 always (prior = inf)
        gap = np.ones(len(starts), bool)
    else:
        starts, gap, rec, seg_lo = [], [], -np.inf, np.inf
        for k in range(len(bars)):
            is_rec, is_gap = hi[k] > rec, o[k] < seg_lo
            if is_rec or is_gap:                            # new record peak, or an open below the segment's lows
                starts.append(k)
                gap.append(bool(is_gap and k > 0))
                seg_lo = np.inf
            rec = max(rec, hi[k])
            seg_lo = min(seg_lo, lo[k])
        starts, gap = np.array(starts), np.array(gap)
    ends = np.r_[starts[1:], len(bars)] - 1
    seg = np.stack([o[starts], np.maximum.reduceat(hi, starts), np.minimum.reduceat(lo, starts), bars[ends, 3]], 1)
    if mode in ("eod", "records"):
        return seg
    out, out_gap = [], []
    for s_, g in zip(seg.tolist(), gap.tolist()):
        while out and not g and out[-1][2] >= s_[2]:        # never merge into a gap-opened segment (its open counts)
            p_ = out.pop()
            g = out_gap.pop()
            s_ = [p_[0], max(p_[1], s_[1]), s_[2], s_[3]]
        out.append(s_)
        out_gap.append(g)
    return np.array(out)


def plan_cap(plan: dict) -> int:
    """Micro-contract cap: the funded account's opening tier (lucid_structure.sweep)."""
    return int((plan.get("fundedStartMinis") or plan["maxMinis"]) * 10)


def base_bracket(risk: float, n: int, product: str) -> int:
    """Stop ticks for the headline $ risk and contract count on this product's micro (sweep's rule)."""
    return int(round(risk / (n * TICK_USD[product])))


def day_results(paths: dict, risk: float, n: int, product: str, comm: float, flat_mod: int,
                rule: str = "fixed", k_abs: float | None = None, cap: int = 40, slip_seed: int = 7,
                mode: str | None = "records"):
    """Bars per (day, side) and per-day summaries.

    `n` = the headline contract count; the base stop st0 = risk / (n x micro tick $) (MNQ $0.50, MES $1.25).
    rule: 'fixed' -> st0 every day; 'rel' -> st0 x scale (regime-relative); 'abs' -> k_abs x vol_ticks.
    Scaled stops re-round contracts at the same $ risk; when that needs more than `cap` contracts the stop keeps
    its scaled width at `cap` contracts and the day risks less (recorded in out['capped'] / out['risk'])."""
    days = paths["days"]
    tick = TICK_USD[product]
    st0 = base_bracket(risk, n, product)
    slips = date_slips(days["date"], slip_seed)
    out = dict(bars=[], code=np.zeros((len(days), 2), int), pnl=np.zeros((len(days), 2)), st=np.zeros(len(days), int),
               n=np.zeros(len(days), int), risk=np.zeros(len(days)), valid=np.ones(len(days), bool),
               capped=np.zeros(len(days), bool), slip=slips, st0=st0)
    for i, r in enumerate(days.itertuples(index=False)):
        if rule == "fixed":
            ni, si = n, st0
        else:
            want = st0 * r.scale if rule == "rel" else k_abs * r.vol_ticks
            if not np.isfinite(want) or want <= 0:
                out["valid"][i] = False
                want = st0
            raw_n = risk / (want * tick)
            if raw_n > cap + 0.5:
                ni, si = cap, max(4, int(round(want)))
                out["capped"][i] = True
            else:
                ni = max(1, int(round(raw_n)))
                si = max(4, int(round(risk / (ni * tick))))
        b = Bracket(si, ni, tick, comm, flat_mod)
        a, z = r.start, r.start + r.n_bars
        O, H, Lo, C, E = paths["o"][a:z], paths["h"][a:z], paths["l"][a:z], paths["c"][a:z], paths["et_min"][a:z]
        out["st"][i], out["n"][i], out["risk"][i] = si, ni, si * ni * tick
        for side in (0, 1):
            o_, h_, l_, c_ = (O, H, Lo, C) if side == 0 else (-O, -Lo, -H, -C)
            code, k, fill, at_close = trade(o_, h_, l_, c_, E, b, float(slips[i, side]), bool(r.half))
            eb = equity_bars(o_, h_, l_, c_, code, k, fill, at_close, b)
            out["bars"].append(compress(eb, mode) if mode else eb)
            out["code"][i, side], out["pnl"][i, side] = code, eb[-1, 3]
    return out


def table_from_bars(bars: list) -> dict:
    """build_day_table layout from per-day (open, hi, lo, close) rows; day ids = list positions."""
    lens = np.array([len(b) for b in bars])
    allb = np.vstack(bars)
    starts = np.r_[0, np.cumsum(lens)[:-1]]
    ends = starts + lens - 1
    n = len(bars)
    return dict(n=n, start=starts.tolist(), end=ends.tolist(), active=[1] * n, time=[0.0] * n,
                lo=allb[:, 2].tolist(), hi=allb[:, 1].tolist(), open=allb[:, 0].tolist(), close=allb[:, 3].tolist(),
                min_lo=np.minimum.reduceat(allb[:, 2], starts).tolist())


def run(table: dict, seqs, plan: dict) -> list:
    """seqs: iterable of day-id sequences (lists/arrays); each replays one account."""
    done = []
    for seq in seqs:
        m = len(seq)
        a = simulate_account(table, lambda k, s=seq, m=m: int(s[k]) if k < m else -1, plan)
        if a["outcome"] != "eval-open":
            done.append(a)
    return done


def iid_seqs(n_ids: int, paths: int, horizon: int = HORIZON, seed: int = 1):
    """Same draws as lucid_structure.attempts."""
    rng = np.random.default_rng(seed)
    for _ in range(paths):
        yield rng.integers(0, n_ids, horizon)


def block_seqs(day_idx: np.ndarray, sides: np.ndarray, paths: int, block: int = BLOCK, horizon: int = HORIZON,
               seed: int = 1):
    """Moving-block bootstrap over the ordered day subset `day_idx`; ids = 2*day + side[day]."""
    rng = np.random.default_rng(seed)
    m = len(day_idx)
    nb = math.ceil(horizon / block)
    for _ in range(paths):
        b = rng.integers(0, max(1, m - block + 1), nb)
        pos = (b[:, None] + np.arange(block)[None, :]).ravel()[:horizon] % m
        d = day_idx[pos]
        yield 2 * d + sides[d]


def hist_seqs(day_idx: np.ndarray, sides: np.ndarray, horizon: int = HORIZON):
    """Every start day in order, at most `horizon` days (as the bootstrap and lucid_structure.attempts)."""
    for s in range(len(day_idx)):
        d = day_idx[s:s + horizon]
        yield 2 * d + sides[d]


def summarize(done: list, plan: dict, fee: float) -> dict:
    """lucid_structure.score's EV, plus the rates this loop reports."""
    takes = np.array([a["take"] for a in done], float)
    used = np.array([a["daysUsed"] for a in done], float)
    paid = np.array([bool(a["payouts"]) for a in done])
    passed = np.array([a["outcome"] != "failed" for a in done])
    costs = np.full(len(done), float(fee))
    if plan.get("rebillDays") or plan.get("activationOnPass"):
        costs = np.array([attempt_cost(a, plan) for a in done], float)
        fee = float(costs.mean())
    ev = float(takes.mean() - fee)
    return dict(n=len(done), fee=fee, ev=ev, pass_rate=float(passed.mean()), p_paid=float(paid.mean()),
                mean_take=float(takes.mean()), days_used=float(used.mean()), ev_per_day=ev / float(used.mean()))


def _mix(x: np.ndarray) -> np.ndarray:
    """splitmix64 finaliser (uint64 -> uint64)."""
    with np.errstate(over="ignore"):
        x = (x + np.uint64(0x9E3779B97F4A7C15)).astype(np.uint64)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def _date_u64(dates, key: int, salt: int) -> np.ndarray:
    ords = np.array([d.toordinal() for d in dates], dtype=np.uint64)
    return _mix(_mix(ords ^ (np.uint64(key) << np.uint64(32))) ^ np.uint64(salt))


def coin_sides(dates, seq: int) -> np.ndarray:
    """Coin per calendar date (0 = long, 1 = short): the same date gets the same side in every file, product and
    entry time for a given sequence, so comparisons across them are paired (review finding 3)."""
    return (_date_u64(dates, seq, 0xC01) >> np.uint64(63)).astype(np.int64)


def date_slips(dates, seed: int) -> np.ndarray:
    """Stop slip (ticks) per date and side from the measured PMF, keyed by date like the coins."""
    cdf = np.cumsum(L.SLIP_P)
    cdf[-1] = 1.0
    out = np.empty((len(dates), 2))
    for side in (0, 1):
        u = (_date_u64(dates, seed, 0x511 + side) >> np.uint64(11)).astype(np.float64) / float(1 << 53)
        out[:, side] = L.SLIP_T[np.searchsorted(cdf, u, side="right")]
    return out
