"""Batch-2 bootstrap: fresh evaluator copies in research_loop_free/b2/{es_daily,crypto} (plan, "More batches").

    cd functions/ml && ../../.venv/bin/python -B -m research_loop_free.bootstrap_b2

Same substitutions as bootstrap.py, one directory deeper: ML is LOOP_DIR.parent.parent.parent, crypto eval/__init__
parents[4], OUT_DIR / STATE under data/research_loop_free/b2/<name>. Input-data paths (UST, Binance raw) still point at
the source loops' frozen data. Refuses if a destination exists.
"""
from __future__ import annotations

import shutil

from . import bootstrap as B

FREE = B.ML / "research_loop_free" / "b2"
SRC = {"es_daily": B.SRC["es_daily"], "crypto": B.SRC["crypto"]}


def deeper(name: str) -> tuple[dict, list]:
    ed = {}
    for rel, pairs in B.EDITS[name].items():
        out = []
        for a, b in pairs:
            b = b.replace("LOOP_DIR.parent.parent\n", "LOOP_DIR.parent.parent.parent\n")
            b = b.replace("ML = LOOP.parent.parent                  # functions/ml",
                          "ML = LOOP.parent.parent.parent           # functions/ml")
            b = b.replace('"research_loop_free" / "es_daily"', '"research_loop_free" / "b2" / "es_daily"')
            b = b.replace("'research_loop_free' / 'crypto'", "'research_loop_free' / 'b2' / 'crypto'")
            b = b.replace("parents[3]", "parents[4]")
            out.append((a, b))
        ed[rel] = out
    ctrl = []
    for a, b in B.CTRL_EDITS[name]:
        b = b.replace("research_loop_free/es_daily", "research_loop_free/b2/es_daily")
        b = b.replace("research_loop_free.es_daily.", "research_loop_free.b2.es_daily.")
        b = b.replace("research_loop_free/crypto", "research_loop_free/b2/crypto")
        b = b.replace("HERE.parents[1]", "HERE.parents[2]")
        ctrl.append((a, b))
    return ed, ctrl


def main() -> None:
    FREE.mkdir(exist_ok=True)
    if not (FREE / "__init__.py").exists():
        (FREE / "__init__.py").write_text('"""Free-data loop, batch 2 evaluator copies."""\n')
    out = []
    for name, src in SRC.items():
        dst = FREE / name
        if (dst / "eval").exists():
            raise SystemExit(f"{dst}/eval exists: copies are written once")
        edits, ctrl = deeper(name)
        shutil.copytree(src / "eval", dst / "eval", ignore=shutil.ignore_patterns("__pycache__", "MANIFEST.sha256"))
        for rel, pairs in edits.items():
            p = dst / rel
            a = p.read_text()
            b = a
            for x, y in pairs:
                b = B.sub_once(b, x, y, f"b2/{name}/{rel}")
            p.chmod(0o644)
            p.write_text(b)
            out.append(B.diff(a, b, f"b2/{name}/{rel}"))
        for f in B.EXTRA[name]:
            shutil.copy2(src / f, dst / f)
        (dst / "tests").mkdir(exist_ok=True)
        for f in B.TESTS[name]:
            a = (src / "tests" / f).read_text()
            b = B.rename_tests(name, a).replace(f"research_loop_free.{name}.", f"research_loop_free.b2.{name}.") \
                .replace(f"research_loop_free/{name}/", f"research_loop_free/b2/{name}/")
            (dst / "tests" / f).write_text(b)
            if a != b:
                out.append(B.diff(a, b, f"b2/{name}/tests/{f}"))
        a = (src / "controller.py").read_text()
        b = a
        for x, y in ctrl:
            b = B.sub_once(b, x, y, f"b2/{name}/controller.py")
        (dst / "controller.py").write_text(b)
        out.append(B.diff(a, b, f"b2/{name}/controller.py"))
        for d in ("strategies", "prereg"):
            (dst / d).mkdir(exist_ok=True)
        if name == "crypto":
            shutil.copy2(src / "strategies" / "__init__.py", dst / "strategies" / "__init__.py")
        (B.ML / "data" / "research_loop_free" / "b2" / name).mkdir(parents=True, exist_ok=True)
    (B.ML / "data" / "research_loop_free" / "b2" / "bootstrap_diff.patch").write_text("".join(out))
    print("".join(out))


if __name__ == "__main__":
    main()
