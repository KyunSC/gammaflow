"""Is session VWAP a special price? Touch-and-reject at VWAP against shifted copies of VWAP (Stage 0).

Sunny asked (2026-10-28) about trading with or against big institutions "since they like to place orders near VWAP".
VWAP is the benchmark institutions are graded against, and VWAP algos slice by a volume schedule rather than resting
at the VWAP price, so the claim is doubtful as stated (write-up: https://claude.ai/artifact/DZwyQtHRocMNQYjo9mWXpz).
Before any order-flow or options-flow data is bought, this asks the cheapest question that can kill the idea: does
price treat VWAP differently from a nearby price that moves exactly like VWAP? No P&L, no costs, no grid.

Rules (fixed before any number was looked at):
  - data, exploration: Databento XNAS.ITCH SPY + QQQ ohlcv-1m sessions <= DISCOVERY_END (2025-03-26), loaded by
    amt_lucid_study.load_sessions (RTH 09:30-15:59 ET, >= 380 bars). Unlimited runs: other studies have read them.
  - data, confirmation: Databento GLBX.MDP3 ES.v.0 and NQ.v.0 ohlcv-1m, RTH sessions 2012-01-03 -> 2021-12-31, from
    the es-ohlcv-1m-early (PR #10) and nq-ohlcv-1m-early (PR #11) jobs. Scored ONCE (--confirm). Those folders are
    also the one-look sets of vp_claims_study.py, trader_playbooks_study.py and vwap_stretch_study.py: freeze every
    study's prereg before any of them looks, so nothing seen there can steer another study's selection.
  - levels, per 1m bar, as of that bar's close: session VWAP from 09:30 of typical price (H+L+C)/3 x volume; the
    placebos VWAP + k x A for k in SHIFTS (+-0.75, +-1.0), where A is fixed per session (below), so a placebo has
    exactly VWAP's lag and smoothness and differs only in price. Every shift lies farther from VWAP than EXCURSION,
    so a placebo touch resolves before price can reach VWAP: a real VWAP effect cannot leak into its own control. Secondary, reported only: session TWAP (running
    mean of typical price), counted only where |VWAP - TWAP| >= TWAP_SEP x A at the touch.
  - A: the 14-bar mean true range of 09:30-anchored 5m bars, as of the 10:40 close (the 14th bar), H-L for the
    first bar. Sessions without 14 such bars by then are skipped. Every distance below is in A.
  - touch (H0b): a level is armed on a side once a 1m bar (minute >= 10:40) closes at least ARM x A away from it.
    An armed level is touched at bar i (minute 10:45-15:30) when bar i's range comes within TOUCH_TOL x A of the
    level as of bar i-1's close, the price a trader saw (a level that holds may stop price a tick short of it). A touch disarms the level until it re-arms. One level's touches never depend on
    another's.
  - outcome: from the touched price, "reject" if price reaches EXCURSION x A back on the approach side before it
    reaches EXCURSION x A through the level; "break" for the reverse. On the touch bar only the break counts (the
    rally after a touch inside that bar cannot be ordered). A later bar reaching both is "ambiguous"; reaching
    neither by 15:59 is "unresolved". Both are counted, and left out of P(reject) = reject / (reject + break).
  - strata: approach side (from above / below) x time of day (10:45-12:00, 12:00-14:00, 14:00-15:30) x approach
    speed (fast: <= FAST_BARS bars since the last bar that closed ARM x A away on that side; slow otherwise).
  - H0b statistic: delta = sum over strata of w_s x (P_vwap,s - P_placebo,s), where P_placebo pools the four shifts
    and w_s is the stratum's share of VWAP's resolved touches (strata missing either side drop out). Pooling +k and
    -k cancels, to first order, any plain pull toward VWAP: it is VWAP as a barrier that is measured.
  - H0a (mechanism, reported only, cannot pass the stage): 1m bars (10:45-15:30) whose range holds VWAP but no
    +-0.75 shift, against bars holding a shift but not VWAP. y = log(volume / the session's median window volume).
    delta_v = the same stratum-weighted difference of means, strata = 30-minute bucket x bar range in A (RANGE_BINS).
  - inference: bootstrap over whole sessions (N_BOOT draws, seed 0). lower = the ALPHA quantile.
  - exploration gate (--freeze): delta >= MIN_EFFECT and lower > 0 on BOTH SPY and QQQ. Otherwise the premise fails at
    1-minute resolution: the stage is killed, ES / NQ are never read for it, and no flow data is bought.
  - verdict on each of ES and NQ (--confirm), ALPHA = 0.05 / 2: PASS when delta >= MIN_EFFECT and lower > 0. VWAP is
    called special only if both pass.
  - reading a negative delta: price that clings to VWAP (pinning) breaks more often than a free walk, because it
    leaks through and then clings on the far side. That is not support, and it does not pass.
  - what the synthetic tests caught before any market data: with shifts at +-0.25 / +-0.5 and a 1 A excursion, the
    shifts' outcomes ran into VWAP itself, so a planted VWAP barrier raised the placebo's P(reject) more than VWAP's
    and read as a negative delta; and with no touch tolerance a barrier that holds is never counted as touched.
    Both are fixed above, and test_vwap_level_study pins that a planted barrier passes and a random walk does not.
    Also from the walks: two-way trend days leave delta near 0, but the same strong up-drift on every session (a
    daily Sharpe near 1, far beyond any index) pushed it to about +0.03 with a CI above 0. Check by_year before
    believing a pass in a one-way bull run. With ~120 sessions a no-edge walk can print +0.03, which is why the
    gate also needs lower > 0.

One look, enforced as in vwap_stretch_study.py: script_sha() hashes this file AND amt_lucid_study.py; the tests pin it
(SPEC_SHA). --freeze re-runs the exploration and writes vwap_level_prereg.json next to this script (commit it).
--confirm refuses when vwap_level_looks.log (committed) has a look, when the hash changed, when exploration did not
pass, or when either download misses a year (>= 230 sessions in each of 2012-2021); then it appends the look first.

    python functions/ml/vwap_level_study.py --explore
    python functions/ml/vwap_level_study.py --freeze          # then commit functions/ml/vwap_level_prereg.json
    python functions/ml/vwap_level_study.py --confirm         # ask first; then commit functions/ml/vwap_level_looks.log

Specification: everything above was written down before the first run and not changed after it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import amt_lucid_study as amt  # noqa: E402

ET = amt.ET
OPEN, FLAT, CLOSE = amt.OPEN, amt.FLAT, amt.CLOSE    # 09:30, 15:54, 16:00
MIN_BARS = amt.MIN_BARS
DISCOVERY_END = amt.DISCOVERY_END

OUT = amt.DATA / "vwap_level"
PREREG, LOOKS = HERE / "vwap_level_prereg.json", HERE / "vwap_level_looks.log"   # committed, unlike OUT
SPEC_FILES = (Path(__file__).resolve(), HERE / "amt_lucid_study.py")
FUT_DIRS = {"ES": amt.DATA / "databento" / "es-ohlcv-1m-early" / "ES",
            "NQ": amt.DATA / "databento" / "nq-ohlcv-1m-early" / "NQ"}
CONFIRM_START, CONFIRM_END = date(2012, 1, 3), date(2021, 12, 31)
MIN_SESSIONS_PER_YEAR = 230

ATR_TF, ATR_N = 5, 14
A_READY = OPEN + ATR_TF * ATR_N        # 10:40: A is known once the 14th 5m bar has closed
TOUCH_FIRST, TOUCH_LAST = 645, 930     # 10:45, 15:30
SHIFTS = (-1.0, -0.75, 0.75, 1.0)    # all farther from VWAP than EXCURSION: a placebo's outcome never reaches VWAP
ARM = 0.5
TOUCH_TOL = 0.1
EXCURSION = 0.5
FAST_BARS = 5
TWAP_SEP = 0.75
TIME_EDGES = (720, 840)                # 12:00, 14:00
RANGE_BINS = (0.1, 0.2, 0.4)           # 1m bar range in A
MIN_EFFECT = 0.03
ALPHA = 0.05 / 2
N_BOOT, SEED = 2000, 0

LEVELS = ("vwap", *(f"shift{k:+.2f}" for k in SHIFTS), "twap")
PLACEBOS = LEVELS[1:1 + len(SHIFTS)]
N_STRATA = 2 * (len(TIME_EDGES) + 1) * 2
N_VSTRATA = (CLOSE - OPEN) // 30 * (len(RANGE_BINS) + 1)
REJECT, BREAK, AMBIG, OPEN_ = 0, 1, 2, 3


# ---------------------------------------------------------------- data

def session(g: pd.DataFrame) -> dict:
    return dict(H=g.high.to_numpy(float), L=g.low.to_numpy(float), C=g.close.to_numpy(float),
                V=g.volume.to_numpy(float), m=g.minute.to_numpy(int))


def load_xnas(symbol: str) -> dict[date, dict]:
    return {d: session(g) for d, g in amt.load_sessions(symbol, DISCOVERY_END).items()}


def load_fut(sym: str, start: date = CONFIRM_START, end: date = CONFIRM_END) -> dict[date, dict]:
    bars_dir = FUT_DIRS[sym]
    files = sorted(bars_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bars in {bars_dir}; run databento_fetch.py {bars_dir.parent.name}")
    cutoff = pd.Timestamp(end + pd.Timedelta(days=1), tz=ET).tz_convert("UTC")
    cols = ["open", "high", "low", "close", "volume", "instrument_id"]
    bars = pd.concat([pd.read_parquet(f, columns=cols, filters=[("ts_event", "<", cutoff)]) for f in files]).sort_index()
    bars = bars[~bars.index.duplicated()]
    assert (bars.index < cutoff).all(), "LEAK: bar read reaches past the confirmation window"
    et = bars.index.tz_convert(ET)
    bars = bars.assign(day=et.date, minute=et.hour * 60 + et.minute)
    bars = bars[(bars.minute >= OPEN) & (bars.minute < CLOSE) & (bars.day >= start) & (bars.day <= end)]
    out = {}
    for d, g in bars.groupby("day", sort=True):
        if (len(g) >= MIN_BARS and g.minute.iloc[0] == OPEN and g.minute.iloc[-1] >= FLAT
                and g.instrument_id.nunique() == 1):
            out[d] = session(g)
    return out


# ---------------------------------------------------------------- levels

def session_vwap(H, L, C, V) -> np.ndarray:
    tp = (H + L + C) / 3
    cv = np.cumsum(V)
    return np.where(cv > 0, np.cumsum(tp * V) / np.where(cv > 0, cv, 1), tp)


def session_twap(H, L, C) -> np.ndarray:
    tp = (H + L + C) / 3
    return np.cumsum(tp) / np.arange(1, len(tp) + 1)


def session_atr(s: dict) -> float:
    """A: 14-bar mean true range of 09:30-anchored 5m bars through the 10:40 close, or nan."""
    keep = s["m"] < A_READY
    b = (s["m"][keep] - OPEN) // ATR_TF
    if len(b) == 0 or len(np.unique(b)) < ATR_N:
        return float("nan")
    df = pd.DataFrame(dict(b=b, H=s["H"][keep], L=s["L"][keep], C=s["C"][keep])).groupby("b")
    H, L, C = df.H.max().to_numpy(), df.L.min().to_numpy(), df.C.last().to_numpy()
    prev = np.r_[np.nan, C[:-1]]
    tr = np.r_[H[0] - L[0], np.maximum(H[1:] - L[1:], np.maximum(np.abs(H[1:] - prev[1:]), np.abs(L[1:] - prev[1:])))]
    return float(tr[-ATR_N:].mean())


def levels(s: dict, A: float) -> dict[str, np.ndarray]:
    vw = session_vwap(s["H"], s["L"], s["C"], s["V"])
    out = {"vwap": vw, "twap": session_twap(s["H"], s["L"], s["C"])}
    for k, name in zip(SHIFTS, PLACEBOS):
        out[name] = vw + k * A
    return out


# ---------------------------------------------------------------- H0b: touches

def stratum(side: int, minute: int, fast: bool) -> int:
    t = int(np.searchsorted(TIME_EDGES, minute, side="right"))
    return ((0 if side > 0 else 1) * (len(TIME_EDGES) + 1) + t) * 2 + (0 if fast else 1)


def passage(s: dict, i: int, side: int, lv: float, x: float) -> int:
    """First passage from a touch of `lv` at bar i, approached from `side` (+1 = from above)."""
    H, L = s["H"], s["L"]
    if (L[i] <= lv - x) if side > 0 else (H[i] >= lv + x):
        return BREAK
    for j in range(i + 1, len(H)):
        up, dn = H[j] >= lv + x, L[j] <= lv - x
        rej, brk = (up, dn) if side > 0 else (dn, up)
        if rej and brk:
            return AMBIG
        if rej:
            return REJECT
        if brk:
            return BREAK
    return OPEN_


def touches(s: dict, lv: np.ndarray, A: float, ok: np.ndarray | None = None) -> list[tuple[int, int, int, int]]:
    """(bar, side, stratum, outcome) for every touch of the level path `lv`. `ok[i]` gates a touch at bar i."""
    H, L, C, m = s["H"], s["L"], s["C"], s["m"]
    out, side, last_far = [], 0, -1
    for i in range(1, len(C)):
        if m[i] > TOUCH_LAST:
            break
        ref = lv[i - 1]
        tol = TOUCH_TOL * A
        if side and TOUCH_FIRST <= m[i] and (L[i] <= ref + tol if side > 0 else H[i] >= ref - tol):
            if ok is None or ok[i]:
                res = passage(s, i, side, ref, EXCURSION * A)
                out.append((i, side, stratum(side, int(m[i]), i - last_far <= FAST_BARS), res))
            side = 0
        if m[i] >= A_READY - 1:          # this bar closes at or after 10:40, when A is known
            d = C[i] - lv[i]
            if abs(d) >= ARM * A:
                side, last_far = (1 if d > 0 else -1), i
    return out


def session_counts(s: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Per level x stratum x outcome touch counts, and H0a volume sums / counts per group x stratum."""
    A = session_atr(s)
    if not (A > 0):
        return None
    lv = levels(s, A)
    cnt = np.zeros((len(LEVELS), N_STRATA, 4))
    sep = np.r_[False, np.abs(lv["vwap"] - lv["twap"])[:-1] >= TWAP_SEP * A]
    for k, name in enumerate(LEVELS):
        for _, _, st, res in touches(s, lv[name], A, sep if name == "twap" else None):
            cnt[k, st, res] += 1
    vsum, vn = volume_cells(s, lv, A)
    return cnt, vsum, vn


# ---------------------------------------------------------------- H0a: volume at VWAP

def volume_cells(s: dict, lv: dict, A: float) -> tuple[np.ndarray, np.ndarray]:
    """Sum and count of log relative volume, [group (0 vwap, 1 shift), stratum]."""
    H, L, V, m = s["H"], s["L"], s["V"], s["m"]
    win = np.flatnonzero((m >= TOUCH_FIRST) & (m <= TOUCH_LAST) & (V > 0))
    win = win[win >= 1]
    vsum, vn = np.zeros((2, N_VSTRATA)), np.zeros((2, N_VSTRATA))
    if len(win) == 0:
        return vsum, vn
    y = np.log(V[win] / np.median(V[win]))

    def holds(name):
        x = lv[name][win - 1]
        return (L[win] <= x) & (x <= H[win])

    at_v = holds("vwap")
    at_s = holds(f"shift{-0.75:+.2f}") | holds(f"shift{0.75:+.2f}")
    st = ((m[win] - OPEN) // 30) * (len(RANGE_BINS) + 1) + np.searchsorted(RANGE_BINS, (H[win] - L[win]) / A, side="right")
    for g, mask in enumerate((at_v & ~at_s, at_s & ~at_v)):
        np.add.at(vsum[g], st[mask], y[mask])
        np.add.at(vn[g], st[mask], 1)
    return vsum, vn


# ---------------------------------------------------------------- scoring

def p_reject(cnt: np.ndarray) -> np.ndarray:
    """P(reject) per stratum from [..., stratum, outcome] counts (nan where nothing resolved)."""
    res = cnt[..., REJECT] + cnt[..., BREAK]
    return np.where(res > 0, cnt[..., REJECT] / np.where(res > 0, res, 1), np.nan)


def delta(cnt: np.ndarray, level: int = 0) -> float:
    """Stratum-weighted P(reject | level) - P(reject | pooled shifts); cnt is [level, stratum, outcome]."""
    pv = p_reject(cnt[level])
    pp = p_reject(cnt[1:1 + len(SHIFTS)].sum(0))
    w = cnt[level, :, REJECT] + cnt[level, :, BREAK]
    ok = ~np.isnan(pv) & ~np.isnan(pp) & (w > 0)
    return float((w[ok] * (pv[ok] - pp[ok])).sum() / w[ok].sum()) if ok.any() else float("nan")


def vdelta(vsum: np.ndarray, vn: np.ndarray) -> float:
    ok = (vn[0] > 0) & (vn[1] > 0)
    if not ok.any():
        return float("nan")
    mv, ms = vsum[0, ok] / vn[0, ok], vsum[1, ok] / vn[1, ok]
    return float((vn[0, ok] * (mv - ms)).sum() / vn[0, ok].sum())


def boot_weights(n: int, n_boot: int = N_BOOT) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    return rng.multinomial(n, np.full(n, 1 / n), size=n_boot).astype(float)


def score(per: dict[date, tuple]) -> dict:
    days = sorted(per)
    if not days:
        return dict(sessions=0)
    cnt = np.stack([per[d][0] for d in days])
    vsum = np.stack([per[d][1] for d in days])
    vn = np.stack([per[d][2] for d in days])
    W = boot_weights(len(days))
    bc = np.einsum("bs,slko->blko", W, cnt)
    bvs, bvn = np.einsum("bs,sgk->bgk", W, vsum), np.einsum("bs,sgk->bgk", W, vn)
    tot = cnt.sum(0)
    d = delta(tot)
    draws = np.array([delta(c) for c in bc])
    vd = vdelta(vsum.sum(0), vn.sum(0))
    vdraws = np.array([vdelta(a, b) for a, b in zip(bvs, bvn)])
    tw = delta(tot, LEVELS.index("twap"))
    years: dict[int, list] = {}
    for k, day in enumerate(days):
        years.setdefault(day.year, []).append(k)
    per_level = {}
    for k, name in enumerate(LEVELS):
        c = tot[k].sum(0)
        res = c[REJECT] + c[BREAK]
        per_level[name] = dict(touches=int(c.sum()), resolved=int(res),
                               p_reject=float(c[REJECT] / res) if res else None,
                               ambiguous=float(c[AMBIG] / c.sum()) if c.sum() else None,
                               unresolved=float(c[OPEN_] / c.sum()) if c.sum() else None)
    lo = float(np.nanquantile(draws, ALPHA))
    return dict(
        sessions=len(days), first=str(days[0]), last=str(days[-1]), per_level=per_level,
        delta=d, lower=lo, ci95=[float(np.nanquantile(draws, .025)), float(np.nanquantile(draws, .975))],
        boot_nan=float(np.isnan(draws).mean()),
        by_side={side: delta(tot[:, [st for st in range(N_STRATA) if (st // (2 * (len(TIME_EDGES) + 1)) == j)]])
                 for j, side in enumerate(("from_above", "from_below"))},
        by_year={y: delta(cnt[ix].sum(0)) for y, ix in sorted(years.items())},
        twap_delta=tw,
        vol_delta=vd, vol_ci95=[float(np.nanquantile(vdraws, .025)), float(np.nanquantile(vdraws, .975))],
        vol_bars=[int(vn[:, 0].sum()), int(vn[:, 1].sum())],
        passed=bool(d >= MIN_EFFECT and lo > 0))


def run(sessions: dict[date, dict]) -> dict:
    per = {}
    for d, s in sessions.items():
        c = session_counts(s)
        if c is not None:
            per[d] = c
    out = score(per)
    out["skipped"] = len(sessions) - len(per)
    return out


# ---------------------------------------------------------------- main

def script_sha() -> str:
    """Hash of the spec: this file and amt_lucid_study.py, whose constants and loader it uses."""
    h = hashlib.sha256()
    for f in SPEC_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def coverage_problems(sessions: dict) -> list[str]:
    per = {y: 0 for y in range(CONFIRM_START.year, CONFIRM_END.year + 1)}
    for d in sessions:
        per[d.year] = per.get(d.year, 0) + 1
    return [f"{y}: {n} sessions" for y, n in per.items() if n < MIN_SESSIONS_PER_YEAR]


def looks() -> list[str]:
    return [l for l in LOOKS.read_text().splitlines() if l.strip()] if LOOKS.exists() else []


def fmt(x, spec="+.4f") -> str:
    return "    n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else format(x, spec)


def report(sym: str, r: dict) -> None:
    print(f"\n{sym}  {r['sessions']} sessions {r.get('first')} -> {r.get('last')} ({r['skipped']} skipped: no A)")
    print(f"  {'level':<12} {'touches':>8} {'resolved':>9} {'P(reject)':>10} {'ambig':>7} {'unres':>7}")
    for name, c in r["per_level"].items():
        print(f"  {name:<12} {c['touches']:>8} {c['resolved']:>9} {fmt(c['p_reject'], '10.4f')} "
              f"{fmt(c['ambiguous'], '7.3f')} {fmt(c['unresolved'], '7.3f')}")
    print(f"  H0b delta (VWAP - shifts, stratified) {r['delta']:+.4f}  95% CI [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}]"
          f"  lower@{ALPHA:.3f} {r['lower']:+.4f}  -> {'PASS' if r['passed'] else 'FAIL'} (needs >= {MIN_EFFECT:+.2f}, lower > 0)")
    print(f"  by side: {', '.join(f'{k} {fmt(v)}' for k, v in r['by_side'].items())}")
    print(f"  by year: {', '.join(f'{y} {fmt(v)}' for y, v in r['by_year'].items())}")
    print(f"  TWAP delta (secondary, |VWAP-TWAP| >= {TWAP_SEP} A only): {fmt(r['twap_delta'])}")
    print(f"  H0a log-volume delta (bars at VWAP vs at +-0.75 shift): {fmt(r['vol_delta'])}  "
          f"95% CI [{fmt(r['vol_ci95'][0])}, {fmt(r['vol_ci95'][1])}]  bars {r['vol_bars'][0]} vs {r['vol_bars'][1]}")


def explore(sha: str) -> dict:
    res = dict(script_sha=sha)
    for sym in ("SPY", "QQQ"):
        res[sym] = run(load_xnas(sym))
        report(sym, res[sym])
    res["passed"] = bool(res["SPY"]["passed"] and res["QQQ"]["passed"])
    print(f"\nexploration gate (both SPY and QQQ; script {sha}): "
          f"{'PASS: ES / NQ may be read once' if res['passed'] else 'FAIL: stage killed, ES / NQ stay unread'}")
    (OUT / "explore.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--explore", action="store_true", help="XNAS SPY + QQQ <= 2025-03-26 (repeatable)")
    mode.add_argument("--freeze", action="store_true", help="re-run the exploration and pin the script hash")
    mode.add_argument("--confirm", action="store_true", help="score once on ES and NQ 2012-2021")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    sha = script_sha()

    if args.explore:
        explore(sha)
        return 0

    if args.freeze:
        if PREREG.exists() or looks():
            print(f"already frozen ({PREREG}) or already scored ({LOOKS}); refusing")
            return 1
        passed = explore(sha)["passed"]
        PREREG.write_text(json.dumps(dict(script_sha=sha, explore_passed=passed, alpha=ALPHA, min_effect=MIN_EFFECT,
                                          frozen_at=pd.Timestamp.now(tz="UTC").isoformat()), indent=1) + "\n")
        print(f"frozen script {sha}. Commit {PREREG.name} now.")
        return 0

    if looks() or (OUT / "results.json").exists():
        print(f"already scored ({'; '.join(looks()) or OUT / 'results.json'}); refusing a second look")
        return 1
    if not PREREG.exists():
        print("run --explore and --freeze first")
        return 1
    pin = json.loads(PREREG.read_text())
    if pin["script_sha"] != sha:
        print(f"spec changed since --freeze ({pin['script_sha']} -> {sha}); refusing")
        return 1
    if not pin["explore_passed"]:
        print("exploration failed the gate: nothing to confirm, ES / NQ left unread")
        return 0
    data = {sym: load_fut(sym) for sym in ("ES", "NQ")}
    gaps = [f"{sym} {g}" for sym, ss in data.items() for g in coverage_problems(ss)]
    if gaps:
        print(f"download incomplete ({', '.join(gaps)}; need >= {MIN_SESSIONS_PER_YEAR} a year); "
              "nothing scored, the look is not spent")
        return 1
    with LOOKS.open("a") as f:
        f.write(f"script={sha} sessions=ES:{len(data['ES'])},NQ:{len(data['NQ'])} "
                f"at {pd.Timestamp.now(tz='UTC').isoformat()}\n")
    print(f"look logged in {LOOKS.name}: commit it with the results")
    res = {}
    for sym, ss in data.items():
        res[sym] = run(ss)
        report(f"{sym} (one look)", res[sym])
    res["verdicts"] = {sym: "PASS" if res[sym]["passed"] else "FAIL" for sym in data}
    special = all(v == "PASS" for v in res["verdicts"].values())
    print(f"\nVERDICTS (alpha {ALPHA:.4f}, min effect {MIN_EFFECT:+.2f}): {res['verdicts']} -> "
          f"{'VWAP is special: Stage 1 may be scoped' if special else 'VWAP not shown special: stop here'}")
    (OUT / "results.json").write_text(json.dumps(dict(prereg=pin, result=res), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
