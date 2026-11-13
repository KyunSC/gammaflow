"""Fetch the free crypto derivatives data for the crypto perp research loop.

One source per run: `python -B research_loop_crypto/fetch_free.py metrics|klines`
(klines = premiumIndexKlines, markPriceKlines and indexPriceKlines, monthly 1m).

Files land in data/research_loop_crypto/raw/<source>/. Every download is logged
(url, bytes, sha256, rows) to raw/<source>/fetch_log.jsonl, and a coverage report
(first dates, missing days, 5m holes, duplicates) goes to coverage.json/.md.

Block guard: files dated on or after TEST_START are downloaded and hashed, but
only their row count is read. Their values never reach this process.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / 'data' / 'research_loop_crypto' / 'raw'
TEST_START = dt.date(2025, 7, 8)
FORWARD_START = dt.date(2026, 10, 1)  # reserved for the MFP sandbox; never fetched
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
S3_LIST = 'https://s3-ap-northeast-1.amazonaws.com/data.binance.vision'
DATA = 'https://data.binance.vision/'
UA = {'User-Agent': 'research-loop-fetch/1.0'}
WORKERS = 8


class BlockGuardError(RuntimeError):
    pass


def _get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * 2 ** i)
    raise AssertionError


def list_keys(prefix: str) -> list[str]:
    """All object keys under a data.binance.vision prefix (S3 listing, paginated)."""
    keys, marker = [], ''
    ns = {'s': 'http://s3.amazonaws.com/doc/2006-03-01/'}
    while True:
        url = f'{S3_LIST}?delimiter=/&prefix={prefix}' + (f'&marker={marker}' if marker else '')
        root = ET.fromstring(_get(url))
        keys += [c.find('s:Key', ns).text for c in root.findall('s:Contents', ns)]
        if root.find('s:IsTruncated', ns).text != 'true':
            return keys
        marker = root.find('s:NextMarker', ns).text


def key_date(key: str) -> dt.date:
    return dt.date.fromisoformat(key.rsplit('-metrics-', 1)[1][:10])


def csv_text(zbytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        (name,) = z.namelist()
        return z.read(name).decode()


def count_rows(zbytes: bytes) -> int:
    """Data rows (header excluded) without parsing any value."""
    text = csv_text(zbytes)
    n = text.count('\n') + (0 if text.endswith('\n') or not text else 1)
    return n - 1 if text.startswith('create_time') else n


def read_metrics(zbytes: bytes, day: dt.date) -> list[dict]:
    """Parsed rows of one metrics day. Refuses any day in the test block or later."""
    if day >= TEST_START:
        raise BlockGuardError(f'{day} is on or after test start {TEST_START}')
    rows = list(csv.DictReader(io.StringIO(csv_text(zbytes))))
    for r in rows:
        if r['create_time'][:10] >= TEST_START.isoformat():
            raise BlockGuardError(f'row {r["create_time"]} is on or after test start')
    return rows


VALUE_COLS = ('sum_open_interest', 'sum_open_interest_value', 'count_toptrader_long_short_ratio',
              'sum_toptrader_long_short_ratio', 'count_long_short_ratio', 'sum_taker_long_short_vol_ratio')


def day_coverage(rows: list[dict], day: dt.date) -> dict:
    """Per-day quality: unique 5m slots, duplicates (identical / conflicting), off-grid stamps, empty/zero values."""
    by_ts = defaultdict(list)
    off_grid = 0
    for r in rows:
        t = dt.datetime.fromisoformat(r['create_time'])
        if t.date() != day or t.second or t.minute % 5:
            off_grid += 1
        by_ts[t].append(tuple(r[c] for c in VALUE_COLS))
    conflicting = sum(1 for v in by_ts.values() if len(set(v)) > 1)
    empty, zero = Counter(), Counter()
    for vals in by_ts.values():
        for c, x in zip(VALUE_COLS, vals[0]):
            if x.strip() == '':
                empty[c] += 1
            elif float(x) == 0.0:
                zero[c] += 1
    return {'rows': len(rows), 'unique_slots': len(by_ts), 'dup_rows': len(rows) - len(by_ts),
            'conflicting_slots': conflicting, 'off_grid': off_grid,
            'empty': dict(empty), 'zero': dict(zero), 'stamps': sorted(by_ts)}


def fetch_metrics(start: dt.date, end: dt.date) -> None:
    out = RAW / 'metrics'
    log_path = out / 'fetch_log.jsonl'
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    listing = {}
    for sym in SYMBOLS:
        keys = list_keys(f'data/futures/um/daily/metrics/{sym}/')
        zips = sorted(k for k in keys if k.endswith('.zip') and start <= key_date(k) <= end)
        listing[sym] = {'zips_listed': len(zips), 'checksums_listed': sum(k.endswith('.CHECKSUM') for k in keys)}
        (out / sym).mkdir(exist_ok=True)
        jobs += [(sym, k) for k in zips]

    def one(job):
        sym, key = job
        day = key_date(key)
        dest = out / sym / key.rsplit('/', 1)[1]
        want = _get(DATA + key + '.CHECKSUM').decode().split()[0]
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == want:
            zb, fresh = dest.read_bytes(), False
        else:
            zb, fresh = _get(DATA + key), True
            tmp = dest.with_suffix('.part')
            tmp.write_bytes(zb)
            tmp.replace(dest)
        sha = hashlib.sha256(zb).hexdigest()
        rec = {'sym': sym, 'date': day.isoformat(), 'url': DATA + key, 'file': str(dest.relative_to(RAW)),
               'bytes': len(zb), 'sha256': sha, 'checksum_ok': sha == want, 'fresh': fresh,
               'block': 'test_or_later' if day >= TEST_START else 'train_or_val',
               'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
        if day >= TEST_START:
            rec['rows'] = count_rows(zb)
            cov = None
        else:
            cov = day_coverage(read_metrics(zb, day), day)
            rec['rows'] = cov['rows']
        return rec, cov

    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(one, jobs))

    with log_path.open('a') as f:
        for rec, _ in results:
            f.write(json.dumps(rec) + '\n')
    write_coverage(out, start, end, listing, results)


def write_coverage(out: Path, start: dt.date, end: dt.date, listing: dict, results: list) -> None:
    report = {'source': 'binance um daily metrics', 'range': [start.isoformat(), end.isoformat()],
              'test_start': TEST_START.isoformat(), 'symbols': {}}
    for sym in SYMBOLS:
        rs = [(r, c) for r, c in results if r['sym'] == sym]
        dates = sorted(dt.date.fromisoformat(r['date']) for r, _ in rs)
        first = dates[0] if dates else None
        span = [first + dt.timedelta(d) for d in range((end - first).days + 1)] if first else []
        missing_days = sorted(set(span) - set(dates))
        pre = [(r, c) for r, c in rs if c is not None]
        stamps = sorted(s for _, c in pre for s in c['stamps'])
        gaps = []
        for a, b in zip(stamps, stamps[1:]):
            if b - a > dt.timedelta(minutes=5):
                gaps.append((a, b, int((b - a) / dt.timedelta(minutes=5)) - 1))
        gaps.sort(key=lambda g: -g[2])
        by_year = defaultdict(lambda: {'days': 0, 'slots': 0, 'dup_rows': 0, 'conflicting_slots': 0,
                                       'off_grid': 0, 'empty': Counter(), 'zero': Counter()})
        for r, c in pre:
            y = by_year[r['date'][:4]]
            y['days'] += 1
            y['slots'] += c['unique_slots']
            for k in ('dup_rows', 'conflicting_slots', 'off_grid'):
                y[k] += c[k]
            y['empty'].update(c['empty'])
            y['zero'].update(c['zero'])
        report['symbols'][sym] = {
            **listing[sym],
            'first_date': first.isoformat() if first else None,
            'last_date': dates[-1].isoformat() if dates else None,
            'files': len(rs),
            'checksum_failures': sum(not r['checksum_ok'] for r, _ in rs),
            'missing_days': [d.isoformat() for d in missing_days],
            'pre_test': {
                'days': len(pre), 'unique_slots': len(stamps),
                'expected_slots': len(pre) * 288,
                'missing_slots_total': sum(g[2] for g in gaps),
                'gaps_over_1h': sum(g[2] >= 12 for g in gaps),
                'largest_gaps': [[a.isoformat(), b.isoformat(), n] for a, b, n in gaps[:15]],
                'by_year': {k: {**v, 'empty': dict(v['empty']), 'zero': dict(v['zero'])}
                            for k, v in sorted(by_year.items())},
            },
            'test_or_later_row_counts': {'days': len(rs) - len(pre),
                                         'rows': sum(r['rows'] for r, c in rs if c is None)},
        }
    (out / 'coverage.json').write_text(json.dumps(report, indent=1))
    (out / 'coverage.md').write_text(coverage_md(report))


def coverage_md(rep: dict) -> str:
    lines = [f"# Coverage: {rep['source']}", '',
             f"Range {rep['range'][0]} → {rep['range'][1]}. Values were read only before {rep['test_start']}; after that, row counts only.", '']
    for sym, s in rep['symbols'].items():
        p = s['pre_test']
        lines += [f'## {sym}', '',
                  f"- First {s['first_date']}, last {s['last_date']}, {s['files']} files, {s['checksum_failures']} checksum failures.",
                  f"- Missing days ({len(s['missing_days'])}): {', '.join(s['missing_days'][:30]) or 'none'}{' …' if len(s['missing_days']) > 30 else ''}",
                  f"- Before test start: {p['days']} days, {p['unique_slots']} unique 5m slots of {p['expected_slots']} expected; "
                  f"{p['missing_slots_total']} missing slots inside the series; {p['gaps_over_1h']} gaps of 1h or more.",
                  f"- Test block and later: {s['test_or_later_row_counts']['days']} days, {s['test_or_later_row_counts']['rows']} rows (count only).",
                  '', '| Year | Days | Slots | Dup rows | Conflicting slots | Off-grid | Empty values | Zero values |',
                  '|---|---|---|---|---|---|---|---|']
        for y, v in p['by_year'].items():
            emp = ', '.join(f'{k}:{n}' for k, n in v['empty'].items()) or '0'
            zer = ', '.join(f'{k}:{n}' for k, n in v['zero'].items()) or '0'
            lines.append(f"| {y} | {v['days']} | {v['slots']} | {v['dup_rows']} | {v['conflicting_slots']} | {v['off_grid']} | {emp} | {zer} |")
        lines += ['', 'Largest gaps (from, to, missing slots):', '']
        lines += [f'- {a} → {b}: {n}' for a, b, n in p['largest_gaps']] or ['- none']
        lines.append('')
    return '\n'.join(lines)


# ---- monthly 1m klines: premiumIndexKlines / markPriceKlines / indexPriceKlines ----

KLINE_SOURCES = ('premiumIndexKlines', 'markPriceKlines', 'indexPriceKlines')
TEST_START_MS = int(dt.datetime(TEST_START.year, TEST_START.month, TEST_START.day,
                                tzinfo=dt.timezone.utc).timestamp() * 1000)


def key_month(key: str) -> dt.date:
    return dt.date.fromisoformat(key.rsplit('-1m-', 1)[1][:7] + '-01')


def _open_ms(field: str) -> int | None:
    """open_time in ms (accepts µs stamps); None for a header line."""
    if not field[:1].isdigit():
        return None
    t = int(field)
    return t // 1000 if t > 10 ** 14 else t


def split_kline_month(zbytes: bytes) -> tuple[list[tuple[int, float, float, float, float]], int]:
    """(rows before TEST_START as (open_ms, o, h, l, c), count of rows at/after TEST_START).

    Rows at or after the test start are counted from their timestamp only; their values are never parsed.
    """
    pre, post = [], 0
    for line in csv_text(zbytes).splitlines():
        if not line:
            continue
        f = line.split(',', 5)
        t = _open_ms(f[0])
        if t is None:
            continue
        if t >= TEST_START_MS:
            post += 1
            continue
        pre.append((t, float(f[1]), float(f[2]), float(f[3]), float(f[4])))
    return pre, post


def read_kline_month(zbytes: bytes, month: dt.date) -> list[tuple[int, float, float, float, float]]:
    """Parsed rows of a month that lies wholly before TEST_START. Refuses later months."""
    if month >= TEST_START.replace(day=1):
        raise BlockGuardError(f'{month:%Y-%m} is not wholly before test start {TEST_START}')
    pre, post = split_kline_month(zbytes)
    if post:
        raise BlockGuardError(f'{month:%Y-%m} holds {post} rows at/after test start')
    return pre


def month_coverage(rows: list[tuple], month: dt.date) -> dict:
    """Unique minutes, duplicates, off-grid stamps, stale runs (≥3 bars with o=h=l=c equal to the previous close)."""
    ts = [r[0] for r in rows]
    uniq = sorted(set(ts))
    off_grid = sum(t % 60000 != 0 for t in uniq)
    stale_runs, run, prev_c = 0, 0, None
    for _, o, h, l, c in sorted(rows):
        if prev_c is not None and o == h == l == c == prev_c:
            run += 1
        else:
            stale_runs += run >= 3
            run = 0
        prev_c = c
    stale_runs += run >= 3
    return {'rows': len(rows), 'unique_minutes': len(uniq), 'dup_rows': len(ts) - len(uniq),
            'off_grid': off_grid, 'stale_runs_3plus': stale_runs, 'stamps': uniq}


def _download_checked(key: str, dest: Path) -> tuple[bytes, str, bool, bool]:
    want = _get(DATA + key + '.CHECKSUM').decode().split()[0]
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == want:
        zb, fresh = dest.read_bytes(), False
    else:
        zb, fresh = _get(DATA + key), True
        tmp = dest.with_suffix('.part')
        tmp.write_bytes(zb)
        tmp.replace(dest)
    sha = hashlib.sha256(zb).hexdigest()
    return zb, sha, sha == want, fresh


def fetch_klines(start: dt.date, end: dt.date) -> None:
    for src in KLINE_SOURCES:
        out = RAW / src
        out.mkdir(parents=True, exist_ok=True)
        jobs, listing = [], {}
        for sym in SYMBOLS:
            keys = list_keys(f'data/futures/um/monthly/{src}/{sym}/1m/')
            zips = sorted(k for k in keys if k.endswith('.zip')
                          and start.replace(day=1) <= key_month(k) <= end.replace(day=1))
            listing[sym] = {'zips_listed': len(zips)}
            (out / sym).mkdir(exist_ok=True)
            jobs += [(sym, k) for k in zips]

        def one(job, out=out, src=src):
            sym, key = job
            month = key_month(key)
            dest = out / sym / key.rsplit('/', 1)[1]
            zb, sha, ok, fresh = _download_checked(key, dest)
            rec = {'src': src, 'sym': sym, 'month': f'{month:%Y-%m}', 'url': DATA + key,
                   'file': str(dest.relative_to(RAW)), 'bytes': len(zb), 'sha256': sha, 'checksum_ok': ok,
                   'fresh': fresh, 'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
            if month >= TEST_START.replace(day=1):
                pre, post = split_kline_month(zb)
                if month > TEST_START.replace(day=1):
                    assert not pre, f'{key}: rows before test start in a later month'
            else:
                pre, post = read_kline_month(zb, month), 0
            rec.update(rows_pre_test=len(pre), rows_test_or_later=post,
                       block='mixed' if pre and post else ('test_or_later' if post else 'train_or_val'))
            return rec, (month_coverage(pre, month) if pre else None)

        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(one, jobs))
        with (out / 'fetch_log.jsonl').open('a') as f:
            for rec, _ in results:
                f.write(json.dumps(rec) + '\n')
        write_kline_coverage(out, src, start, end, listing, results)
        print(src, 'done', len(results), 'files', flush=True)


def write_kline_coverage(out: Path, src: str, start: dt.date, end: dt.date, listing: dict, results: list) -> None:
    rep = {'source': f'binance um monthly {src} 1m', 'range': [f'{start:%Y-%m}', f'{end:%Y-%m}'],
           'test_start': TEST_START.isoformat(), 'symbols': {}}
    for sym in SYMBOLS:
        rs = sorted(((r, c) for r, c in results if r['sym'] == sym), key=lambda x: x[0]['month'])
        months = [r['month'] for r, _ in rs]
        if months:
            y, m = map(int, months[0].split('-'))
            span = []
            while (y, m) <= (end.year, end.month):
                span.append(f'{y:04d}-{m:02d}')
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        else:
            span = []
        stamps = [t for _, c in rs if c for t in c['stamps']]
        gaps = [(a, b, (b - a) // 60000 - 1) for a, b in zip(stamps, stamps[1:]) if b - a > 60000]
        gaps.sort(key=lambda g: -g[2])
        iso = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M')
        by_year = defaultdict(lambda: Counter())
        for r, c in rs:
            if c:
                by_year[r['month'][:4]].update({k: c[k] for k in ('rows', 'unique_minutes', 'dup_rows', 'off_grid', 'stale_runs_3plus')})
        rep['symbols'][sym] = {
            **listing[sym], 'first_month': months[0] if months else None, 'last_month': months[-1] if months else None,
            'missing_months': sorted(set(span) - set(months)),
            'checksum_failures': sum(not r['checksum_ok'] for r, _ in rs),
            'pre_test': {'unique_minutes': len(stamps), 'missing_minutes_total': sum(g[2] for g in gaps),
                         'gaps_over_1h': sum(g[2] >= 60 for g in gaps),
                         'largest_gaps': [[iso(a), iso(b), n] for a, b, n in gaps[:15]],
                         'by_year': {k: dict(v) for k, v in sorted(by_year.items())}},
            'test_or_later_rows': sum(r['rows_test_or_later'] for r, _ in rs),
        }
    (out / 'coverage.json').write_text(json.dumps(rep, indent=1))
    lines = [f"# Coverage: {rep['source']}", '',
             f"Range {rep['range'][0]} → {rep['range'][1]}. Values parsed only for bars opening before {TEST_START}; later bars counted from their timestamp.", '']
    for sym, s in rep['symbols'].items():
        p = s['pre_test']
        lines += [f'## {sym}', '',
                  f"- First {s['first_month']}, last {s['last_month']}, missing months: {', '.join(s['missing_months']) or 'none'}; {s['checksum_failures']} checksum failures.",
                  f"- Before test start: {p['unique_minutes']} unique minutes; {p['missing_minutes_total']} missing minutes inside the series; {p['gaps_over_1h']} gaps of 1h or more.",
                  f"- Test block and later: {s['test_or_later_rows']} rows (count only).", '',
                  '| Year | Rows | Unique minutes | Dup rows | Off-grid | Stale runs ≥3 |', '|---|---|---|---|---|---|']
        lines += [f"| {y} | {v['rows']} | {v['unique_minutes']} | {v['dup_rows']} | {v['off_grid']} | {v['stale_runs_3plus']} |"
                  for y, v in p['by_year'].items()]
        lines += ['', 'Largest gaps (from, to, missing minutes):', '']
        lines += [f'- {a} → {b}: {n}' for a, b, n in p['largest_gaps']] or ['- none']
        lines.append('')
    (out / 'coverage.md').write_text('\n'.join(lines))


def _monthly_pre_rows(path: Path, month: dt.date) -> list[tuple]:
    if month < TEST_START.replace(day=1):
        return read_kline_month(path.read_bytes(), month)
    return split_kline_month(path.read_bytes())[0]


def backfill_klines() -> None:
    """Fill whole or partial days missing from the monthly files with daily files (pre-test days only)."""
    for src in KLINE_SOURCES:
        out = RAW / src
        recs = {}
        for line in (out / 'fetch_log.jsonl').read_text().splitlines():
            r = json.loads(line)
            if 'month' in r:
                recs[(r['sym'], r['month'])] = r
        summary, results = {}, []
        for sym in SYMBOLS:
            months = sorted(m for s, m in recs if s == sym)
            merged = {}
            for m in months:
                mo = dt.date.fromisoformat(m + '-01')
                if mo > TEST_START.replace(day=1):
                    continue
                for row in _monthly_pre_rows(RAW / recs[(sym, m)]['file'], mo):
                    merged.setdefault(row[0], row)
            first_day = dt.date.fromisoformat(months[0] + '-01')
            per_day = Counter(dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).date() for t in merged)
            short = [first_day + dt.timedelta(d) for d in range((TEST_START - first_day).days)
                     if per_day[first_day + dt.timedelta(d)] < 1440]
            ddir = out / sym / 'daily'
            ddir.mkdir(exist_ok=True)

            def one(day, sym=sym, src=src, ddir=ddir):
                key = f'data/futures/um/daily/{src}/{sym}/1m/{sym}-1m-{day.isoformat()}.zip'
                try:
                    zb, sha, ok, fresh = _download_checked(key, ddir / key.rsplit('/', 1)[1])
                except Exception as e:  # noqa: BLE001 — a missing daily file is a coverage fact, not a crash
                    return {'src': src, 'sym': sym, 'day': day.isoformat(), 'url': DATA + key, 'error': str(e)[:200]}, []
                pre, post = split_kline_month(zb)
                assert post == 0, f'{key}: rows at/after test start'
                return ({'src': src, 'sym': sym, 'day': day.isoformat(), 'url': DATA + key,
                         'file': str((ddir / key.rsplit('/', 1)[1]).relative_to(RAW)), 'bytes': len(zb),
                         'sha256': sha, 'checksum_ok': ok, 'fresh': fresh, 'rows': len(pre),
                         'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}, pre)

            with ThreadPoolExecutor(WORKERS) as ex:
                got = list(ex.map(one, short))
            added = conflicts = 0
            for rec, rows in got:
                for row in rows:
                    if row[0] in merged:
                        conflicts += merged[row[0]][1:] != row[1:]
                    else:
                        merged[row[0]] = row
                        added += 1
                rec['added_minutes'] = len(rows)
            with (out / 'fetch_log.jsonl').open('a') as f:
                for rec, _ in got:
                    f.write(json.dumps(rec) + '\n')
            summary[sym] = {'short_days': len(short), 'daily_fetched': sum('error' not in r for r, _ in got),
                            'daily_missing': [r['day'] for r, _ in got if 'error' in r],
                            'minutes_added': added, 'overlap_conflicts': conflicts}
            by_month = defaultdict(list)
            for row in merged.values():
                by_month[dt.datetime.fromtimestamp(row[0] / 1000, dt.timezone.utc).strftime('%Y-%m')].append(row)
            for m in months:
                r = recs[(sym, m)]
                rows = by_month.get(m, [])
                results.append((r, month_coverage(rows, dt.date.fromisoformat(m + '-01')) if rows else None))
            del merged
        merged_dir = out / 'merged'
        merged_dir.mkdir(exist_ok=True)
        listing = {s: {'zips_listed': sum(1 for x, _ in recs if x == s)} for s in SYMBOLS}
        write_kline_coverage(merged_dir, src, dt.date(2020, 1, 1), dt.date(2026, 9, 30), listing, results)
        (merged_dir / 'backfill_summary.json').write_text(json.dumps(summary, indent=1))
        print(src, json.dumps(summary), flush=True)


# ---- Coinbase Exchange spot candles (5m; 1m would need ~26k calls, over the loop's time budget) ----

CB_API = 'https://api.exchange.coinbase.com/products/{p}/candles?granularity={g}&start={s}&end={e}'
CB_PRODUCTS = ('BTC-USD', 'ETH-USD', 'USDT-USD')
CB_GRAN = 300
CB_FIRST = {'USDT-USD': dt.date(2021, 4, 1)}  # probed: no USDT-USD candles before 2021-05
CB_MIN_INTERVAL = 0.34  # <= 3 requests per second
TEST_START_S = TEST_START_MS // 1000


def cb_windows(month: dt.date, gran: int = CB_GRAN) -> list[tuple[int, int]]:
    """[start, end] epoch-second request windows of <=300 bars covering one UTC month, clipped before TEST_START."""
    m0 = int(dt.datetime(month.year, month.month, 1, tzinfo=dt.timezone.utc).timestamp())
    nxt = dt.date(month.year + month.month // 12, month.month % 12 + 1, 1)
    m1 = min(int(dt.datetime(nxt.year, nxt.month, 1, tzinfo=dt.timezone.utc).timestamp()), TEST_START_S)
    out, s = [], m0
    while s < m1:
        e = min(s + 300 * gran, m1)
        out.append((s, e - gran))  # the API's end is inclusive
        s = e
    return out


def cb_keep_pre_test(rows: list) -> tuple[list, int]:
    """Rows with bar start before TEST_START, and how many were dropped (timestamp only)."""
    keep = [r for r in rows if r[0] < TEST_START_S]
    return keep, len(rows) - len(keep)


def _cb_get(url: str, state: dict) -> tuple[list, int]:
    for i in range(6):
        wait = state['last'] + CB_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        state['last'] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read()), r.status
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == 5:
                raise
        except Exception:
            if i == 5:
                raise
        time.sleep(2 ** i)
    raise AssertionError


def fetch_coinbase(start: dt.date) -> None:
    import gzip
    out = RAW / 'coinbase'
    out.mkdir(parents=True, exist_ok=True)
    state = {'last': 0.0}
    log = (out / 'fetch_log.jsonl').open('a')
    last_month = TEST_START.replace(day=1)
    for prod in CB_PRODUCTS:
        (out / prod).mkdir(exist_ok=True)
        m = max(start, CB_FIRST.get(prod, start)).replace(day=1)
        while m <= last_month:
            dest = out / prod / f'{m:%Y-%m}.csv.gz'
            if not dest.exists():
                rows, dropped = {}, 0
                for s, e in cb_windows(m):
                    url = CB_API.format(p=prod, g=CB_GRAN, s=dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                                        e=dt.datetime.fromtimestamp(e, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
                    data, status = _cb_get(url, state)
                    keep, d = cb_keep_pre_test(data)
                    dropped += d
                    for t, lo, hi, op, cl, v in keep:
                        rows[t] = (t, op, hi, lo, cl, v)
                    log.write(json.dumps({'src': 'coinbase', 'product': prod, 'url': url, 'status': status,
                                          'rows': len(data), 'dropped_test_rows': d}) + '\n')
                body = 't,open,high,low,close,volume\n' + ''.join(','.join(map(str, rows[t])) + '\n' for t in sorted(rows))
                gz = gzip.compress(body.encode(), mtime=0)
                tmp = dest.with_suffix('.part')
                tmp.write_bytes(gz)
                tmp.replace(dest)
                log.write(json.dumps({'src': 'coinbase', 'product': prod, 'month': f'{m:%Y-%m}', 'file': str(dest.relative_to(RAW)),
                                      'bars': len(rows), 'dropped_test_rows': dropped, 'sha256': hashlib.sha256(gz).hexdigest(),
                                      'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}) + '\n')
                log.flush()
                print(prod, f'{m:%Y-%m}', len(rows), flush=True)
            m = dt.date(m.year + m.month // 12, m.month % 12 + 1, 1)
    log.close()
    write_coinbase_coverage(out)


def write_coinbase_coverage(out: Path) -> None:
    import gzip
    rep = {'source': f'coinbase exchange candles {CB_GRAN}s', 'test_start': TEST_START.isoformat(), 'products': {}}
    lines = [f"# Coverage: {rep['source']}", '', f'Fetched only bars starting before {TEST_START}; the test block was not requested.', '']
    for prod in CB_PRODUCTS:
        ts, zero, by_year = [], 0, Counter()
        for f in sorted((out / prod).glob('*.csv.gz')):
            for line in gzip.decompress(f.read_bytes()).decode().splitlines()[1:]:
                t, o, h, l, c, v = line.split(',')
                t = int(t)
                assert t < TEST_START_S
                ts.append(t)
                zero += float(v) == 0.0
                by_year[dt.datetime.fromtimestamp(t, dt.timezone.utc).year] += 1
        ts.sort()
        gaps = sorted(((a, b, (b - a) // CB_GRAN - 1) for a, b in zip(ts, ts[1:]) if b - a > CB_GRAN), key=lambda g: -g[2])
        iso = lambda s: dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M')
        first = iso(ts[0]) if ts else None
        rep['products'][prod] = {'first_bar': first, 'last_bar': iso(ts[-1]) if ts else None, 'bars': len(ts),
                                 'missing_slots': sum(g[2] for g in gaps), 'gaps_over_1h': sum(g[2] >= 12 for g in gaps),
                                 'zero_volume_bars': zero, 'bars_by_year': dict(by_year),
                                 'largest_gaps': [[iso(a), iso(b), n] for a, b, n in gaps[:15]]}
        p = rep['products'][prod]
        lines += [f'## {prod}', '', f"- First bar {p['first_bar']}, last {p['last_bar']}, {p['bars']} bars, {p['zero_volume_bars']} with zero volume.",
                  f"- {p['missing_slots']} missing 5m slots inside the series (Coinbase omits bars with no trades); {p['gaps_over_1h']} gaps of 1h or more.",
                  f"- Bars by year: {', '.join(f'{y}: {n}' for y, n in sorted(by_year.items()))}", '', 'Largest gaps:', '']
        lines += [f'- {a} → {b}: {n}' for a, b, n in p['largest_gaps']] or ['- none']
        lines.append('')
    (out / 'coverage.json').write_text(json.dumps(rep, indent=1))
    (out / 'coverage.md').write_text('\n'.join(lines))


# ---- Deribit DVOL (30-day implied vol index), hourly ----

DVOL_API = ('https://www.deribit.com/api/v2/public/get_volatility_index_data?currency={c}'
            '&start_timestamp={s}&end_timestamp={e}&resolution=3600')
DVOL_CURRENCIES = ('BTC', 'ETH')
DVOL_START = dt.date(2021, 3, 24)
HOUR_MS = 3_600_000


def dvol_windows(start_ms: int, gap_ms: int = 900 * HOUR_MS) -> list[tuple[int, int]]:
    """Inclusive [start, end] ms windows of <=900 hourly bars, the last ending at the final bar before TEST_START."""
    last = TEST_START_MS - HOUR_MS
    out, s = [], start_ms
    while s <= last:
        e = min(s + gap_ms - HOUR_MS, last)
        out.append((s, e))
        s = e + HOUR_MS
    return out


def fetch_dvol() -> None:
    import gzip
    out = RAW / 'dvol'
    out.mkdir(parents=True, exist_ok=True)
    state = {'last': 0.0}
    rep = {'source': 'deribit DVOL hourly (bar stamped at hour start; usable at hour end)',
           'test_start': TEST_START.isoformat(), 'currencies': {}}
    lines = [f"# Coverage: {rep['source']}", '', f'Requested only bars starting before {TEST_START}.', '']
    iso = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M')
    with (out / 'fetch_log.jsonl').open('a') as log:
        for cur in DVOL_CURRENCIES:
            start_ms = int(dt.datetime(DVOL_START.year, DVOL_START.month, DVOL_START.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
            rows, dropped = {}, 0
            for s, e in dvol_windows(start_ms):
                url = DVOL_API.format(c=cur, s=s, e=e)
                data, status = _cb_get(url, state)
                res = data['result']
                assert res.get('continuation') is None, f'{url}: paged response'
                pts = res['data']
                for t, o, h, l, c in pts:
                    if t >= TEST_START_MS:
                        dropped += 1
                        continue
                    rows[t] = (t, o, h, l, c)
                log.write(json.dumps({'src': 'dvol', 'currency': cur, 'url': url, 'status': status, 'rows': len(pts)}) + '\n')
            ts = sorted(rows)
            body = 't_ms,open,high,low,close\n' + ''.join(','.join(map(str, rows[t])) + '\n' for t in ts)
            gz = gzip.compress(body.encode(), mtime=0)
            dest = out / f'{cur}.csv.gz'
            dest.write_bytes(gz)
            off_grid = sum(t % HOUR_MS != 0 for t in ts)
            gaps = sorted(((a, b, (b - a) // HOUR_MS - 1) for a, b in zip(ts, ts[1:]) if b - a > HOUR_MS), key=lambda g: -g[2])
            stale = sum(1 for a, b in zip(ts, ts[1:]) if rows[a][1:] == rows[b][1:])
            vals = [rows[t][4] for t in ts]
            log.write(json.dumps({'src': 'dvol', 'currency': cur, 'file': str(dest.relative_to(RAW)), 'bars': len(ts),
                                  'dropped_test_rows': dropped, 'sha256': hashlib.sha256(gz).hexdigest(),
                                  'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}) + '\n')
            r = rep['currencies'][cur] = {
                'first_bar': iso(ts[0]), 'last_bar': iso(ts[-1]), 'bars': len(ts), 'dropped_test_rows': dropped,
                'missing_hours': sum(g[2] for g in gaps), 'gaps_over_6h': sum(g[2] >= 6 for g in gaps),
                'off_grid': off_grid, 'repeated_bars': stale, 'close_min': min(vals), 'close_max': max(vals),
                'nonpositive': sum(v <= 0 for v in vals), 'largest_gaps': [[iso(a), iso(b), n] for a, b, n in gaps[:15]]}
            lines += [f'## {cur}', '', f"- First {r['first_bar']}, last {r['last_bar']}, {r['bars']} hourly bars; "
                      f"{r['missing_hours']} missing hours, {r['gaps_over_6h']} gaps of 6h or more; {r['off_grid']} off-grid stamps.",
                      f"- Close range {r['close_min']} → {r['close_max']}; {r['nonpositive']} non-positive; "
                      f"{r['repeated_bars']} bars identical to the previous one; {dropped} test-block rows dropped by timestamp.",
                      '', 'Largest gaps:', '']
            lines += [f'- {a} → {b}: {n}' for a, b, n in r['largest_gaps']] or ['- none']
            lines.append('')
    (out / 'coverage.json').write_text(json.dumps(rep, indent=1))
    (out / 'coverage.md').write_text('\n'.join(lines))
    print('\n'.join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('source', choices=['metrics', 'klines', 'klines-backfill', 'coinbase', 'dvol'])
    ap.add_argument('--start', default=None)
    ap.add_argument('--end', default='2026-09-30')
    a = ap.parse_args()
    start = dt.date.fromisoformat(a.start or ('2020-09-01' if a.source == 'metrics' else '2020-01-01'))
    end = dt.date.fromisoformat(a.end)
    if end >= FORWARD_START:
        raise SystemExit(f'--end must be before {FORWARD_START} (forward data is reserved)')
    if a.source == 'metrics':
        fetch_metrics(start, end)
    elif a.source == 'dvol':
        fetch_dvol()
    elif a.source == 'coinbase':
        fetch_coinbase(dt.date.fromisoformat(a.start or '2020-03-01'))
    elif a.source == 'klines':
        fetch_klines(start, end)
    else:
        backfill_klines()


if __name__ == '__main__':
    main()
