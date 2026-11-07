"""Offline checks that publish() keeps real data off the public site and the synthetic sample out of the catalog."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import publish_backtest_data as pub

REPO = Path(__file__).resolve().parents[2]
BAR_TIMES = [1767623400, 1767623700]  # 2026-01-05 14:30, 14:35 UTC


def dataset(symbol: str = "QQQ", **extra) -> dict:
    return {
        "symbol": symbol, "interval": "5m", "bars": 2, "generatedAt": "2026-01-06T00:00:00+00:00",
        "start": "2026-01-05T14:30:00+00:00", "end": "2026-01-05T14:35:00+00:00",
        "time": BAR_TIMES, "open": [100.0, 101.0], "high": [101.5, 102.0], "low": [99.5, 100.5],
        "close": [101.0, 101.5], "volume": [1000, 1200], **extra,
    }


def write_export(folder: Path, datasets: dict, **index_flags) -> None:
    """datasets: filename -> (dataset dict, flags copied onto its index.json entry)."""
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, (data, entry_flags) in datasets.items():
        (folder / name).write_text(json.dumps(data))
        entries.append({"symbol": data["symbol"], "file": name, **entry_flags})
    (folder / "index.json").write_text(json.dumps({"datasets": entries, **index_flags}))


class SandboxedPublicDir(unittest.TestCase):
    """Points PUBLIC_DIR at a temp tree, so a broken guard can never touch frontend/public."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.public = self.root / "frontend" / "public"
        self.public.mkdir(parents=True)
        patcher = mock.patch.object(pub, "PUBLIC_DIR", self.public)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)


class IsPublicPathTests(SandboxedPublicDir):
    def test_flags_every_spelling_of_the_public_folder(self):
        (self.root / "link").symlink_to(self.public)
        (self.root / "dangling").symlink_to(self.public / "new")  # target does not exist yet
        os.chdir(self.root / "frontend")
        for path in (self.public, self.public / "backtest",
                     "public", "public/backtest", "../frontend/public/backtest",
                     "public/../public/backtest", self.root / "frontend/lab/../public/backtest",
                     self.root / "link", self.root / "link/backtest",
                     self.root / "dangling"):
            with self.subTest(path=path):
                self.assertTrue(pub.is_public_path(path))

    def test_flags_a_symlink_chain_and_a_symlinked_parent(self):
        (self.root / "hop").symlink_to(self.root / "frontend")
        (self.root / "hop2").symlink_to(self.root / "hop")
        self.assertTrue(pub.is_public_path(self.root / "hop2/public/backtest"))

    def test_flags_a_public_dir_that_is_itself_a_symlink(self):
        real = self.root / "assets"
        real.mkdir()
        self.public.rmdir()
        self.public.symlink_to(real)
        self.assertTrue(pub.is_public_path(real / "backtest"))

    def test_flags_a_case_variant_on_a_case_insensitive_disk(self):
        variant = self.public.with_name("PUBLIC")
        if not variant.exists():
            self.skipTest("case-sensitive filesystem")
        self.assertTrue(pub.is_public_path(variant))
        self.assertTrue(pub.is_public_path(variant / "backtest/new"))

    def test_leaves_everything_else_alone(self):
        (self.root / "elsewhere").mkdir()
        (self.root / "away").symlink_to(self.root / "elsewhere")
        for path in (self.root / "frontend", self.root / "frontend/public-notes",
                     self.root / "frontend/public/../lab/data", self.root / "away/backtest", "elsewhere"):
            with self.subTest(path=path):
                self.assertFalse(pub.is_public_path(path))

    def test_works_when_the_public_folder_does_not_exist(self):
        self.public.rmdir()
        self.assertTrue(pub.is_public_path(self.public / "backtest"))
        self.assertFalse(pub.is_public_path(self.root / "elsewhere"))


class PublishDestinationTests(SandboxedPublicDir):
    def setUp(self):
        super().setUp()
        self.source = self.root / "export"
        write_export(self.source, {"qqq_5m.json": (dataset(), {})})

    def test_refuses_a_public_destination_and_writes_nothing(self):
        (self.root / "link").symlink_to(self.public)
        for out in (self.public / "backtest", "frontend/public/backtest",
                    "frontend/public/../public/backtest", self.root / "link/backtest"):
            with self.subTest(out=out):
                with self.assertRaisesRegex(ValueError, "public site"):
                    pub.publish(self.source, out)
                self.assertEqual(list(self.public.iterdir()), [])

    def test_destination_is_checked_before_the_source_is_read(self):
        with self.assertRaisesRegex(ValueError, "public site"):
            pub.publish(self.root / "missing", self.public)

    def test_publishes_real_data_elsewhere(self):
        out = self.root / "catalog"
        catalog = pub.publish(self.source, out)
        self.assertEqual([d["symbol"] for d in catalog["datasets"]], ["QQQ"])
        self.assertTrue((out / f"{catalog['datasets'][0]['id']}.json").exists())
        self.assertTrue((out / "index.json").exists())


class PublishSyntheticTests(SandboxedPublicDir):
    def setUp(self):
        super().setUp()
        self.source = self.root / "export"
        self.out = self.root / "catalog"

    def assert_refused(self):
        with self.assertRaisesRegex(ValueError, "synthetic"):
            pub.publish(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_refuses_the_index_flag(self):
        write_export(self.source, {"qqq_5m.json": (dataset(), {})}, synthetic=True)
        self.assert_refused()

    def test_refuses_the_index_entry_flag(self):
        write_export(self.source, {"qqq_5m.json": (dataset(), {"synthetic": True})})
        self.assert_refused()

    def test_refuses_the_dataset_flag(self):
        write_export(self.source, {"qqq_5m.json": (dataset(synthetic=True), {})})
        self.assert_refused()

    def test_one_synthetic_dataset_blocks_the_whole_publish(self):
        write_export(self.source, {"qqq_5m.json": (dataset(), {}), "spy_5m.json": (dataset("SPY", synthetic=True), {})})
        self.assert_refused()

    def test_refuses_over_an_existing_catalog_without_touching_it(self):
        write_export(self.source, {"qqq_5m.json": (dataset(), {})})
        catalog = pub.publish(self.source, self.out)
        before = sorted((p.name, p.read_bytes()) for p in self.out.iterdir())
        write_export(self.source, {"spy_5m.json": (dataset("SPY", synthetic=True), {})})
        with self.assertRaisesRegex(ValueError, "synthetic"):
            pub.publish(self.source, self.out)
        self.assertEqual(before, sorted((p.name, p.read_bytes()) for p in self.out.iterdir()))
        self.assertEqual(len(catalog["datasets"]), 1)

    def test_explicit_false_is_not_a_refusal(self):
        write_export(self.source, {"qqq_5m.json": (dataset(synthetic=False), {"synthetic": False})}, synthetic=False)
        self.assertEqual(len(pub.publish(self.source, self.out)["datasets"]), 1)


class BundledSampleTests(unittest.TestCase):
    def test_public_dir_is_the_folder_the_site_serves(self):
        self.assertTrue((pub.PUBLIC_DIR / "backtest" / "index.json").exists())
        self.assertTrue(pub.is_public_path(REPO / "frontend/public/backtest"))

    def test_the_bundled_sample_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "catalog"
            with self.assertRaisesRegex(ValueError, "synthetic"):
                pub.publish(REPO / "frontend/public/backtest", out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
