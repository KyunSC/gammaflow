"""Offline checks for the exact volume-at-price partitions the chart's profile reads."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import publish_tick_profiles as pub

START = pd.Timestamp("2026-07-06 13:25", tz="UTC")


def write_chunk(folder: Path, prints: list[tuple], minutes: int = 3, start: pd.Timestamp = START,
                name: str = "2026-07-06_2026-07-07") -> None:
    """prints: (seconds after start, price, size, instrument_id[, side]); side defaults to "N"."""
    stem = folder / name
    end = start + pd.Timedelta(minutes=minutes)
    stem.with_suffix(".request.json").write_text(json.dumps(
        {"request": {"start": str(start), "end": str(end)}}))
    pd.DataFrame({
        "ts_event": [start + pd.Timedelta(seconds=p[0]) for p in prints],
        "price": [p[1] for p in prints],
        "size": pd.array([p[2] for p in prints], dtype="uint32"),
        "instrument_id": pd.array([p[3] for p in prints], dtype="uint32"),
        "side": [p[4] if len(p) > 4 else "N" for p in prints],
    }).to_parquet(stem.with_suffix(".parquet"))


class PublishTests(unittest.TestCase):
    def publish(self, prints, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "src", Path(tmp) / "out"
            src.mkdir()
            write_chunk(src, prints, **kw)
            pub.publish(src, out, "NQ")
            index = json.loads((out / "NQ" / "index.json").read_text())
            day = json.loads(gzip.decompress((out / "NQ" / index["sessions"][0]["file"]).read_bytes()))
            return index, day

    def test_minutes_hold_contiguous_tick_slots(self):
        index, day = self.publish([
            (5, 100.00, 2, 1), (10, 100.75, 3, 1), (20, 100.00, 1, 1),  # minute 0
            (70, 101.00, 4, 1),                                              # minute 1
        ])
        t0 = int(START.timestamp())
        self.assertEqual(index["sessions"], [{"date": "2026-07-06", "start": t0, "end": t0 + 180,
                                              "file": "2026-07-06.json.gz"}])
        self.assertEqual(day["minutes"], [[t0, 400, 3, 0, 0, 3], [t0 + 60, 404, 4]])
        self.assertEqual((day["volume"], day["tickSize"]), (10, 0.25))

    def test_drops_prints_off_the_front_contract_and_outside_the_span(self):
        _, day = self.publish([(5, 100.0, 5, 1), (6, 300.0, 1, 2), (7, 100.0, 1, 1),
                               (200, 100.0, 9, 1)], minutes=3)
        self.assertEqual(day["volume"], 6)
        self.assertEqual(len(day["minutes"]), 1)

    def test_delta_is_buy_minus_sell_aggressor_per_slot(self):
        _, day = self.publish([
            (5, 100.00, 2, 1, "B"), (6, 100.00, 5, 1, "A"), (7, 100.50, 3, 1, "B"),
            (8, 100.50, 1, 1, "N"),                                            # minute 0
            (70, 101.00, 4, 1, "A"),                                           # minute 1
        ])
        self.assertEqual(day["minutes"][0][2:], [7, 0, 4])
        self.assertEqual(day["delta"], [[-3, 0, 3], [-4]])

    def test_two_chunks_on_one_date_get_their_own_files(self):
        later = START + pd.Timedelta(hours=1)
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "src", Path(tmp) / "out"
            src.mkdir()
            write_chunk(src, [(5, 100.0, 2, 1)], name="2026-07-06a")
            write_chunk(src, [(5, 110.0, 7, 1)], start=later, name="2026-07-06b")
            pub.publish(src, out, "NQ")
            index = json.loads((out / "NQ" / "index.json").read_text())
            days = [json.loads(gzip.decompress((out / "NQ" / s["file"]).read_bytes())) for s in index["sessions"]]
        self.assertEqual([s["file"] for s in index["sessions"]], ["2026-07-06.json.gz", "2026-07-06-2.json.gz"])
        self.assertEqual([s["date"] for s in index["sessions"]], ["2026-07-06", "2026-07-06"])
        self.assertEqual([d["minutes"] for d in days], [[[int(START.timestamp()), 400, 2]],
                                                         [[int(later.timestamp()), 440, 7]]])

    def test_rejects_prices_off_the_tick_grid(self):
        with self.assertRaises(ValueError):
            self.publish([(5, 100.1, 1, 1)])


if __name__ == "__main__":
    unittest.main()
