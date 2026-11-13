import datetime as dt
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_free as ff  # noqa: E402

HDR = ('create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,'
       'sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n')


def zipped(rows: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('x.csv', HDR + rows)
    return b.getvalue()


ROW = '{t},BTCUSDT,1,2,3,4,5,{v}\n'


class BlockGuard(unittest.TestCase):
    def test_refuses_test_day(self):
        zb = zipped(ROW.format(t='2025-07-08 00:00:00', v=1))
        with self.assertRaises(ff.BlockGuardError):
            ff.read_metrics(zb, dt.date(2025, 7, 8))

    def test_refuses_test_row_in_earlier_file(self):
        zb = zipped(ROW.format(t='2025-07-07 23:55:00', v=1) + ROW.format(t='2025-07-08 00:00:00', v=1))
        with self.assertRaises(ff.BlockGuardError):
            ff.read_metrics(zb, dt.date(2025, 7, 7))

    def test_count_rows_without_header(self):
        zb = zipped(ROW.format(t='2025-08-01 00:00:00', v=1) * 3)
        self.assertEqual(ff.count_rows(zb), 3)


class Coverage(unittest.TestCase):
    def test_duplicates_and_conflicts(self):
        d = dt.date(2021, 1, 1)
        rows = ff.read_metrics(zipped(ROW.format(t='2021-01-01 00:00:00', v=1) * 2
                                      + ROW.format(t='2021-01-01 00:05:00', v=1)
                                      + ROW.format(t='2021-01-01 00:05:00', v=2)
                                      + ROW.format(t='2021-01-01 00:07:00', v=0)), d)
        c = ff.day_coverage(rows, d)
        self.assertEqual((c['rows'], c['unique_slots'], c['dup_rows']), (5, 3, 2))
        self.assertEqual(c['conflicting_slots'], 1)
        self.assertEqual(c['off_grid'], 1)
        self.assertEqual(c['zero'], {'sum_taker_long_short_vol_ratio': 1})


KHDR = 'open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n'


def kzip(ms_list, header=True, vals='1,2,0.5,1.5'):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('k.csv', (KHDR if header else '') + ''.join(f'{t},{vals},0,{t + 59999},0,12,0,0,0\n' for t in ms_list))
    return b.getvalue()


class KlineGuard(unittest.TestCase):
    T = ff.TEST_START_MS

    def test_straddling_month_splits_at_test_start(self):
        zb = kzip([self.T - 120000, self.T - 60000, self.T, self.T + 60000])
        pre, post = ff.split_kline_month(zb)
        self.assertEqual([r[0] for r in pre], [self.T - 120000, self.T - 60000])
        self.assertEqual(post, 2)

    def test_post_rows_values_never_parsed(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr('k.csv', f'{self.T - 60000},1,2,0.5,1.5,0,0,0,12,0,0,0\n{self.T},NOT_A_NUMBER,x,y,z,0,0,0,12,0,0,0\n')
        pre, post = ff.split_kline_month(b.getvalue())
        self.assertEqual((len(pre), post), (1, 1))

    def test_read_refuses_test_month(self):
        with self.assertRaises(ff.BlockGuardError):
            ff.read_kline_month(kzip([self.T - 60000]), dt.date(2025, 7, 1))

    def test_microsecond_stamps_and_no_header(self):
        pre, post = ff.split_kline_month(kzip([(self.T - 60000) * 1000], header=False))
        self.assertEqual((pre[0][0], post), (self.T - 60000, 0))

    def test_month_coverage_stale_and_dups(self):
        rows = [(i * 60000, 1.0, 1.0, 1.0, 1.0) for i in range(5)] + [(0, 1.0, 1.0, 1.0, 1.0), (5 * 60000 + 1, 1.0, 2.0, 0.5, 1.2)]
        c = ff.month_coverage(rows, dt.date(2021, 1, 1))
        self.assertEqual((c['dup_rows'], c['off_grid'], c['stale_runs_3plus']), (1, 1, 1))



class CoinbaseGuard(unittest.TestCase):
    def test_windows_cover_month_and_stop_before_test(self):
        w = ff.cb_windows(dt.date(2025, 7, 1))
        self.assertEqual(w[0][0], int(dt.datetime(2025, 7, 1, tzinfo=dt.timezone.utc).timestamp()))
        self.assertEqual(w[-1][1], ff.TEST_START_S - ff.CB_GRAN)
        self.assertTrue(all(e - s < 300 * ff.CB_GRAN for s, e in w))
        self.assertTrue(all(b[0] == a[1] + ff.CB_GRAN for a, b in zip(w, w[1:])))
        self.assertEqual(ff.cb_windows(dt.date(2025, 8, 1)), [])

    def test_full_month_window_count(self):
        w = ff.cb_windows(dt.date(2021, 2, 1))
        self.assertEqual(sum((e - s) // ff.CB_GRAN + 1 for s, e in w), 28 * 288)

    def test_drops_rows_at_or_after_test_start(self):
        keep, dropped = ff.cb_keep_pre_test([[ff.TEST_START_S - 300, 1, 2, 1, 2, 3], [ff.TEST_START_S, 9, 9, 9, 9, 9]])
        self.assertEqual((len(keep), dropped), (1, 1))



class DvolGuard(unittest.TestCase):
    def test_windows_contiguous_and_end_before_test(self):
        w = ff.dvol_windows(ff.TEST_START_MS - 2000 * ff.HOUR_MS)
        self.assertEqual(w[-1][1], ff.TEST_START_MS - ff.HOUR_MS)
        self.assertTrue(all(b[0] == a[1] + ff.HOUR_MS for a, b in zip(w, w[1:])))
        self.assertEqual(sum((e - s) // ff.HOUR_MS + 1 for s, e in w), 2000)
        self.assertTrue(all((e - s) // ff.HOUR_MS + 1 <= 900 for s, e in w))


if __name__ == '__main__':
    unittest.main()
