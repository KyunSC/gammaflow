"""Crypto perp research-loop controller: runs pre-registered candidates through the frozen evaluator, keeps the ledger.

    cd functions/ml && ../../.venv/bin/python -B research_loop_free/crypto/controller.py run <id> --block train|validation
    ../../.venv/bin/python -B research_loop_free/crypto/controller.py sanity [--seeds 3] [--ev]
    ../../.venv/bin/python -B research_loop_free/crypto/controller.py status

Not frozen (only eval/ is). Its tests are research_loop_crypto/test_controller.py, outside tests/ because the manifest
pins tests/*.py.

Every run first verifies eval/MANIFEST.sha256 against the digest pinned in state.json (freeze.digest) and refuses on any
mismatch. A strategy is strategies/<id>.py defining `signals(m, feats, params) -> list[Signal]` (and optionally
WARMUP_DAYS); it sees a Market that includes the warmup and a Features object for the same window. Signals decided
before the block start are dropped; the rest are executed on a Market that starts at the block start, so the EV book
has no warmup days.

One ledger row per (candidate, config, block), appended (fsync'd) only once every symbol of that config is done, so a
killed run leaves no row and a rerun resumes without duplicates. Refusals:
  * the test block (never inside the loop), no prereg/<id>.json or strategy, a grid of more than 3 configurations;
  * a strategy or prereg that changed after its first train row (a refinement needs a new id);
  * forbidden tokens in the strategy source (block internals, file or network access);
  * the train budget of TRAIN_CONFIG_LIMIT configurations across the loop;
  * a family that research_loop/data_spend_ledger.json marks as spent (one_look) on crypto over the block's dates;
  * validation for a config that did not pass train (except K0 = C4 with state.json c4_approval == "YES"), a config
    that already has a validation row, or a 6th validation look (blocks.open_block counts looks.jsonl).

Gate per asset (plan, Decisions): train >= 200 trades, side-matched twin p < 0.005, mean net R > 0 with session (UTC
entry day) block-bootstrap CI low > 0, stress R > 0 (every trade's costs doubled), no year > 40% of net R, net R > 0
without the top 5 trades, median stop >= 1.5% of entry price, and Elite 50K EV above the twins' mean EV. Validation:
>= 100 trades, twin p < 0.05 / K (K = candidates with a train pass, this one included), net R > 0, EV above twins.
A config passes when BTC and ETH both pass; SOL is reported only (train from 2022-05-01, after its gappy months).
On train every config also gets a truncation-invariance check: signals decided before each of 4 fixed cuts must be
identical when the data stops at that cut (review finding: no strategy may read bars or features after its decision).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(HERE.parents[1]) not in sys.path:
    sys.path.append(str(HERE.parents[1]))   # functions/ml, for research_loop_free.shared

from eval import config as C  # noqa: E402
from eval import engine as E  # noqa: E402
from eval import manifest as M  # noqa: E402
from eval.blocks import Block, HoldoutError, looks, open_block  # noqa: E402
from eval.features import Features  # noqa: E402
from eval.stats import block_idx  # noqa: E402

LEDGER = HERE / 'ledger.jsonl'
PREREG = HERE / 'prereg'
STRATS = HERE / 'strategies'
STATE = C.STATE / 'state.json'
RUNS = C.STATE / 'runs'
SPEND = C.ML / 'research_loop' / 'data_spend_ledger.json'
LOOP_NAME = 'research_loop_free/crypto'

MAX_GRID = 3
TRAIN_CONFIG_LIMIT = 10
GATE_SYMBOLS = ('BTCUSDT', 'ETHUSDT')
REPORT_SYMBOLS = ('SOLUSDT',)
SOL_TRAIN_START = pd.Timestamp('2022-05-01', tz='UTC')   # after SOL's gappy 2022-02 / 2022-04 months
# Truncation cuts inside train at odd times of day and week (a peek is caught when a signal sits within its horizon).
TRUNC_CUTS = tuple(pd.Timestamp(x, tz='UTC') for x in ('2021-03-17 13:47', '2022-04-02 00:00', '2022-11-09 18:21',
                                                         '2023-08-15 07:13'))
EV_TWINS = 200
MIN_MEDIAN_STOP_PCT = 1.5
CRYPTO_MARKETS = ('BTC', 'ETH', 'SOL', 'crypto')
CRITERIA = {
    'train': dict(min_trades=200, p_max=0.005, ci_low_positive=True, stress_positive=True, max_year_share=0.40,
                  positive_without_top=5),
    'validation': dict(min_trades=100, p_max=0.05),   # divided by K
}
FORBIDDEN = re.compile(r'\b(open_block|_OPEN|Block\s*\(|looks\.jsonl|read_parquet|read_csv|open\s*\(|urllib|requests|'
                       r'subprocess|socket|os\.|shutil|importlib|__import__|exec\s*\(|eval\s*\(|TEST_START|_read\s*\()')


class Refused(RuntimeError):
    pass


# ---------------------------------------------------------------- ledger and bookkeeping

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ledger_rows(path: Path | None = None) -> list[dict]:
    path = path or LEDGER
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def append_row(row: dict, path: Path | None = None) -> None:
    line = json.dumps(row, sort_keys=True, default=float) + '\n'
    with open(path or LEDGER, 'a') as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


_append_local = append_row


def append_row(row: dict, path: Path | None = None) -> None:
    """Local ledger (budget) first, then the shared research_loop/ledger.jsonl mirror (plan rule 3)."""
    _append_local(row, path)
    if path is None:
        from research_loop_free.shared import mirror_run
        mirror_run(row, LOOP_NAME)


def verify_eval() -> str:
    pinned = json.loads(STATE.read_text()).get('freeze', {}).get('digest')
    if not pinned:
        raise Refused('no pinned evaluator digest in state.json (freeze.digest)')
    try:
        return M.verify(expect_digest=pinned)
    except M.HashMismatch as e:
        raise Refused(f'evaluator hash mismatch: {e}') from e


def configs(grid: dict) -> list[dict]:
    base, axes = grid.get('base', {}), grid.get('axes', {})
    names = sorted(axes)
    if not names:
        return [dict(base)]
    return [{**base, **dict(zip(names, vals))} for vals in itertools.product(*(axes[n] for n in names))]


def run_key(cid: str, k: int, block: str, digest: str, strat_sha: str, prereg_sha: str) -> str:
    return hashlib.sha256(f'{cid}|{k}|{block}|{digest}|{strat_sha}|{prereg_sha}'.encode()).hexdigest()[:24]


def check_source(src: str, name: str) -> None:
    hit = FORBIDDEN.search(src)
    if hit:
        raise Refused(f'{name}: forbidden token {hit.group(0)!r} (strategies get bars and features from the controller)')


def spent_conflicts(families: list[str], block: str, spend: Path = SPEND) -> list[str]:
    lo, hi = (date.fromisoformat(x) for x in C.BLOCKS[block])
    out = []
    for r in json.loads(spend.read_text())['rows']:
        mk = r['market'] if isinstance(r['market'], list) else [r['market']]
        if r['kind'] != 'one_look' or not set(mk) & set(CRYPTO_MARKETS):
            continue
        both = set(r['families']) & set(families)
        if both and date.fromisoformat(r['start']) < hi and date.fromisoformat(r['end']) >= lo:
            out.append(f"{r['study']} ({r['start']}..{r['end']}, {sorted(both)})")
    return out


def load_strategy(path: Path):
    check_source(path.read_text(), path.name)
    spec = importlib.util.spec_from_file_location(f'cpl_strategy_{path.stem}', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, 'signals', None)):
        raise Refused(f'{path.name} defines no signals(m, feats, params)')
    return mod


# ---------------------------------------------------------------- data windows

def first_month(sym: str) -> pd.Timestamp:
    ms = sorted(p.name[:7] for p in (C.BINANCE / 'klines-1m' / sym).glob('*.parquet') if 'gappy' not in p.name)
    return pd.Timestamp(ms[0] + '-01', tz='UTC')


def symbol_block(blk: Block, sym: str) -> Block:
    """SOL's train window starts after its gappy months (a train-only Block may be built directly)."""
    if sym == 'SOLUSDT' and blk.name == 'train' and blk.start < SOL_TRAIN_START:
        return Block('train', SOL_TRAIN_START, blk.end, blk.root)
    return blk


def data_floor(sym: str) -> pd.Timestamp:
    """Earliest date a loader may reach for `sym`, warmup included (SOL: after its gappy 2022-02 / 2022-04 months)."""
    f = first_month(sym)
    return max(f, SOL_TRAIN_START) if sym == 'SOLUSDT' else f


def load_market(blk: Block, sym: str, warmup_days: int) -> tuple[E.Market, Features, int]:
    """Market and Features including the warmup (clamped to data_floor), plus the warmup bar count."""
    w = int(max(0, min(warmup_days, (blk.start - data_floor(sym)).days)))
    m = E.Market(sym, blk.bars(sym, w), blk.funding(sym, w))
    off = int(np.searchsorted(m.t, int(blk.start.timestamp())))
    return m, Features(blk, w), off


def exec_view(m_full: E.Market, off: int, sigs: list[E.Signal]) -> tuple[E.Market, list[E.Signal]]:
    """Execution market without the warmup bars; signals decided before the block start are dropped."""
    if off == 0:
        return m_full, list(sigs)
    m = E.Market(m_full.symbol, m_full.bars.iloc[off:].reset_index(drop=True), m_full.funding)
    out = [E.Signal(s.sig - off, s.side, s.stop, s.target, s.end - off, s.trail) for s in sigs if s.sig >= off]
    return m, out


def truncation_check(mod, params: dict, sym: str, blk: Block, warmup: int, m_full: E.Market,
                     sigs_full: list[E.Signal], cuts=None) -> dict:
    """Signals decided before each cut must not change when the data stops at that cut."""
    cuts = [c for c in (TRUNC_CUTS if cuts is None else cuts) if blk.start < c < blk.end]
    if not cuts:
        return dict(checked=False)

    def key(m, s):
        return (int(m.t[s.sig]), int(s.side), round(float(s.stop), 9),
                None if s.target is None else round(float(s.target), 9), s.trail)
    before, diffs = 0, []
    for c in cuts:
        m2, f2, _ = load_market(Block('train', blk.start, c, blk.root), sym, warmup)
        cut = int(c.timestamp())
        a = {key(m_full, s) for s in sigs_full if m_full.t[s.sig] + 60 <= cut}
        b = {key(m2, s) for s in mod.signals(m2, f2, params) if m2.t[s.sig] + 60 <= cut}
        before += len(a)
        diffs += [(c.isoformat(),) + d for d in sorted(a ^ b)]
    return dict(checked=True, cuts=len(cuts), before_cut=before, mismatches=len(diffs), ok=not diffs,
                first=[list(map(str, d)) for d in diffs[:3]])


# ---------------------------------------------------------------- metrics and gate

def session_ci(day: np.ndarray, r: np.ndarray, seed: int = C.SEED) -> list[float]:
    """Mean net R per trade, block bootstrap over UTC entry days (blocks of R_BOOT_BLOCK days)."""
    u, inv = np.unique(day, return_inverse=True)
    s, c = np.bincount(inv, r), np.bincount(inv)
    idx = block_idx(len(u), C.R_BOOT, min(C.R_BOOT_BLOCK, len(u)), np.random.default_rng(seed))
    b = s[idx].sum(1) / c[idx].sum(1)
    return [float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))]


def measure(m: E.Market, trades: list[E.Trade], *, ev: bool, workers: int = C.MAX_WORKERS) -> dict:
    d = E.describe(m, trades)
    if not trades:
        return dict(book=d, trades=0)
    rl, rs, dirs = E.mirrors(trades)
    legs = [t.legs[int(x)] for t, x in zip(trades, dirs)]
    r = E.taken(rl, rs, dirs)
    cost_r = np.array([lg.costs for lg in legs]) / E.RISK_USD
    stress = r - cost_r                                   # every trade's costs doubled
    entry_t = m.t[[t.entry for t in trades]]
    day = entry_t // 86400
    yr = pd.to_datetime(entry_t, unit='s', utc=True).year.to_numpy()
    years = {int(y): float(r[yr == y].sum()) for y in np.unique(yr)}
    total = float(r.sum())
    stop_pct = np.array([t.sig.stop / m.o[t.entry] * 100 for t in trades])
    out = dict(book=d, trades=len(trades), twins=E.r_test(rl, rs, dirs), mean_r=float(r.mean()),
               ci_session=session_ci(day, r), gross_r=float((r + cost_r).mean()),
               gross_ci_session=session_ci(day, r + cost_r), mean_r_stress=float(stress.mean()),
               year_sum_r=years, max_year_share=float(max(years.values()) / total) if total > 0 else float('inf'),
               mean_r_without_top5=float(np.sort(r)[:-5].mean()) if len(r) > 5 else float('nan'),
               median_stop_pct=float(np.median(stop_pct)), unholed_trades=int(sum(not t.holed for t in trades)),
               by_year=E.by_year(m, trades, dirs))
    if ev:
        out['ev'] = E.ev_test(E.build_book(m, trades), dirs, EV_TWINS, C.EV_PATHS, workers)
    return out


def gate(x: dict, block: str, k_candidates: int = 1) -> list[str]:
    """Failed criteria for one asset (empty = pass)."""
    c = CRITERIA[block]
    if not x.get('trades'):
        return ['no trades']
    fails = []
    if x['trades'] < c['min_trades']:
        fails.append(f"trades {x['trades']} < {c['min_trades']}")
    p_max = c['p_max'] / (max(1, k_candidates) if block == 'validation' else 1)
    if not x['twins']['p'] < p_max:
        fails.append(f"twin p {x['twins']['p']:.4f} >= {p_max:.4f}")
    if not x['mean_r'] > 0:
        fails.append(f"net R {x['mean_r']:+.4f} <= 0")
    if 'ev' in x and not x['ev']['strategy']['ev'] > x['ev']['twin_ev_mean']:
        fails.append(f"EV {x['ev']['strategy']['ev']:.0f} <= twins {x['ev']['twin_ev_mean']:.0f}")
    if 'ev' not in x:
        fails.append('EV not computed')
    if block == 'train':
        if not x['ci_session'][0] > 0:
            fails.append(f"session CI low {x['ci_session'][0]:+.4f} <= 0")
        if not x['mean_r_stress'] > 0:
            fails.append(f"stress R {x['mean_r_stress']:+.4f} <= 0")
        if not x['max_year_share'] <= c['max_year_share']:
            fails.append(f"max year share {x['max_year_share']:.2f} > {c['max_year_share']}")
        if not x['mean_r_without_top5'] > 0:
            fails.append(f"R without top 5 {x['mean_r_without_top5']:+.4f} <= 0")
        if not x['median_stop_pct'] >= MIN_MEDIAN_STOP_PCT:
            fails.append(f"median stop {x['median_stop_pct']:.2f}% < {MIN_MEDIAN_STOP_PCT}%")
        if x.get('truncation', {}).get('checked') and not x['truncation']['ok']:
            fails.append(f"truncation-invariance: {x['truncation']['mismatches']} signals change at the cut")
    return fails


# ---------------------------------------------------------------- run

def _load_candidate(cid: str) -> tuple[dict, Path, str, str]:
    pre = PREREG / f'{cid}.json'
    if not pre.exists():
        raise Refused(f'no pre-registration prereg/{cid}.json')
    spec = json.loads(pre.read_text())
    path = STRATS / f'{cid}.py'
    if not path.exists():
        raise Refused(f'no strategy file strategies/{cid}.py')
    check_source(path.read_text(), path.name)
    return spec, path, sha(path), sha(pre)


def plan_run(cid: str, block: str, spec: dict, s_sha: str, p_sha: str, rows: list[dict], state: dict,
             n_val_looks: int) -> tuple[list[int], int]:
    """Which configs to run and K (validation). Raises Refused on any rule; pure, so it is unit-tested."""
    if block == 'test':
        raise Refused('the crypto perp loop never opens the test block')
    if block not in C.BLOCKS:
        raise Refused(f'unknown block {block!r}')
    cfgs = configs(spec['grid'])
    if len(cfgs) > MAX_GRID:
        raise Refused(f'grid has {len(cfgs)} configurations (max {MAX_GRID})')
    cand = [r for r in rows if r.get('kind') == 'candidate' and r['status'] == 'ok']
    mine = [r for r in cand if r['id'] == cid]
    first_train = [r for r in mine if r['block'] == 'train']
    if first_train and (first_train[0]['strategy_sha256'] != s_sha or first_train[0]['prereg_sha256'] != p_sha):
        raise Refused(f'{cid}: strategy or prereg changed after its train run; a refinement needs a new id')
    if block == 'train':
        if spec.get('k0'):
            raise Refused('K0 (C4) is never re-run on train')
        done = {r['k'] for r in first_train}
        todo = [k for k in range(len(cfgs)) if k not in done]
        used = len({(r['id'], r['k']) for r in cand if r['block'] == 'train'})
        if used + len(todo) > TRAIN_CONFIG_LIMIT:
            raise Refused(f'budget: {used} train configurations used, {len(todo)} more would exceed {TRAIN_CONFIG_LIMIT}')
        return todo, 1
    if n_val_looks >= C.MAX_VALIDATION_LOOKS:
        raise Refused(f'validation already opened {n_val_looks} times (limit {C.MAX_VALIDATION_LOOKS})')
    if spec.get('k0'):
        if state.get('c4_approval') != 'YES':
            raise Refused('K0 needs c4_approval == "YES" in state.json (plan: C4 approval line)')
        passed = set(range(len(cfgs)))
    else:
        passed = {r['k'] for r in first_train if r['pass']}
    override = state.get('validation_overrides', {}).get(cid)
    if not passed and override:
        # The user may send a train-failed candidate to validation. It must be explicit, name its configs, and
        # set its own K; the ledger row records that the train gate was overridden.
        if override.get('approved_by') != 'user' or override.get('train_failed_ack') is not True:
            raise Refused(f'{cid}: validation override needs approved_by "user" and train_failed_ack true')
        if len(first_train) != len(cfgs):
            raise Refused(f'{cid}: override needs every configuration run on train first')
        passed = {int(k) for k in override['configs']} & set(range(len(cfgs)))
    if not passed:
        raise Refused(f'{cid}: no configuration passed train; validation not allowed')
    seen = {r['k'] for r in mine if r['block'] == 'validation'}
    todo = sorted(passed - seen)
    if not todo:
        raise Refused(f'{cid}: every train-passing configuration already has its validation row')
    sent = {r['id'] for r in cand if r['block'] == 'train' and r['pass']} | {cid}
    sent |= {r['id'] for r in cand if r['block'] == 'validation'}
    if override and not {r['k'] for r in first_train if r['pass']}:
        return todo, max(len(sent), int(override.get('K', 1)))
    return todo, len(sent)


def cmd_run(cid: str, block: str, workers: int = C.MAX_WORKERS) -> int:
    if block == 'test':
        raise Refused('the crypto perp loop never opens the test block')
    digest = verify_eval()
    spec, path, s_sha, p_sha = _load_candidate(cid)
    state = json.loads(STATE.read_text())
    n_val = sum(1 for x in looks() if x['block'] == 'validation')
    conflicts = spent_conflicts(spec.get('family', []), block)
    if conflicts:
        raise Refused(f'{cid}: family already spent on {block}: ' + '; '.join(conflicts))
    rows = ledger_rows()
    todo, K = plan_run(cid, block, spec, s_sha, p_sha, rows, state, n_val)
    cfgs = configs(spec['grid'])
    mod = load_strategy(path)
    warm = int(spec.get('warmup_days', getattr(mod, 'WARMUP_DAYS', 0)))
    done_keys = {r['run_key'] for r in rows if r.get('kind') == 'candidate'}
    todo = [k for k in todo if run_key(cid, k, block, digest, s_sha, p_sha) not in done_keys]
    if not todo:
        print(f'{cid} {block}: every configuration already recorded')
        return 0
    overridden = block == 'validation' and cid in state.get('validation_overrides', {}) and \
        not any(r['pass'] for r in rows if r.get('kind') == 'candidate' and r['id'] == cid and r['block'] == 'train')
    purpose = f'crypto perp loop: {cid} {block}, configs {todo}' + (f', K={K}' if block == 'validation' else '') + \
        (' (USER OVERRIDE: train gate failed)' if overridden else '')
    results = {k: {} for k in todo}
    t0 = time.time()
    with open_block(block, purpose=purpose, spec_hashes=[p_sha[:16]]) as blk:
        for sym in GATE_SYMBOLS + REPORT_SYMBOLS:
            sb = symbol_block(blk, sym)
            m_full, feats, off = load_market(sb, sym, warm)
            for k in todo:
                sigs = mod.signals(m_full, feats, cfgs[k])
                m, ex = exec_view(m_full, off, sigs)
                trades = E.run_book(m, ex)
                x = measure(m, trades, ev=sym in GATE_SYMBOLS, workers=workers)
                x['window'] = [E.iso(m.t[0]), E.iso(m.t[-1])]
                if block == 'train' and sym in GATE_SYMBOLS:
                    x['truncation'] = truncation_check(mod, cfgs[k], sym, sb, warm, m_full, sigs)
                x['fails'] = gate(x, block, K)
                results[k][sym] = x
                out = RUNS / cid / f'{block}_{k}_{sym}.json'
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(dict(metrics=x, trades=[dict(entry=E.iso(m.t[t.entry]), exit=E.iso(m.t[t.exit]),
                                                                        side=int(t.sig.side), stop=float(t.sig.stop),
                                                                        r=float(t.legs[int(t.sig.side)].r), holed=t.holed)
                                                                   for t in trades]), default=float))
                tw = x.get('twins', {})
                print(f"{cid}[{k}] {block} {sym}: n={x['trades']} R={x.get('mean_r', float('nan')):+.4f} "
                      f"p={tw.get('p', float('nan')):.4f} -> {'ok' if not x['fails'] else 'fail: ' + '; '.join(x['fails'])}"[:400],
                      flush=True)
    for k in todo:
        ok = all(not results[k][s]['fails'] for s in GATE_SYMBOLS)
        append_row(dict(kind='candidate', id=cid, k=k, block=block, params=cfgs[k], status='ok', **{'pass': ok},
                        run_key=run_key(cid, k, block, digest, s_sha, p_sha), eval_digest=digest, strategy_sha256=s_sha,
                        prereg_sha256=p_sha, family=spec.get('family', []), K=K, warmup_days=warm,
                        train_gate_override=overridden,
                        seconds=round(time.time() - t0, 1), ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                        symbols={s: {kk: v for kk, v in results[k][s].items() if kk != 'by_year'} for s in results[k]}))
        print(f"{cid}[{k}] {block} {json.dumps(cfgs[k])}: {'PASS' if ok else 'FAIL'}")
    return 0


# ---------------------------------------------------------------- sanity

SANITY = {
    '_sanity_flat': '"""Sanity only: never trades."""\n\n\ndef signals(m, feats, params):\n    return []\n',
    '_sanity_random': '''"""Sanity only: one random-side market entry per UTC day at a random minute, stop = target = stop_pct of price,
held at most 24h. Accounting check: mean net R ~ -cost, gross R ~ 0."""
import numpy as np

from eval.engine import Signal, end_by_time, run_starts


def signals(m, feats, params):
    rng = np.random.default_rng(params["seed"])
    out = []
    first = run_starts(m.t // 86400)
    for a, b in zip(first, np.r_[first[1:], m.n]):
        s = a + int(rng.integers(0, max(1, b - a - 1)))
        side = 1 if rng.random() < 0.5 else -1
        if s + 1 >= m.n:
            continue
        d = params["stop_pct"] / 100 * m.c[s]
        out.append(Signal(s, side, d, d, end_by_time(m, s, 86400)))
    return out
''',
}


def cmd_sanity(seeds: int, ev: bool, workers: int = C.MAX_WORKERS) -> int:
    """Always-flat and random-direction runs on train: accounting checks, not candidates (kind=sanity, no budget)."""
    digest = verify_eval()
    for name, src in SANITY.items():
        p = STRATS / f'{name}.py'
        if not p.exists() or p.read_text() != src:
            p.write_text(src)
    done = {r['run_key'] for r in ledger_rows() if r.get('kind') == 'sanity'}
    cfgs = [('_sanity_flat', {})] + [('_sanity_random', {'seed': s, 'stop_pct': 2.0}) for s in range(seeds)]
    todo = [(n, p) for n, p in cfgs if run_key(n, p.get('seed', -1), 'train', digest, sha(STRATS / f'{n}.py'), 'sanity') not in done]
    if not todo:
        print('sanity: every run already recorded')
        return 0
    with open_block('train', purpose=f'free-data loop (research_loop_free/crypto): controller sanity (flat + random), {len(todo)} runs; not research') as blk:
        markets = {s: load_market(symbol_block(blk, s), s, 0) for s in GATE_SYMBOLS}
        for name, params in todo:
            p = STRATS / f'{name}.py'
            mod = load_strategy(p)
            per = {}
            t0 = time.time()
            for sym, (m_full, feats, off) in markets.items():
                m, ex = exec_view(m_full, off, mod.signals(m_full, feats, params))
                x = measure(m, E.run_book(m, ex), ev=ev and name != '_sanity_flat', workers=workers)
                x.pop('by_year', None)
                per[sym] = x
                if x['trades']:
                    print(f"{name} {params} {sym}: n={x['trades']} R={x['mean_r']:+.4f} CI{np.round(x['ci_session'], 4).tolist()} "
                          f"gross={x['gross_r']:+.4f} CI{np.round(x['gross_ci_session'], 4).tolist()} "
                          f"cost={x['book']['cost_r']:.4f} p={x['twins']['p']:.3f} stop%={x['median_stop_pct']:.2f}"
                          + (f" EV={x['ev']['strategy']['ev']:.0f} twins={x['ev']['twin_ev_mean']:.0f}" if 'ev' in x else ''), flush=True)
                else:
                    print(f'{name} {sym}: n=0 trades', flush=True)
            append_row(dict(kind='sanity', id=name, params=params, block='train', status='ok', eval_digest=digest,
                            run_key=run_key(name, params.get('seed', -1), 'train', digest, sha(p), 'sanity'),
                            seconds=round(time.time() - t0, 1), ts=time.strftime('%Y-%m-%dT%H:%M:%S%z'), symbols=per))
    return 0


def cmd_status() -> int:
    rows = ledger_rows()
    cand = [r for r in rows if r.get('kind') == 'candidate']
    used = len({(r['id'], r['k']) for r in cand if r['block'] == 'train'})
    n_val = sum(1 for x in looks() if x['block'] == 'validation')
    print(f'train configurations {used}/{TRAIN_CONFIG_LIMIT}; validation looks {n_val}/{C.MAX_VALIDATION_LOOKS} '
          f'(shared looks.jsonl); ledger rows {len(rows)} ({len(cand)} candidate)')
    for r in cand[-10:]:
        print(f"  {r['id']}[{r['k']}] {r['block']} {r['status']} pass={r.get('pass')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('id')
    r.add_argument('--block', required=True)
    s = sub.add_parser('sanity')
    s.add_argument('--seeds', type=int, default=3)
    s.add_argument('--ev', action='store_true')
    sub.add_parser('status')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'run':
            return cmd_run(a.id, a.block)
        if a.cmd == 'sanity':
            return cmd_sanity(a.seeds, a.ev)
        return cmd_status()
    except (Refused, HoldoutError) as e:
        print(f'REFUSED: {e}')
        return 3


if __name__ == '__main__':
    sys.exit(main())
