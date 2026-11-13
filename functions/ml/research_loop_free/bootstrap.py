"""One-time bootstrap of the free-data ideas loop (plan: ~/.claude/plans/free-data-ideas-loop.md, rule 1).

    cd functions/ml && ../../.venv/bin/python -B -m research_loop_free.bootstrap

Copies three evaluator directories verbatim, then applies ONLY the substitutions listed in EDITS (each must match
exactly once). Rule 1 allows OUT_DIR and SEED; the other edits are forced by the copy sitting one directory deeper
(research_loop_free/<name>/eval instead of research_loop_<x>/eval), so the derived functions/ml root and the input-data
directories that the source derived from its OUT_DIR keep pointing at the same files. No cost, criterion, split, twin or
limit is touched. Controllers, tests and hashed helper files are copied with the edits in CTRL_EDITS / test renames.
Refuses to run if a destination already exists (the copies are written once, then frozen).
"""
from __future__ import annotations

import difflib
import re
import shutil
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
FREE = ML / "research_loop_free"

SRC = {"es_intraday": ML / "research_loop", "es_daily": ML / "research_loop_daily", "crypto": ML / "research_loop_crypto"}

EDITS = {
    "es_intraday": {"eval/config.py": [
        ("ML = LOOP_DIR.parent\n", "ML = LOOP_DIR.parent.parent\n"),
        ('OUT_DIR = ML / "data" / "research_loop"\n', 'OUT_DIR = ML / "data" / "research_loop_free" / "es_intraday"\n'),
        ("SEED = 20261102\n", "SEED = 20261105\n"),
    ]},
    "es_daily": {"eval/config.py": [
        ("ML = LOOP_DIR.parent\n", "ML = LOOP_DIR.parent.parent\n"),
        ('OUT_DIR = ML / "data" / "research_loop_daily"\n', 'OUT_DIR = ML / "data" / "research_loop_free" / "es_daily"\n'),
        ('UST_DIR = OUT_DIR / "treasury"', 'UST_DIR = ML / "data" / "research_loop_daily" / "treasury"'),
        ("SEED = 20261102\n", "SEED = 20261105\n"),
    ]},
    "crypto": {
        "eval/config.py": [
            ("ML = LOOP.parent                         # functions/ml\n",
             "ML = LOOP.parent.parent                  # functions/ml\n"),
            ("STATE = ML / 'data' / 'research_loop_crypto'\n", "STATE = ML / 'data' / 'research_loop_free' / 'crypto'\n"),
            ("RAW = STATE / 'raw'\n", "RAW = ML / 'data' / 'research_loop_crypto' / 'raw'\n"),
            ("SEED = 7\n", "SEED = 20261105\n"),
        ],
        "eval/__init__.py": [("parents[2]", "parents[3]")],
    },
}

# Not frozen (as in the source loops) but sha-pinned in state.json. Each controller mirrors every ledger row into the
# shared research_loop/ledger.jsonl (rule 3) through research_loop_free.shared.
MIRROR_ES = '''

_append_local = append_row


def append_row(row: dict) -> None:
    """Local ledger (budget) first, then the shared research_loop/ledger.jsonl mirror (plan rule 3)."""
    _append_local(row)
    from research_loop_free.shared import mirror_run
    mirror_run(row, LOOP_NAME)
'''
MIRROR_CRYPTO = '''

_append_local = append_row


def append_row(row: dict, path: Path | None = None) -> None:
    """Local ledger (budget) first, then the shared research_loop/ledger.jsonl mirror (plan rule 3)."""
    _append_local(row, path)
    if path is None:
        from research_loop_free.shared import mirror_run
        mirror_run(row, LOOP_NAME)
'''
CTRL_EDITS = {
    "es_intraday": [
        ('SPEND = LOOP / "data_spend_ledger.json"\n',
         'SPEND = C.ML / "research_loop" / "data_spend_ledger.json"   # shared with the other research loops\n'
         'LOOP_NAME = "research_loop_free/es_intraday"\n'),
        ("        os.fsync(f.fileno())\n\n\ndef verify_eval", "        os.fsync(f.fileno())\n" + MIRROR_ES + "\n\ndef verify_eval"),
        ("-m research_loop.controller", "-m research_loop_free.es_intraday.controller"),
    ],
    "es_daily": [
        ('SHARED_LOCK = C.ML / "research_loop" / ".shared.lock"\n',
         'SHARED_LOCK = C.ML / "research_loop" / ".shared.lock"\nLOOP_NAME = "research_loop_free/es_daily"\n'),
        ("        os.fsync(f.fileno())\n\n\ndef _atomic_write", "        os.fsync(f.fileno())\n" + MIRROR_ES + "\n\ndef _atomic_write"),
        ("-m research_loop_daily.controller", "-m research_loop_free.es_daily.controller"),
    ],
    "crypto": [
        ("SPEND = C.ML / 'research_loop' / 'data_spend_ledger.json'\n",
         "SPEND = C.ML / 'research_loop' / 'data_spend_ledger.json'\nLOOP_NAME = 'research_loop_free/crypto'\n"),
        ("        os.fsync(f.fileno())\n\n\ndef verify_eval", "        os.fsync(f.fileno())\n" + MIRROR_CRYPTO + "\n\ndef verify_eval"),
        ("if str(HERE) not in sys.path:\n    sys.path.insert(0, str(HERE))\n",
         "if str(HERE) not in sys.path:\n    sys.path.insert(0, str(HERE))\nif str(HERE.parents[1]) not in sys.path:\n"
         "    sys.path.append(str(HERE.parents[1]))   # functions/ml, for research_loop_free.shared\n"),
        ("crypto perp loop: controller sanity", "free-data loop (research_loop_free/crypto): controller sanity"),
        ("research_loop_crypto/controller.py", "research_loop_free/crypto/controller.py"),
    ],
}

# Extra files the source manifests hash at LOOP_DIR (copied verbatim, never run here).
EXTRA = {"es_intraday": ["__init__.py"], "es_daily": ["__init__.py", "build_ust.py"], "crypto": ["fetch_free.py"]}
TESTS = {"es_intraday": ["__init__.py", "test_eval.py"], "es_daily": ["__init__.py", "test_eval.py"],
         "crypto": ["test_eval.py", "test_engine_legacy.py", "test_fetch_free.py"]}


def rename_tests(name: str, text: str) -> str:
    """Point the copied tests at the copy (module and repo paths), never at data paths (data/research_loop_*)."""
    old = SRC[name].name
    new = f"research_loop_free/{name}"
    text = re.sub(rf"(?<![\w/]){old}\.", f"research_loop_free.{name}.", text)
    return re.sub(rf"(?<![\w/]){old}/", f"{new}/", text)


def sub_once(text: str, a: str, b: str, where: str) -> str:
    n = text.count(a)
    if n < 1 or (n > 1 and not (a.startswith("-m ") or a.endswith("controller.py"))):
        raise SystemExit(f"{where}: expected one match of {a!r}, found {n}")
    return text.replace(a, b)


def diff(a: str, b: str, path: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), f"source/{path}", f"copy/{path}", n=0))


def main() -> None:
    FREE.mkdir(exist_ok=True)
    (FREE / "__init__.py").write_text('"""Free-data ideas loop (research_loop_free). Not frozen; the evaluators under */eval are."""\n') \
        if not (FREE / "__init__.py").exists() else None
    out = []
    for name, src in SRC.items():
        dst = FREE / name
        if (dst / "eval").exists():
            raise SystemExit(f"{dst}/eval exists: copies are written once")
        shutil.copytree(src / "eval", dst / "eval", ignore=shutil.ignore_patterns("__pycache__", "MANIFEST.sha256"))
        for rel, edits in EDITS[name].items():
            p = dst / rel
            a = p.read_text()
            b = a
            for x, y in edits:
                b = sub_once(b, x, y, f"{name}/{rel}")
            p.chmod(0o644)
            p.write_text(b)
            out.append(diff(a, b, f"{name}/{rel}"))
        for f in EXTRA[name]:
            shutil.copy2(src / f, dst / f)
        (dst / "tests").mkdir(exist_ok=True)
        for f in TESTS[name]:
            a = (src / "tests" / f).read_text()
            b = rename_tests(name, a)
            (dst / "tests" / f).write_text(b)
            if a != b:
                out.append(diff(a, b, f"{name}/tests/{f}"))
        a = (src / "controller.py").read_text()
        b = a
        for x, y in CTRL_EDITS[name]:
            b = sub_once(b, x, y, f"{name}/controller.py")
        (dst / "controller.py").write_text(b)
        out.append(diff(a, b, f"{name}/controller.py"))
        for d in ("strategies", "prereg"):
            (dst / d).mkdir(exist_ok=True)
        if name == "crypto":
            shutil.copy2(src / "strategies" / "__init__.py", dst / "strategies" / "__init__.py")
        (ML / "data" / "research_loop_free" / name).mkdir(parents=True, exist_ok=True)
    (ML / "data" / "research_loop_free" / "bootstrap_diff.patch").write_text("".join(out))
    print("".join(out))


if __name__ == "__main__":
    main()
