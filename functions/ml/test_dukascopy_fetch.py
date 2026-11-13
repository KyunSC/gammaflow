import lzma
import struct
import unittest
from datetime import date

import dukascopy_fetch as dk


class DukascopyTest(unittest.TestCase):
    def blob(self, rows):
        return lzma.compress(b"".join(struct.pack(">5if", *r) for r in rows), format=lzma.FORMAT_ALONE)

    def test_decode_orders_ohlc(self):
        rows = dk.decode(self.blob([(60, 119374, 119371, 119369, 119375, 25.5)]), 1e5, date(2015, 1, 6))
        ts, o, h, l, c, v = rows[0]
        self.assertEqual(ts.isoformat(), "2015-01-06T00:01:00+00:00")
        self.assertEqual((o, h, l, c, v), (1.19374, 1.19375, 1.19369, 1.19371, 25.5))

    def test_bad_ohlc_refused(self):
        with self.assertRaises(ValueError):
            dk.decode(self.blob([(0, 100, 100, 101, 102, 1.0)]), 1e3, date(2015, 1, 6))

    def test_empty_day_and_month_index(self):
        self.assertEqual(dk.decode(b"", 1e5, date(2015, 1, 1)), [])
        self.assertIn("/2015/00/06/", dk.URL.format(sym="EURUSD", y=2015, m=0, d=6, side="BID"))
        self.assertEqual(len(list(dk.weekdays(date(2026, 8, 10), date(2026, 8, 17)))), 5)


if __name__ == "__main__":
    unittest.main()
