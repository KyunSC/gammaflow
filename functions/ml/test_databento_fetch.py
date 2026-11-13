"""Offline checks: never instantiate a real client or read credentials."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import databento_fetch as fetch


class FetchTests(unittest.TestCase):
    def test_daily_jobs_cover_each_weekday(self):
        self.assertEqual(len(fetch.chunk_dates(fetch.JOBS['fut-bbo-1s'], '2026-07-06', '2026-07-13')), 5)

    def test_no_options(self):
        # Options come from ThetaData; Databento is futures plus equity bars only.
        for j in fetch.JOBS.values():
            self.assertNotEqual(j.dataset, 'OPRA.PILLAR')
            if j.dataset == fetch.DATASET:
                self.assertIn(j.symbols, ('outrights', 'continuous'))
            else:
                self.assertEqual((j.dataset, j.symbols, j.schema), ('XNAS.ITCH', 'raw', 'ohlcv-1m'))

    def test_equity_request(self):
        job = fetch.JOBS['eq-ohlcv-1m']
        c = fetch.Chunk('eq-ohlcv-1m', 'QQQ', '2022-01-01', '2022-02-01', fetch.candidate_symbols(job, 'QQQ'))
        q = fetch.request(job, c)
        self.assertEqual((q['dataset'], q['symbols'], q['stype_in']), ('XNAS.ITCH', ['QQQ'], 'raw_symbol'))

    def test_continuous_ohlcv_job(self):
        job = fetch.JOBS['fut-ohlcv-1m-cont']
        self.assertTrue(job.whole_window_only)  # explicit dates only
        c = fetch.Chunk('fut-ohlcv-1m-cont', 'NQ', '2016-01-01', '2016-02-01', fetch.candidate_symbols(job, 'NQ'))
        q = fetch.request(job, c)
        self.assertEqual((q['dataset'], q['schema'], q['symbols'], q['stype_in']),
                         ('GLBX.MDP3', 'ohlcv-1m', ['NQ.v.0'], 'continuous'))
        self.assertEqual((q['start'].isoformat(), q['end'].isoformat()),
                         ('2016-01-01T00:00:00+00:00', '2016-02-01T00:00:00+00:00'))
        self.assertEqual(len(fetch.chunk_dates(job, '2016-01-01', '2022-01-01')), 72)

    def test_macro_continuous_products(self):
        job = fetch.JOBS['fut-ohlcv-1m-cont']
        for product in ('ZN', 'GC', '6E'):
            self.assertIn(product, job.opt_in)
            self.assertEqual(fetch.candidate_symbols(job, product), [f'{product}.v.0'])
        # Macro products are billed only when named: the default run stays ES/NQ.
        self.assertEqual(fetch.selected_products(job, None), ['ES', 'NQ'])
        self.assertEqual(fetch.selected_products(job, 'zn,gc'), ['ZN', 'GC'])
        self.assertEqual(fetch.selected_products(job, 'NQ'), ['NQ'])
        self.assertEqual(fetch.JOBS['fut-ohlcv-1m'].products, ('ES', 'NQ'))  # outrights job unchanged

    def test_dst(self):
        job = fetch.JOBS['fut-bbo-1s']
        self.assertEqual(fetch.request_span(job, '2026-03-06', '2026-03-07')[0].hour, 14)
        self.assertEqual(fetch.request_span(job, '2026-03-09', '2026-03-10')[0].hour, 13)

    def test_es_trades_mirrors_nq_trades(self):
        es, nq = fetch.JOBS['es-trades'], fetch.JOBS['nq-trades']
        self.assertEqual(es.products, ('ES',))
        self.assertEqual(replace(es, products=nq.products), nq)
        lo, hi = fetch.request_span(es, '2026-07-06', '2026-07-07')
        self.assertEqual((lo.isoformat(), hi.isoformat()), ('2026-07-06T13:25:00+00:00', '2026-07-06T20:00:00+00:00'))

    def test_interrupted_request_cannot_spend_twice(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, 'OUT_ROOT', Path(tmp)):
            c = fetch.Chunk('fut-bbo-1s', 'NQ', '2026-07-06', '2026-07-07', ['NQ.v.0'])
            client = Mock()
            client.timeseries.get_range.side_effect = RuntimeError('interrupted')
            with self.assertRaises(RuntimeError):
                fetch.download(client, fetch.JOBS['fut-bbo-1s'], c)
            with self.assertRaises(FileExistsError):
                fetch.download(client, fetch.JOBS['fut-bbo-1s'], c)
            self.assertEqual(client.timeseries.get_range.call_count, 1)

    def test_total_cap_blocks_all_downloads(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, 'OUT_ROOT', Path(tmp)), \
             patch.object(fetch, 'load_dotenv'), patch.object(fetch.db, 'Historical') as factory, \
             patch.object(fetch, 'download') as paid, patch('sys.stdout', Mock()), \
             patch('sys.argv', ['fetch', 'fut-bbo-1s', '--start', '2026-07-06', '--end', '2026-07-07',
                                '--download', '--max-cost', '0.01']):
            factory.return_value.metadata.get_cost.return_value = 1.0
            factory.return_value.metadata.get_billable_size.return_value = 100
            self.assertEqual(fetch.main(), 3)
            paid.assert_not_called()

    def test_updated_quote_blocks_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch, 'OUT_ROOT', Path(tmp)), \
             patch.object(fetch, 'load_dotenv'), patch.object(fetch.db, 'Historical') as factory, \
             patch.object(fetch, 'download') as paid, patch('sys.stdout', Mock()), \
             patch('sys.argv', ['fetch', 'fut-bbo-1s', '--products', 'NQ', '--start', '2026-07-06',
                                '--end', '2026-07-07', '--download', '--max-cost', '1']):
            factory.return_value.metadata.get_cost.side_effect = [0.5, 2.0]
            factory.return_value.metadata.get_billable_size.return_value = 100
            self.assertEqual(fetch.main(), 3)
            paid.assert_not_called()

    def test_month_chunks_are_clipped(self):
        self.assertEqual(fetch.chunk_dates(fetch.JOBS['fut-ohlcv-1m'], '2026-04-24', '2026-06-02'),
                         [('2026-04-24', '2026-05-01'), ('2026-05-01', '2026-06-01'), ('2026-06-01', '2026-06-02')])


if __name__ == '__main__':
    unittest.main()
