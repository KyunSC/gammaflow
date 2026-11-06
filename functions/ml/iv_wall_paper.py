"""Forward paper journal for the frozen NQ IV-wall break (iv_wall_grid_prereg.json pick: touch / fixed 2R / 0.4 sigma).

The rules are not re-implemented here: the bars go through frontend/lib/ivWalls.js (frontend/scripts/
iv-walls-replay.mjs), so the journal records exactly what the chart's "IV Walls (break)" indicator shows.

Sources, per session:
  * databento: NQ.v.0 1m bars on disk (data/databento/fut-ohlcv-1m-cont/NQ), aggregated to 5m, roll sessions from
    the instrument id (as the backtest). Used whenever the session is complete on disk.
  * yahoo: NQ=F 5m bars from yfinance (last 60 days), calendar roll rule (as the chart).
  VXN closes come from yfinance ^VXN, filled from the Cboe file on disk for dates Yahoo lacks.

Only finished sessions (ET date before today, or today after 16:10 ET) are logged, from 2026-08-17 (the first
session after the last bar any IV-wall study read). Rows are append-only: a logged date is never rewritten. To rebuild
from scratch, delete data/iv_wall/paper/.

Costs per MNQ are the evaluator's base case: 1 tick on the stop entry, 1 tick on stop / flat exits, 0 on targets,
$0.50 per side. MNQ count = floor(--risk / (risk_pts x $2)); 0 means the trade is too big for the budget.

    cd functions/ml && ../../.venv/bin/python -B iv_wall_paper.py [--risk 500] [--source auto|databento|yahoo]
    cd functions/ml && ../../.venv/bin/python -B iv_wall_paper.py --today [--risk 500]   # this morning's orders
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ML = Path(__file__).resolve().parent
ROOT = ML.parent.parent
REPLAY = ROOT / "frontend" / "scripts" / "iv-walls-replay.mjs"
BARS = ML / "data" / "databento" / "fut-ohlcv-1m-cont" / "NQ"
CBOE_VXN = ML / "data" / "iv_wall" / "cboe" / "VXN_History.csv"
OUT = ML / "data" / "iv_wall" / "paper"
ET = ZoneInfo("America/New_York")
START = date(2026, 8, 17)
WARMUP_DAYS = 70          # calendar days of bars before START (20 daily returns + slack)
TICK, POINT_VALUE, COMMISSION = 0.25, 2.0, 0.50
EXIT_SLIP = {"stop": 1, "target": 0, "flat": 1, "open": 1}
# NYSE full-day closures on weekdays, for --today only (the journal finds holidays from the bars). Extend yearly.
NYSE_CLOSED = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
               "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}

SESSION_COLS = ["date", "source", "status", "pc", "pc_date", "vol", "vol_date", "sigma", "upper", "lower", "risk_pts",
                "mnq", "trades", "day_usd", "logged_at"]
TRADE_COLS = ["date", "source", "side", "wall", "entry_et", "entry", "stop", "target", "risk_pts", "exit_et", "exit",
              "exit_kind", "r_gross", "usd_per_mnq", "r_net", "mnq", "usd"]


def et_str(t: float) -> str:
    return datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d %H:%M")


def epoch_s(idx: pd.DatetimeIndex) -> np.ndarray:
    """UTC epoch seconds, whatever the index's unit (Yahoo's is not always ns)."""
    return np.asarray((idx.tz_convert("UTC") - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1), dtype=np.int64)


def to5m(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby((epoch_s(df.index) // 300) * 300)
    out = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    if "instrument_id" in df:
        out["instrument_id"] = g["instrument_id"].last()
    return out


def databento_bars(lo: date):
    files = [f for f in sorted(BARS.glob("*.parquet")) if date.fromisoformat(f.name[11:21]) > lo]
    if not files:
        return None
    raw = pd.concat([pd.read_parquet(f, columns=["open", "high", "low", "close", "instrument_id", "symbol"]) for f in files])
    raw = raw[raw["symbol"] == "NQ.v.0"]
    raw = raw[~raw.index.duplicated(keep="last")].sort_index()
    b = to5m(raw)
    # Roll sessions: the RTH front contract differs from the previous session's (the backtest's rule).
    et = pd.to_datetime(b.index, unit="s", utc=True).tz_convert(ET)
    mod = et.hour * 60 + et.minute
    rth = b[(mod >= 570) & (mod < 960)].copy()
    rth["d"] = et[(mod >= 570) & (mod < 960)].strftime("%Y-%m-%d")
    inst = rth.groupby("d")["instrument_id"].agg(lambda s: s.mode().iloc[0])
    rolls = [d for d, p, c in zip(inst.index[1:], inst.values[:-1], inst.values[1:]) if c != p]
    last = datetime.fromtimestamp(int(b.index[-1]) + 300, ET)
    return b, rolls, last


def yahoo_bars():
    import yfinance as yf
    h = yf.Ticker("NQ=F").history(period="60d", interval="5m", auto_adjust=False)
    if h.empty:
        return None
    h = h.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    h.index = epoch_s(h.index)
    last = datetime.fromtimestamp(int(h.index[-1]) + 300, ET)
    return h, None, last


def vxn_closes() -> list[dict]:
    rows = {}
    if CBOE_VXN.exists():
        c = pd.read_csv(CBOE_VXN).dropna(subset=["CLOSE"])
        for d, v in zip(pd.to_datetime(c["DATE"], format="%m/%d/%Y").dt.date, c["CLOSE"]):
            rows[d.isoformat()] = float(v)
    try:
        import yfinance as yf
        y = yf.Ticker("^VXN").history(period="1y", interval="1d", auto_adjust=False)
        for ts, v in zip(y.index, y["Close"]):
            if math.isfinite(v):
                rows[ts.tz_convert(ET).date().isoformat()] = float(v)  # Yahoo wins where both have the date
    except Exception as e:  # offline: the Cboe file alone
        print(f"warning: ^VXN from Yahoo failed ({e}); using the Cboe file only")
    return [{"d": d, "c": c} for d, c in sorted(rows.items())]


def replay(bars: pd.DataFrame, rolls, vols, targets=()) -> dict:
    inp = {"time": [int(t) for t in bars.index], "open": bars["open"].tolist(), "high": bars["high"].tolist(),
           "low": bars["low"].tolist(), "close": bars["close"].tolist(), "vols": vols, "rollSessions": rolls,
           "targets": list(targets)}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(inp, f)
    try:
        out = subprocess.run(["node", str(REPLAY), f.name], cwd=REPLAY.parent.parent, check=True,
                             capture_output=True, text=True).stdout
    finally:
        Path(f.name).unlink(missing_ok=True)
    return json.loads(out)


def finished(d: str, last_bar_end: datetime, now: datetime) -> bool:
    """The session's RTH is over and the bars reach past its 16:00 ET close."""
    close = datetime.combine(date.fromisoformat(d), datetime.min.time(), ET) + timedelta(hours=16)
    return last_bar_end >= close and now >= close + timedelta(minutes=10)


def trade_row(s: dict, source: str, risk_usd: float) -> dict:
    kind = s["exitKind"]
    exit_px = s.get("exit", s["entry"] + s["r"] * s["risk"] * s["side"])
    gross = s["side"] * (exit_px - s["entry"])
    per = (gross - (1 + EXIT_SLIP[kind]) * TICK) * POINT_VALUE - 2 * COMMISSION
    mnq = int(risk_usd // (s["risk"] * POINT_VALUE))
    return {"date": s["date"], "source": source, "side": "long" if s["side"] > 0 else "short", "wall": s["wall"],
            "entry_et": et_str(s["entryTime"]), "entry": round(s["entry"], 2), "stop": round(s["stop"], 2),
            "target": round(s["target"], 2), "risk_pts": round(s["risk"], 2),
            "exit_et": et_str(s["exitTime"]) if "exitTime" in s else "", "exit": round(exit_px, 2), "exit_kind": kind,
            "r_gross": round(s["r"], 3), "usd_per_mnq": round(per, 2), "r_net": round(per / (s["risk"] * POINT_VALUE), 3),
            "mnq": mnq, "usd": round(mnq * per, 2)}


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def append(p: Path, cols: list[str], rows: list[dict]) -> None:
    new = not p.exists()
    with p.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        w.writerows(rows)


def main(risk_usd: float, source: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s_path, t_path = OUT / "sessions.csv", OUT / "trades.csv"
    done = {r["date"] for r in read_csv(s_path)}
    now = datetime.now(ET)
    vols = vxn_closes()
    results = {}  # source -> (sessions by date, signals by date, last bar end)
    loaders = {"databento": lambda: databento_bars(START - timedelta(days=WARMUP_DAYS)), "yahoo": yahoo_bars}
    for name in (["databento", "yahoo"] if source == "auto" else [source]):
        try:
            got = loaders[name]()
        except Exception as e:
            print(f"warning: {name} bars failed ({e})")
            continue
        if got is None:
            continue
        bars, rolls, last = got
        res = replay(bars, rolls, vols)
        sig = {}
        for s in res["signals"]:
            sig.setdefault(s["date"], []).append(s)
        results[name] = ({w["date"]: w for w in res["sessions"]}, sig, last)
        print(f"{name}: bars to {last:%Y-%m-%d %H:%M} ET, {len(res['sessions'])} sessions")
    logged_at = now.isoformat(timespec="seconds")
    s_rows, t_rows = [], []
    dates = sorted({d for sess, _, _ in results.values() for d in sess if d >= START.isoformat() and d not in done})
    for d in dates:
        pick = next((n for n in ("databento", "yahoo") if n in results and d in results[n][0]
                     and finished(d, results[n][2], now)), None)
        if pick is None:
            continue
        w, trades = results[pick][0][d], results[pick][1].get(d, [])
        if not w.get("skip") and "openedOutside" not in w:
            continue  # bars for that date but no RTH (CME holiday trading hours)
        rows = [trade_row(s, pick, risk_usd) for s in trades]
        status = (f"skip: {w['skip']}" if w.get("skip") else "opened outside" if w["openedOutside"]
                  else "traded" if rows else "no touch")
        rp = 0.4 * w["sigma"] if "sigma" in w else None
        s_rows.append({"date": d, "source": pick, "status": status, "pc": round(w.get("pc", float("nan")), 2),
                       "pc_date": w.get("pcDate", ""), "vol": round(w["vol"], 2) if "vol" in w else "", "vol_date": w.get("volDate", ""),
                       "sigma": round(w["sigma"], 2) if rp else "", "upper": round(w["upper"], 2) if rp else "",
                       "lower": round(w["lower"], 2) if rp else "", "risk_pts": round(rp, 2) if rp else "",
                       "mnq": int(risk_usd // (rp * POINT_VALUE)) if rp else "", "trades": len(rows),
                       "day_usd": round(sum(r["usd"] for r in rows), 2), "logged_at": logged_at})
        t_rows += rows
    append(s_path, SESSION_COLS, s_rows)
    append(t_path, TRADE_COLS, t_rows)
    for r in s_rows:
        line = f"{r['date']} [{r['source']}] {r['status']}"
        if r["sigma"] != "":
            line += f"  walls {r['lower']:.2f} / {r['upper']:.2f}  sigma {r['sigma']:.1f}"
        print(line)
    for r in t_rows:
        print(f"  {r['date']} {r['side']:5s} {r['entry_et'][11:]} @ {r['entry']:.2f} -> {r['exit_kind']} {r['exit']:.2f}  "
              f"{r['r_net']:+.2f}R net  {r['mnq']} MNQ ${r['usd']:+.0f}")
    summary(read_csv(t_path))


def summary(trades: list[dict]) -> None:
    if not trades:
        print("journal: no trades yet")
        return
    r = np.array([float(t["r_net"]) for t in trades])
    usd = sum(float(t["usd"]) for t in trades)
    print(f"journal since {trades[0]['date']}: {len(r)} trades, mean {r.mean():+.3f}R net "
          f"(backtest 2022-26: +0.115R), win {np.mean(r > 0):.0%}, total ${usd:+,.0f}")


def snap(px: float, up: bool) -> float:
    """Tick grid, as the backtest engine: entries away from the band, stops toward it, targets outward."""
    q = px / TICK
    return (math.ceil(q - 1e-9) if up else math.floor(q + 1e-9)) * TICK


def target_session(now: datetime) -> date:
    """Today if it is a trading day and RTH has not closed, else the next trading day."""
    d = now.date()
    if now.hour >= 16:
        d += timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in NYSE_CLOSED:
        d += timedelta(days=1)
    return d


def today(risk_usd: float) -> None:
    """Walls and orders for the current (or next) session from Yahoo bars, plus its status if RTH has started."""
    now = datetime.now(ET)
    key = target_session(now).isoformat()
    got = yahoo_bars()
    if got is None:
        raise SystemExit("no NQ=F bars from Yahoo")
    bars, _, last = got
    res = replay(bars, None, vxn_closes(), targets=[key])
    t = res["targets"][key]
    w = t["walls"]
    print(f"NQ IV-wall break for {key} (Yahoo bars to {last:%Y-%m-%d %H:%M} ET)")
    if w.get("skip"):
        print(f"  NO TRADE: {w['skip']}")
        return
    rp = 0.4 * w["sigma"]
    mnq = int(risk_usd // (rp * POINT_VALUE))
    print(f"  prior close {w['pc']:.2f} ({w['pcDate']})  VXN {w['vol']:.2f} ({w['volDate']})")
    print(f"  sigma {w['sigma']:.1f} = (implied {w['sigmaIv']:.1f} + 20d hist {w['sigmaHv']:.1f}) / 2")
    print(f"  walls: upper {w['upper']:.2f}   lower {w['lower']:.2f}")
    warn = []
    if w["volDate"] != w["pcDate"]:
        warn.append(f"VXN close is from {w['volDate']}, not the prior session {w['pcDate']}: Yahoo may not have posted "
                    "it yet. Rerun later, or check the Cboe VXN close and recompute.")
    if (date.fromisoformat(key) - date.fromisoformat(w["pcDate"])).days > 4:
        warn.append(f"prior close is from {w['pcDate']}: is Yahoo missing a session?")
    if key > max(NYSE_CLOSED):
        warn.append("NYSE_CLOSED in iv_wall_paper.py has no holidays this far out: extend it")
    o = t["orders"]
    lg = {"entry": snap(o["long"]["entry"], True), "stop": snap(o["long"]["stop"], False), "target": snap(o["long"]["target"], True)}
    sh = {"entry": snap(o["short"]["entry"], False), "stop": snap(o["short"]["stop"], True), "target": snap(o["short"]["target"], False)}
    risk_mnq = (lg["entry"] - lg["stop"]) * POINT_VALUE
    print(f"  BUY  STOP {lg['entry']:.2f}   stop loss {lg['stop']:.2f}   target {lg['target']:.2f}")
    print(f"  SELL STOP {sh['entry']:.2f}   stop loss {sh['stop']:.2f}   target {sh['target']:.2f}")
    print(f"  risk {rp:.1f} pts = ${risk_mnq:.0f} per MNQ (+ ~$1.50 costs)   size at ${risk_usd:.0f} budget: {mnq} MNQ"
          + ("   (0 = skip: stop too wide for the budget)" if mnq == 0 else ""))
    flat = "12:55" if t["halfDay"] else "15:55"
    print(f"  orders live 09:35-15:30 ET as an OCO pair, one trade per wall, flat at {flat} ET"
          + ("  (HALF DAY: RTH ends 13:00)" if t["halfDay"] else ""))
    print("  a wall touched before your order is live (09:30-09:35, or while in a trade) is dead for the day")
    # Status of a session already under way.
    sess = next((x for x in res["sessions"] if x["date"] == key), None)
    et = pd.to_datetime(bars.index, unit="s", utc=True).tz_convert(ET)
    m = et.hour * 60 + et.minute
    rth = bars[(et.strftime("%Y-%m-%d") == key) & (m >= 570) & (m < 960)]
    if len(rth) and sess is not None:
        rt = pd.to_datetime(rth.index, unit="s", utc=True).tz_convert(ET)
        print(f"  --- status at {rt[-1]:%H:%M} ET (last 5m bar start) ---")
        if sess.get("openedOutside"):
            print("  opened outside the walls: NO TRADES today")
        else:
            sigs = [x for x in res["signals"] if x["date"] == key]
            live = []
            for name, wall, hit in (("upper", "U", rth["high"] >= w["upper"]), ("lower", "L", rth["low"] <= w["lower"])):
                traded = any(x["wall"] == wall for x in sigs)
                if not hit.any():
                    print(f"  {name} wall: untouched")
                    live.append(name)
                else:
                    print(f"  {name} wall: touched at {rt[hit.to_numpy()][0]:%H:%M}, "
                          + ("traded (see below)" if traded else "no fill, DEAD for today"))
            holding = any(x["exitKind"] == "open" for x in sigs)
            last_min = int(m[-1]) if len(m) else 0
            if holding:
                print("  NOW: in a trade; keep its stop and target, flat at " + flat)
            elif not live or last_min >= 15 * 60 + 30 or et[-1].strftime("%Y-%m-%d") != key:
                print("  NOW: nothing to rest; done for the day")
            else:
                rest = [f"BUY STOP {lg['entry']:.2f}" if n == "upper" else f"SELL STOP {sh['entry']:.2f}" for n in live]
                print("  NOW: rest " + " + ".join(rest) + (" (OCO)" if len(rest) == 2 else ""))
            for sg in sigs:
                side = "long" if sg["side"] > 0 else "short"
                if sg["exitKind"] == "open":
                    print(f"  OPEN {side} from {et_str(sg['entryTime'])[11:]} @ {sg['entry']:.2f}: {sg['r']:+.2f}R at the last bar")
                else:
                    print(f"  {side} {et_str(sg['entryTime'])[11:]} @ {sg['entry']:.2f} -> {sg['exitKind']} "
                          f"{sg['exit']:.2f} ({sg['r']:+.2f}R gross)")
    for x in warn:
        print(f"  WARNING: {x}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--risk", type=float, default=500.0, help="$ risk budget per trade (MNQ = floor(risk / stop $))")
    ap.add_argument("--source", choices=["auto", "databento", "yahoo"], default="auto")
    ap.add_argument("--today", action="store_true", help="print the current/next session's walls and orders; log nothing")
    a = ap.parse_args()
    today(a.risk) if a.today else main(a.risk, a.source)
