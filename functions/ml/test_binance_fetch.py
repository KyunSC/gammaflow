"""Offline checks for binance_fetch.py and crypto_holdout.py: synthetic zips, no network."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

import binance_fetch as bf
import crypto_holdout as ch


def kline_zip(month: str, drop: int = 0, header: bool = True, step: int = 60) -> bytes:
    start, end = bf.month_bounds(month)
    t = np.arange(start, end, step)
    if drop:
        t = np.delete(t, np.arange(100, 100 + drop))
    rows = [f"{s * 1000},1,2,0.5,1.5,10,{s * 1000 + 59999},15,3,4,6,0" for s in t]
    body = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
            if header else "") + "\n".join(rows) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"X-1m-{month}.csv", body)
    return buf.getvalue()


def funding_zip(month: str) -> bytes:
    start, _ = bf.month_bounds(month)
    body = "calc_time,funding_interval_hours,last_funding_rate\n" + "\n".join(f"{(start + k * 28800) * 1000},8,0.0001" for k in range(3))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("f.csv", body)
    return buf.getvalue()


def fake_fetch(files: dict):
    def fetch(url):
        if url.endswith(".CHECKSUM"):
            blob = files.get(url[: -len(".CHECKSUM")])
            return None if blob is None else f"{hashlib.sha256(blob).hexdigest()}  x.zip".encode()
        return files.get(url)
    return fetch


class FetchTests(unittest.TestCase):
    def test_months_and_bounds(self):
        self.assertEqual(bf.months("2023-11", "2024-02"), ["2023-11", "2023-12", "2024-01", "2024-02"])
        s, e = bf.month_bounds("2024-02")
        self.assertEqual((e - s) // 60, 29 * 1440)
        self.assertEqual(bf.last_full_month(pd.Timestamp("2026-01-05").date()), "2025-12")

    def test_parse_with_and_without_header(self):
        a = bf.parse_klines(kline_zip("2020-02", header=False))
        b = bf.parse_klines(kline_zip("2020-02", header=True))
        self.assertEqual(len(a), 29 * 1440)
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(int(a["time"].iloc[0]), bf.month_bounds("2020-02")[0])

    def test_coverage_finds_holes(self):
        rep = bf.coverage(bf.parse_klines(kline_zip("2024-03", drop=90))["time"].to_numpy(), "2024-03")
        self.assertEqual(rep["expected"] - rep["bars"], 90)
        self.assertEqual(len(rep["holes"]), 1)
        self.assertEqual(rep["holes"][0]["missing_bars"], 90)

    def test_fetch_month_verifies_and_quarantines_gappy_months(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ok, bad = "2024-01", "2024-02"
            files = {bf.kline_url("BTCUSDT", ok): kline_zip(ok), bf.kline_url("BTCUSDT", bad): kline_zip(bad, drop=200),
                     bf.funding_url("BTCUSDT", ok): funding_zip(ok)}
            self.assertEqual(bf.fetch_month("BTCUSDT", ok, root, fake_fetch(files))["status"], "ok")
            self.assertEqual(bf.fetch_month("BTCUSDT", bad, root, fake_fetch(files))["status"], "gappy")
            self.assertTrue((root / "klines-1m/BTCUSDT/2024-01.parquet").exists())
            self.assertTrue((root / "klines-1m/BTCUSDT/2024-02.gappy.parquet").exists())
            self.assertEqual(len(pd.read_parquet(root / "funding/BTCUSDT/2024-01.parquet")), 3)
            self.assertEqual(bf.fetch_month("BTCUSDT", ok, root, fake_fetch(files))["status"], "cached")
            self.assertEqual(bf.fetch_month("BTCUSDT", "2024-03", root, fake_fetch(files))["status"], "not-published")

    def test_checksum_mismatch_refuses(self):
        blob = kline_zip("2024-01")
        with self.assertRaises(RuntimeError):
            bf.verify(blob, b"0" * 64, "u")
        with self.assertRaises(RuntimeError):
            bf.verify(blob, None, "u")


class HoldoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "um"
        self.log = Path(self.tmp.name) / "looks.jsonl"
        for m in ["2024-06", "2024-07", "2024-08"]:
            bars = bf.parse_klines(kline_zip(m, step=3600 * 6))
            f = self.root / "klines-1m" / "BTCUSDT" / f"{m}.parquet"
            f.parent.mkdir(parents=True, exist_ok=True)
            bars.to_parquet(f, index=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_blocks_are_ordered_with_embargoes(self):
        names = ["train", "validation", "test"]
        for a, b in zip(names, names[1:]):
            gap = ch._ts(ch.BLOCKS[b][0]) - ch._ts(ch.BLOCKS[a][1])
            self.assertGreaterEqual(gap, pd.Timedelta(days=ch.EMBARGO_DAYS))

    def test_block_never_returns_data_outside_its_dates(self):
        with ch.open_block("validation", purpose="t", root=self.root, log=self.log) as b:
            with self.assertRaises(ch.HoldoutError):
                b.bars("BTCUSDT")  # needs months up to 2025-06, not on disk
        b = ch.Block("validation", ch._ts("2024-07-08"), ch._ts("2024-08-01"), self.root)
        t = b.bars("BTCUSDT")["time"]
        self.assertGreaterEqual(t.min(), ch._ts("2024-07-08").timestamp())
        self.assertLess(t.max(), ch._ts("2024-08-01").timestamp())
        w = b.bars("BTCUSDT", warmup_days=10)["time"]
        self.assertLess(w.min(), ch._ts("2024-07-08").timestamp())
        self.assertLess(w.max(), ch._ts("2024-08-01").timestamp())

    def test_gappy_months_do_not_load(self):
        f = self.root / "klines-1m" / "BTCUSDT" / "2024-07.parquet"
        f.rename(f.with_suffix(".gappy.parquet"))
        b = ch.Block("x", ch._ts("2024-07-08"), ch._ts("2024-08-01"), self.root)
        with self.assertRaisesRegex(ch.HoldoutError, "coverage"):
            b.bars("BTCUSDT")

    def test_validation_is_capped_and_test_opens_once(self):
        for k in range(ch.MAX_VALIDATION_LOOKS):
            with ch.open_block("validation", purpose=f"cut {k}", root=self.root, log=self.log):
                pass
        with self.assertRaises(ch.HoldoutError):
            with ch.open_block("validation", purpose="one more", root=self.root, log=self.log):
                pass
        with self.assertRaises(ch.HoldoutError):
            with ch.open_block("test", purpose="no specs", root=self.root, log=self.log):
                pass
        with ch.open_block("test", purpose="score", spec_hashes=["abc123"], root=self.root, log=self.log):
            pass
        with self.assertRaisesRegex(ch.HoldoutError, "one look"):
            with ch.open_block("test", purpose="again", spec_hashes=["abc123"], root=self.root, log=self.log):
                pass
        self.assertEqual([x["block"] for x in ch.looks(self.log)].count("test"), 1)

    def test_train_needs_a_purpose(self):
        with self.assertRaises(ch.HoldoutError):
            with ch.open_block("train", purpose="", root=self.root, log=self.log):
                pass


if __name__ == "__main__":
    unittest.main()
