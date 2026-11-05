"""Offline checks that the export CLI refuses a public destination before it fetches or writes."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import export_backtest_data as exp
import publish_backtest_data as pub


class ExportGuardTests(unittest.TestCase):
    """PUBLIC_DIR points at a temp tree and build_symbol is mocked: nothing here touches the network or the repo."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.public = self.root / "frontend" / "public"
        self.public.mkdir(parents=True)
        self.export = self.root / "export"
        payload = {"bars": 2, "start": "s", "end": "e", "horizonMinutes": 15}
        self.build_symbol = self.patch(exp, "build_symbol", mock.Mock(return_value=payload))
        self.publish = self.patch(exp, "publish", mock.Mock())
        self.patch(exp, "PUBLIC_DIR", self.public)
        self.patch(pub, "PUBLIC_DIR", self.public)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)

    def patch(self, target, name: str, value):
        patcher = mock.patch.object(target, name, value)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def run_main(self, *argv) -> None:
        with mock.patch.object(sys, "argv", ["export_backtest_data.py", "--symbols", "QQQ", *map(str, argv)]):
            exp.main()

    def assert_refused(self, flag: str, *argv) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            self.run_main(*argv)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn(f"{flag}: real data must not be written under", stderr.getvalue())
        self.build_symbol.assert_not_called()
        self.publish.assert_not_called()
        self.assertEqual(list(self.public.iterdir()), [])
        self.assertFalse(self.export.exists(), "guard must fail before the output dir is created")

    def public_spellings(self) -> list:
        (self.root / "link").symlink_to(self.public)
        return [self.public / "backtest", "frontend/public/backtest", "frontend/public/../public/backtest",
                self.root / "link/backtest"]

    def test_publish_out_under_public_is_refused(self):
        for out in self.public_spellings():
            with self.subTest(out=out):
                self.assert_refused("--publish-out", "--out", self.export, "--publish-out", out)

    def test_out_under_public_is_refused(self):
        for out in self.public_spellings():
            with self.subTest(out=out):
                self.assert_refused("--out", "--out", out)

    def test_private_destinations_export_and_publish(self):
        catalog = self.root / "catalog"
        self.run_main("--out", self.export, "--publish-out", catalog)
        self.build_symbol.assert_called_once()
        self.publish.assert_called_once_with(self.export, catalog)
        self.assertEqual(json.loads((self.export / "index.json").read_text())["datasets"][0]["symbol"], "QQQ")

    def test_export_without_publish_out_skips_the_publisher(self):
        self.run_main("--out", self.export)
        self.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
