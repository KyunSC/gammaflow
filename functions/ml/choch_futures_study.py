"""4-hour change of character (CHoCH) on CME ES and NQ, 2012-2021, scored ONCE against coin-flip twins.

The rule is choch_crypto_study.SPEC, unchanged (choch_events, k=2, 0.1 ATR pad, 1R target, 20-day cap), so the
crypto train block and this futures window test the same frozen rule. Sunny chose on 2026-10-28 to spend this window
now rather than only after a crypto pass. The 2012-2021 ES and NQ 1m bars are the one-look confirmation sets of
vp_claims_study.py (ES, PR #10) and trader_playbooks_study.py (NQ, PR #11), and the window PR #13 planned to share;
this look reads the same files, so those confirmations are no longer the first use of this data.

Futures specifics (fixed before any futures bar was read for this rule):
  - data: Databento GLBX.MDP3 ES.v.0 / NQ.v.0 ohlcv-1m, all hours (databento_fetch.py es-ohlcv-1m-early and
    nq-ohlcv-1m-early), Globex sessions with an ET trade date 2012-01-03 -> 2021-12-31.
  - 4h bars: anchored to the 18:00 ET Globex open, so 18-22, 22-02, 02-06, 06-10, 10-14 and 14-17 (3h). A bar never
    spans a session break or a contract change.
  - rolls: the volume-rolled front contract jumps at a roll. A contract change starts a new run: swings, ATR and
    signals restart, and a trade still open at a run's last bar closes there ("roll"), like trader_playbooks_study.
  - execution on 1m bars: market entry at the open of the bar after the 4h close, 1 tick worse. A stop fills at the
    stop, or at the open of a bar opening through it, 1 tick worse; a bar touching stop and target is the stop.
    The target fills at its price when a bar trades a tick through it, or at the open of a bar opening through it.
    Time, roll and data-end exits fill at the bar's close, 1 tick worse.
  - costs: $4.50 round trip per contract (ES $50/pt, NQ $20/pt). R = (points - costs) / the planned stop distance
    (from the signal close). Each trade is also scored with no costs (gross) and at doubled friction (2 ticks per
    slipped fill, 2x commission: mean_2x).
  - book: one position per instrument; each signal is simulated long and short (the mirror), and a new signal is
    taken only once both are flat, so the twins share every entry, stop, target and exit.
  - twins: mfp_crypto_study.r_test, 2,000 coin flips with P(long) = the rule's long share; fair coin reported.
  - verdict per instrument: PASS when twin p < ALPHA (0.05 / 2), the excess CI is above zero, mean net R > 0 and
    mean_2x > 0. C6 on futures passes only if ES and NQ both pass. k = 1, 3, 5 are reported, never selected.

One look: script_sha() hashes this file and choch_crypto_study.py, and choch_futures_prereg.json (committed) pins
it. --score refuses when choch_futures_looks.log (committed) has a look, when the hash changed, or when either
download misses a year (>= 230 sessions in each of 2012-2021); then it appends the look before scoring.

    python functions/ml/databento_fetch.py es-ohlcv-1m-early nq-ohlcv-1m-early --start 2012-01-01 --end 2022-01-01   # free quote
    python functions/ml/databento_fetch.py es-ohlcv-1m-early nq-ohlcv-1m-early --start 2012-01-01 --end 2022-01-01 --download --max-cost 50
    python functions/ml/choch_futures_study.py --check     # coverage only, reads no prices, spends nothing
    python functions/ml/choch_futures_study.py --score     # once; then commit choch_futures_looks.log
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import choch_crypto_study as cs  # noqa: E402
import mfp_crypto_study as mfp  # noqa: E402

ET = "America/New_York"
DATA = HERE / "data" / "databento"
DIRS = {"ES": DATA / "es-ohlcv-1m-early" / "ES", "NQ": DATA / "nq-ohlcv-1m-early" / "NQ"}
OUT = HERE / "data" / "choch_futures"
PREREG, LOOKS = HERE / "choch_futures_prereg.json", HERE / "choch_futures_looks.log"   # committed, unlike OUT
SPEC_FILES = (Path(__file__).resolve(), HERE / "choch_crypto_study.py")
START, END = date(2012, 1, 3), date(2021, 12, 31)
MIN_SESSIONS_PER_YEAR = 230

TICK = 0.25
PV = {"ES": 50.0, "NQ": 20.0}
COMMISSION_RT = 4.50
ALPHA = 0.05 / 2
SESSION_OPEN_H = 18
BAR_MINUTES = 240


# ---------------------------------------------------------------- data

@dataclass
class Tape:
    t: np.ndarray        # epoch seconds
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    inst: np.ndarray
    session: np.ndarray  # Globex trade date as a day number (the 18:00 ET open's next calendar day)
    bucket: np.ndarray   # 4h bucket within the session, 0..5

    @property
    def n(self) -> int:
        return len(self.t)


def tape_from_frame(df: pd.DataFrame) -> Tape:
    """df indexed by UTC ts_event with open/high/low/close/instrument_id."""
    et = df.index.tz_convert(ET).tz_localize(None)
    since_open = et - pd.Timedelta(hours=SESSION_OPEN_H)
    day0 = since_open.normalize()
    minutes = ((since_open - day0) // pd.Timedelta(minutes=1)).to_numpy()
    session = ((day0 - pd.Timestamp(0)).days + 1).to_numpy()  # 18:00 Sunday -> Monday's trade date
    return Tape(t=df.index.as_unit("s").asi8.astype(np.int64), o=df["open"].to_numpy(float), h=df["high"].to_numpy(float),
                l=df["low"].to_numpy(float), c=df["close"].to_numpy(float), inst=df["instrument_id"].to_numpy(np.int64),
                session=session, bucket=minutes // BAR_MINUTES)


def load(symbol: str, bars_dir: Path | None = None) -> Tape:
    bars_dir = bars_dir or DIRS[symbol]
    files = sorted(bars_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bars in {bars_dir}; run databento_fetch.py {bars_dir.parent.name}")
    lo = pd.Timestamp(START, tz=ET) - pd.Timedelta(hours=24 - SESSION_OPEN_H)   # 18:00 ET the evening before
    hi = pd.Timestamp(END, tz=ET) + pd.Timedelta(hours=SESSION_OPEN_H)          # 18:00 ET on the last trade date
    lo, hi = lo.tz_convert("UTC"), hi.tz_convert("UTC")
    cols = ["open", "high", "low", "close", "instrument_id"]
    df = pd.concat([pd.read_parquet(f, columns=cols, filters=[("ts_event", ">=", lo), ("ts_event", "<", hi)])
                    for f in files]).sort_index()
    df = df[~df.index.duplicated()]
    assert (df.index < hi).all(), "LEAK: bar read reaches past the window"
    return tape_from_frame(df)


def sessions_per_year(tp: Tape) -> dict[int, int]:
    days = pd.to_datetime(np.unique(tp.session), unit="D")
    return {y: int((days.year == y).sum()) for y in range(START.year, END.year + 1)}


def coverage_problems(tp: Tape) -> list[str]:
    return [f"{y}: {k} sessions" for y, k in sessions_per_year(tp).items() if k < MIN_SESSIONS_PER_YEAR]


# ---------------------------------------------------------------- signals

@dataclass
class FSignal:
    sig: int         # 1m index of the 4h bar's last minute; entry at sig + 1
    side: int
    stop: float      # price level
    target: float    # price level
    dist: float      # planned risk in points, from the signal close
    end: int         # last 1m index the trade may be held through


def runs(tp: Tape) -> list[tuple[int, int]]:
    """[a, b) of each contiguous contract run."""
    s = mfp.run_starts(tp.inst)
    return list(zip(s, np.r_[s[1:], tp.n]))


def signals(tp: Tape, k: int) -> list[FSignal]:
    f = cs.SPEC["fixed"]
    out = []
    for a, b in runs(tp):
        key = tp.session[a:b] * 8 + tp.bucket[a:b]
        first = mfp.run_starts(key) + a
        last = np.r_[first[1:] - 1, b - 1]
        H = np.maximum.reduceat(tp.h[a:b], first - a)
        L = np.minimum.reduceat(tp.l[a:b], first - a)
        C = tp.c[last]
        atr = pd.Series(mfp.true_range(H, L, C)).rolling(f["atr_bars"]).mean().to_numpy()
        for j, side, extreme in cs.choch_events(H, L, C, k):
            if not np.isfinite(atr[j]):
                continue
            s = int(last[j])
            if s + 1 >= b:
                continue
            stop = extreme + side * -1 * f["pad_atr"] * atr[j]
            dist = side * (tp.c[s] - stop)
            if dist <= 0:
                continue
            cap = int(np.searchsorted(tp.t, tp.t[s + 1] + f["hold_days"] * 86400, side="left")) - 1
            out.append(FSignal(s, side, stop, tp.c[s] + side * f["target_r"] * dist, dist, min(cap, b - 1)))
    return out


# ---------------------------------------------------------------- execution

@dataclass
class FLeg:
    side: int
    exit: int
    reason: str
    points: float    # side x (exit - entry) before slippage and commission
    slipped: int     # fills that take slippage (entry, and a non-target exit)
    dist: float

    def r(self, pv: float, slip_ticks: float = 1, comm_mult: float = 1) -> float:
        return (self.points - self.slipped * slip_ticks * TICK - comm_mult * COMMISSION_RT / pv) / self.dist


def simulate(tp: Tape, sg: FSignal, side: int, roll_end: int) -> FLeg:
    """One side of a signal. side == sg.side trades the rule; the other side mirrors stop and target."""
    e = sg.sig + 1
    stop = sg.stop if side == sg.side else tp.c[sg.sig] - side * sg.dist
    tgt = sg.target if side == sg.side else tp.c[sg.sig] + side * sg.dist
    sl = slice(e, sg.end + 1)
    xo, xc = side * tp.o[sl], side * tp.c[sl]
    xh, xl = (tp.h[sl], tp.l[sl]) if side > 0 else (-tp.l[sl], -tp.h[sl])
    xs, xt, x0 = side * stop, side * tgt, side * tp.o[e]
    hit_s, hit_t = xl <= xs, xh >= xt + TICK
    hit = hit_s | hit_t
    j = int(np.argmax(hit)) if hit.any() else len(xo) - 1
    if hit[j] and hit_s[j]:
        xf, reason, slipped = min(xo[j], xs), "stop", 2
    elif hit[j]:
        xf, reason, slipped = (xo[j] if xo[j] >= xt + TICK else xt), "target", 1
    else:
        end = e + j
        reason = "data-end" if end == tp.n - 1 else "roll" if end == roll_end else "time"
        xf, slipped = xc[j], 2
    return FLeg(side, e + j, reason, float(xf - x0), slipped, float(sg.dist))


@dataclass
class FTrade:
    sig: FSignal
    legs: dict

    @property
    def exit(self) -> int:
        return max(self.legs[1].exit, self.legs[-1].exit)


def run_book(tp: Tape, sigs: list[FSignal]) -> list[FTrade]:
    roll_end = np.empty(tp.n, np.int64)
    for a, b in runs(tp):
        roll_end[a:b] = b - 1
    out, busy = [], -1
    for sg in sorted(sigs, key=lambda s: s.sig):
        if sg.sig + 1 <= busy:
            continue
        tr = FTrade(sg, {s: simulate(tp, sg, s, int(roll_end[sg.sig])) for s in (1, -1)})
        out.append(tr)
        busy = tr.exit
    return out


# ---------------------------------------------------------------- scoring

def mirrors(trades: list[FTrade], pv: float, slip: float = 1, comm: float = 1):
    rl = np.array([t.legs[1].r(pv, slip, comm) for t in trades])
    rs = np.array([t.legs[-1].r(pv, slip, comm) for t in trades])
    return rl, rs, np.array([t.sig.side for t in trades])


def lookahead_dirs(tp: Tape, trades: list[FTrade], frac: float = mfp.LOOKAHEAD_FRAC) -> np.ndarray:
    """Planted bug: the side of the price `frac` of the way from entry to the trade's cap. Must pass."""
    e = np.array([t.sig.sig + 1 for t in trades])
    later = e + (frac * (np.array([t.sig.end for t in trades]) - e)).astype(int)
    return np.where(tp.c[later] >= tp.o[e], 1, -1)


def score(tp: Tape, symbol: str, k: int, n_twins: int, controls: bool) -> dict:
    pv = PV[symbol]
    trades = run_book(tp, signals(tp, k))
    if not trades:
        return dict(trades=0)
    rl, rs, dirs = mirrors(trades, pv)
    gl, gs, _ = mirrors(trades, pv, 0, 0)
    dl, ds, _ = mirrors(trades, pv, 2, 2)
    taken = [t.legs[int(d)] for t, d in zip(trades, dirs)]
    yr = pd.to_datetime(tp.t[[t.sig.sig for t in trades]], unit="s", utc=True).year.to_numpy()
    r = mfp.taken(rl, rs, dirs)
    ex = mfp.excess(rl, rs, dirs, mfp.long_share(dirs))
    res = dict(k=k, trades=len(trades), long_share=mfp.long_share(dirs),
               mean_r=float(r.mean()), gross=float(mfp.taken(gl, gs, dirs).mean()),
               mean_2x=float(mfp.taken(dl, ds, dirs).mean()),
               win_rate=float((r > 0).mean()), median_stop_points=float(np.median([t.sig.dist for t in trades])),
               median_hold_h=float(np.median([(tp.t[lg.exit] - tp.t[t.sig.sig + 1]) / 3600 for t, lg in zip(trades, taken)])),
               exits=pd.Series([lg.reason for lg in taken]).value_counts().to_dict(),
               twins=mfp.r_test(rl, rs, dirs, n_twins=n_twins),
               fair_coin=mfp.r_test(rl, rs, dirs, p_long=0.5, n_twins=n_twins),
               years={int(y): dict(trades=int((yr == y).sum()), mean_r=float(r[yr == y].mean()),
                                   excess=float(ex[yr == y].mean())) for y in np.unique(yr)})
    if controls:
        coins = [mfp.r_test(rl, rs, mfp.coin_dirs(len(trades), mfp.SEED + 100 + i), n_twins=n_twins, seed=mfp.SEED + i)
                 for i in range(mfp.COIN_CONTROLS)]
        res["controls"] = dict(lookahead=mfp.r_test(rl, rs, lookahead_dirs(tp, trades), n_twins=n_twins),
                               coin_pass_rate=float(np.mean([mfp.passes(c, ALPHA) for c in coins])))
    return res


def verdict(res: dict) -> str:
    if not res.get("trades"):
        return "NO TRADES"
    ok = mfp.passes(res["twins"], ALPHA) and res["mean_r"] > 0 and res["mean_2x"] > 0
    return "PASS" if ok else "FAIL"


def script_sha() -> str:
    h = hashlib.sha256()
    for f in SPEC_FILES:
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def looks() -> list[str]:
    return [x for x in LOOKS.read_text().splitlines() if x.strip()] if LOOKS.exists() else []


def report(symbol: str, res: dict) -> None:
    if not res.get("trades"):
        print(f"{symbol} k={res.get('k')}: no trades")
        return
    t = res["twins"]
    print(f"{symbol} k={res['k']}: n={res['trades']} long {res['long_share']:.2f} win {res['win_rate']:.3f} "
          f"net {res['mean_r']:+.3f}R gross {res['gross']:+.3f} 2x {res['mean_2x']:+.3f} | twins {t['twin_mean_r']:+.3f} "
          f"excess {t['excess']:+.3f} CI [{t['excess_ci'][0]:+.3f}, {t['excess_ci'][1]:+.3f}] p={t['p']:.4f} "
          f"| exits {res['exits']}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="coverage and hash only; spends nothing")
    mode.add_argument("--score", action="store_true", help="the one look at ES + NQ 2012-2021")
    ap.add_argument("--twins", type=int, default=mfp.N_TWINS)
    a = ap.parse_args(argv)
    sha = script_sha()
    pin = json.loads(PREREG.read_text())
    if pin["script_sha"] != sha:
        print(f"spec changed since it was frozen ({pin['script_sha']} -> {sha}); refusing")
        return 1
    if looks():
        print(f"already scored ({'; '.join(looks())}); refusing a second look")
        return 1
    tapes = {s: load(s) for s in DIRS}
    gaps = {s: coverage_problems(tp) for s, tp in tapes.items()}
    for s, tp in tapes.items():
        print(f"{s}: {tp.n} bars, sessions per year {sessions_per_year(tp)}")
    if any(gaps.values()):
        print(f"download incomplete {gaps} (need >= {MIN_SESSIONS_PER_YEAR} a year); nothing scored, the look is not spent")
        return 1
    if a.check:
        print(f"coverage ok, spec {sha}: ready for --score")
        return 0
    with LOOKS.open("a") as f:
        f.write(f"script={sha} at {pd.Timestamp.now(tz='UTC').isoformat()} es_bars={tapes['ES'].n} nq_bars={tapes['NQ'].n}\n")
    print(f"look logged in {LOOKS.name}: commit it with the results")
    primary = cs.SPEC["primary"]["k"]
    results = dict(prereg=pin, alpha=ALPHA, symbols={})
    for s, tp in tapes.items():
        rows = {}
        for k in cs.SPEC["grid"]["k"]:
            rows[k] = score(tp, s, k, a.twins, controls=k == primary)
            report(s, rows[k])
        rows[primary]["verdict"] = verdict(rows[primary])
        results["symbols"][s] = dict(primary=rows[primary], sensitivity={k: v for k, v in rows.items() if k != primary})
    verdicts = {s: v["primary"]["verdict"] for s, v in results["symbols"].items()}
    results["verdict"] = "PASS on ES and NQ" if all(v == "PASS" for v in verdicts.values()) else f"FAIL {verdicts}"
    print(f"\nC6 on futures (alpha {ALPHA:.3f} each, k={primary}): {results['verdict']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
