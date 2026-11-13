"""Bar-by-bar backtest engine.

Timing (structural, not by review):
  * The strategy sees one closed 5m bar at a time (`on_bar(bar, pos)`), never a frame. It runs in a child
    process (ChildStrategy) fed through a pipe, so it holds nothing but what it was sent.
  * An action decided on bar k's close takes effect from bar k+1: market orders fill at the open of bar k+1's
    first 1m bar, stop moves apply from that bar, stop/limit entries can trigger on any 1m bar of their window.
  * Fills are simulated on the 1m bars inside each 5m bar. Within one 1m bar the stop wins when both the stop and
    the target are touched. Targets and limit entries need a tick traded through their price (no touch fills) and
    fill at their own price, never better (the queue at the limit empties before a gapped print). Limits must rest
    on the passive side of the decision close. Order prices snap to the equivalent price on the 0.25 tick grid.
  * A market entry whose open is already through its target exits there at the open (a marketable OCO limit).
  * On a 1m bar where an entry fills after the open (stop/limit entry) the stop is checked against that bar's
    whole range and the target is not checked (the intrabar order is unknown: assume the worst).
  * bar['es'] is the companion ES 5m bar of the same slot (same ET minutes, closed at the same time) or None;
    bar['es_prev_close'] is ES's own previous RTH close and bar['es_roll'] flags an ES contract change (ES rolls on
    different days from NQ; reset any ES history then). ES is information only; orders are NQ.
  * Every position is closed at the open of the session's last 5m bar (15:55, or 12:55 on half days); no order
    fills in that bar. Warmup sessions are shown to the strategy with bar['warmup'] = True and every action is
    ignored.

Actions (dict or None):
  {"op": "enter", "side": 1|-1, "type": "market"|"stop"|"limit", "price": px (stop/limit), "stop": px,
   "target": px|None, "ttl": n 5m bars for stop/limit (default 1)}
  {"op": "exit"}                 flatten at the next bar's open and cancel any pending entry
  {"op": "stop", "price": px}    move the stop (must be on the losing side of the decision close)
  {"op": "cancel"}               cancel a pending entry
"""
from __future__ import annotations

import importlib.util
import math
import multiprocessing as mp
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config as C
from .data import Session


class StrategyError(RuntimeError):
    pass


def check_bar(o: float, h: float, l: float, d: int, stop: float, target: float | None, allow_target: bool,
              tick: float = C.TICK, marketable: bool = False) -> tuple[str, float] | None:
    """Exit of an open position on one 1m bar, or None. `o` is the bar open, or the fill price on an entry bar.
    `marketable`: the target order goes in at this open (market entry bar), so an open through it fills at the open."""
    if d > 0:
        if o <= stop:
            return "stop", o
        if marketable and allow_target and target is not None and o >= target:
            return "target", o
        if l <= stop:
            return "stop", stop
        if allow_target and target is not None and h >= target + tick:
            return "target", target
    else:
        if o >= stop:
            return "stop", o
        if marketable and allow_target and target is not None and o <= target:
            return "target", o
        if h >= stop:
            return "stop", stop
        if allow_target and target is not None and l <= target - tick:
            return "target", target
    return None


def entry_fill(o: float, h: float, l: float, d: int, typ: str, px: float, tick: float = C.TICK) -> float | None:
    """Fill price of a resting stop/limit entry on one 1m bar, or None."""
    if typ == "stop":
        if d > 0 and h >= px:
            return max(o, px)
        if d < 0 and l <= px:
            return min(o, px)
    elif typ == "limit":  # must trade a tick through; fills at the limit, never better
        if d > 0 and l <= px - tick:
            return px
        if d < 0 and h >= px + tick:
            return px
    return None


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


def _bar_dict(s: Session, k: int, warmup: bool) -> dict:
    b = s.b5
    return {
        "day": s.day.isoformat(), "dow": s.day.weekday(), "slot": int(b["slot"][k]), "t": int(b["t"][k]),
        "mod": C.RTH_OPEN + int(b["slot"][k]) * C.BAR_MINUTES,
        "o": float(b["o"][k]), "h": float(b["h"][k]), "l": float(b["l"][k]), "c": float(b["c"][k]), "v": float(b["v"][k]),
        "first": k == 0, "flat_slot": s.flat_slot, "half_day": s.half, "close_mod": s.close_mod,
        "roll": s.roll, "prev_close": s.prev_close, "overnight": None if s.overnight is None else dict(s.overnight),
        "news": list(s.news), "news_day": s.news_day,
        "es": None if s.es5 is None or int(b["slot"][k]) not in s.es5 else dict(s.es5[int(b["slot"][k])]),
        "es_prev_close": s.es_prev_close, "es_roll": s.es_roll,
        "warmup": warmup,
    }


def snap(px: float, up: bool, tick: float = C.TICK) -> float:
    """Price on the tick grid: the tradeable price an off-grid order is equivalent to."""
    q = px / tick
    return (math.ceil(q - 1e-9) if up else math.floor(q + 1e-9)) * tick


def _num(x, what: str, act) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise StrategyError(f"{what} must be a finite number: {act}")
    return float(x)


def normalize(act, close: float, pos: dict | None) -> dict:
    """Validate an action decided on a bar that closed at `close`; return it with prices on the tick grid."""
    if not isinstance(act, dict):
        raise StrategyError(f"action must be a dict or None, got {type(act)}")
    op = act.get("op")
    if op in ("exit", "cancel"):
        return {"op": op}
    if op == "stop":
        if pos is None:
            raise StrategyError(f"stop move without a position: {act}")
        d = pos["side"]
        px = snap(_num(act.get("price"), "stop price", act), up=d < 0)
        if not d * (close - px) > 0:
            raise StrategyError(f"moved stop {px} is not on the losing side of {close}; use exit: {act}")
        return {"op": "stop", "price": px}
    if op != "enter":
        raise StrategyError(f"unknown op in {act}")
    d = act.get("side")
    if isinstance(d, bool) or d not in (1, -1):
        raise StrategyError(f"bad side in {act}")
    typ = act.get("type", "market")
    if typ not in ("market", "stop", "limit"):
        raise StrategyError(f"bad type in {act}")
    ttl = act.get("ttl", 1)
    if typ != "market" and (isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 1):
        raise StrategyError(f"ttl must be an int >= 1: {act}")
    if typ == "market":
        px = close
    elif typ == "stop":
        px = snap(_num(act.get("price"), "price", act), up=d > 0)
    else:
        px = snap(_num(act.get("price"), "price", act), up=d < 0)
        if not d * (close - px) > 0:
            raise StrategyError(f"limit {px} is marketable against close {close}; use a market order: {act}")
    st = snap(_num(act.get("stop"), "stop", act), up=d < 0)
    if not d * (px - st) > 0:
        raise StrategyError(f"stop on the wrong side of {px}: {act}")
    tg = act.get("target")
    if tg is not None:
        tg = snap(_num(tg, "target", act), up=d > 0)
        if not d * (tg - px) > 0:
            raise StrategyError(f"target on the wrong side of {px}: {act}")
    return {"op": "enter", "side": d, "type": typ, "price": None if typ == "market" else px, "stop": st,
            "target": tg, "ttl": int(ttl)}


def run(sessions_warm: list[Session], sessions: list[Session], strategy) -> dict:
    """Run a strategy (anything with on_bar(bar, pos)) over warmup then trade sessions. Returns trades + counters."""
    trades: list[dict] = []
    counters = {"rejected": 0, "replaced": 0, "bars": 0}
    for warm, group in ((True, sessions_warm), (False, sessions)):
        for si, s in enumerate(group):
            _run_session(s, si, strategy, warm, trades, counters)
    return {"trades": trades, **counters}


def _close(trades, s, si, p: Pos, j: int, kind: str, ref: float) -> None:
    trades.append({
        "day": s.day.isoformat(), "si": si, "side": p.side, "entry_kind": p.entry_kind, "entry_ref": p.entry_ref,
        "stop_init": p.stop_init, "target": p.target, "j_entry": p.j_entry, "at_open": p.at_open,
        "entry_mod": int(s.mod[p.j_entry]), "exit_kind": kind, "exit_ref": float(ref), "j_exit": j,
        "exit_mod": int(s.mod[j]), "risk_pts": max(abs(p.entry_ref - p.stop_init), C.TICK),
    })


def _run_session(s: Session, si: int, strategy, warm: bool, trades: list, counters: dict) -> None:
    b = s.b5
    nb = len(b["slot"])
    pos: Pos | None = None
    pend: dict | None = None
    act: dict | None = None
    for k in range(nb):
        a, z = int(b["a"][k]), int(b["b"][k])
        slot = int(b["slot"][k])
        if not warm:
            flat = slot >= s.flat_slot
            # 1) apply the action decided on the previous bar's close
            if flat:
                pend = None
                if pos is not None:
                    _close(trades, s, si, pos, a, "flat", s.o[a])
                    pos = None
                act = None
            elif act is not None:
                op = act.get("op")
                if op == "enter":
                    if pos is not None:
                        counters["rejected"] += 1
                    elif act.get("type", "market") == "market":
                        pos = Pos(act["side"], "market", float(s.o[a]), act["stop"], act["stop"],
                                  act["target"], a, True, k)
                        pend = None
                    else:
                        counters["replaced"] += pend is not None
                        pend = {**act, "left": act["ttl"]}
                elif op == "exit":
                    pend = None
                    if pos is not None:
                        _close(trades, s, si, pos, a, "market", s.o[a])
                        pos = None
                elif op == "stop":
                    if pos is not None:
                        pos.stop = act["price"]
                elif op == "cancel":
                    pend = None
                act = None
            # 2) walk the 1m bars of bar k
            if not flat:
                for j in range(a, z + 1):
                    o, h, l = s.o[j], s.h[j], s.l[j]
                    if pos is None and pend is not None:
                        f = entry_fill(o, h, l, pend["side"], pend["type"], float(pend["price"]))
                        if f is None:
                            continue
                        pos = Pos(pend["side"], pend["type"], float(f), pend["stop"], pend["stop"],
                                  pend["target"], j, pend["type"] == "stop" and f == o, k)
                        pend = None
                        r = check_bar(f, h, l, pos.side, pos.stop, pos.target, allow_target=pos.at_open)
                    elif pos is not None:
                        first = j == pos.j_entry
                        r = check_bar(o, h, l, pos.side, pos.stop, pos.target, allow_target=(not first) or pos.at_open,
                                      marketable=first and pos.entry_kind == "market")
                    else:
                        continue
                    if r is not None:
                        _close(trades, s, si, pos, j, *r)
                        pos = None
                if pend is not None:
                    pend["left"] -= 1
                    if pend["left"] <= 0:
                        pend = None
        # 3) bar k is closed: ask the strategy
        bar = _bar_dict(s, k, warm)
        pd_ = None if pos is None else {"side": pos.side, "entry_px": pos.entry_ref, "stop": pos.stop,
                                        "target": pos.target, "bars_held": k - pos.k_entry}
        counters["bars"] += 1
        out = strategy.on_bar(bar, pd_)
        if warm or out is None:
            continue
        out = normalize(out, float(b["c"][k]), pd_)
        if k + 1 < nb and int(b["slot"][k + 1]) < s.flat_slot:
            act = out
        elif out.get("op") == "exit":
            act = None  # the flat at the last bar closes it anyway
    if pos is not None and not warm:  # no bar at/after the flat slot (data gap): close at the last close
        _close(trades, s, si, pos, len(s.c) - 1, "flat", s.c[-1])


# --- Strategy loading --------------------------------------------------------------------------------------------

def load_strategy_class(path: Path):
    from .sandbox import check_source
    src = Path(path).read_text()
    check_source(src, str(path))
    spec = importlib.util.spec_from_file_location(f"strategy_{Path(path).stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Strategy


def _child(conn, path: str, params: dict) -> None:
    os.chdir(tempfile.mkdtemp(prefix="strategy_"))  # nothing readable by relative path
    try:
        strat = load_strategy_class(Path(path))(params)
    except Exception as e:  # noqa: BLE001
        conn.send(("err", f"load: {e!r}"))
        return
    conn.send(("ok", None))
    while True:
        msg = conn.recv()
        if msg is None:
            return
        try:
            conn.send(("ok", strat.on_bar(*msg)))
        except Exception as e:  # noqa: BLE001
            conn.send(("err", repr(e)))
            return


class ChildStrategy:
    """Runs strategies/<id>.py in a spawned process and forwards on_bar calls through a pipe."""

    def __init__(self, path: Path, params: dict):
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_child, args=(child, str(path), params), daemon=True)
        self.proc.start()
        ok, err = self._recv()
        if ok != "ok":
            self.close()
            raise StrategyError(err)

    def _recv(self, timeout: float = 60.0):
        """Wait for the child's reply; fail instead of hanging if it died or stalls."""
        waited = 0.0
        while not self.conn.poll(0.5):
            waited += 0.5
            if not self.proc.is_alive():
                raise StrategyError(f"strategy process exited (code {self.proc.exitcode})")
            if waited >= timeout:
                self.proc.kill()
                raise StrategyError(f"strategy did not answer within {timeout:.0f}s")
        return self.conn.recv()

    def on_bar(self, bar, pos):
        self.conn.send((bar, pos))
        ok, out = self._recv()
        if ok != "ok":
            raise StrategyError(out)
        return out

    def close(self):
        try:
            self.conn.send(None)
        except Exception:  # noqa: BLE001
            pass
        self.proc.join(timeout=5)
        if self.proc.is_alive():
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
