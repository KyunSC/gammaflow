"""Static check on strategy source: a strategy may compute, not read files, spawn processes or reach the evaluator.

It is one layer, not a jail: the child process plus this allowlist make "peek at future bars" require an obvious,
reviewable violation instead of an accidental one.
"""
from __future__ import annotations

import ast

ALLOWED_IMPORTS = {"math", "statistics", "collections", "dataclasses", "itertools", "functools",
                   "bisect", "heapq", "numpy", "__future__"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr",
                   "setattr", "delattr", "input", "breakpoint", "memoryview", "__builtins__"}
FORBIDDEN_ATTRS = {"load", "loads", "loadtxt", "fromfile", "genfromtxt", "memmap", "save", "savez", "savetxt",
                   "tofile", "read", "write", "system", "popen", "__dict__", "__class__", "__subclasses__",
                   "__globals__", "__builtins__", "__code__", "__import__", "f_back", "f_globals", "gi_frame",
                   "DataSource", "lib", "ctypeslib", "testing", "open", "eval", "exec", "compile", "__self__",
                   "__mro__", "__bases__", "__base__", "tb_frame", "f_locals", "f_code", "cr_frame", "ag_frame",
                   "__getattribute__", "__reduce__", "__reduce_ex__", "get_type_hints", "npyio", "format",
                   "f2py", "distutils", "fromregex", "frombuffer"}


class SandboxError(ValueError):
    pass


def check_source(src: str, name: str = "<strategy>") -> None:
    tree = ast.parse(src, name)
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS or any(x in FORBIDDEN_ATTRS for x in a.name.split(".")[1:]):
                    bad.append(f"import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                bad.append(f"from {'.' * node.level}{node.module} import")
            for part in (node.module or "").split(".")[1:]:
                if part in FORBIDDEN_ATTRS:
                    bad.append(f"from {node.module} import")
            for a in node.names:
                if a.name in FORBIDDEN_ATTRS or a.name in FORBIDDEN_NAMES or a.name == "*":
                    bad.append(f"from {node.module} import {a.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            bad.append("dunder string literal")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            bad.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            bad.append(f"attribute .{node.attr}")
    if not any(isinstance(n, ast.ClassDef) and n.name == "Strategy" for n in tree.body):
        bad.append("no top-level class Strategy")
    if bad:
        raise SandboxError(f"{name}: " + "; ".join(sorted(set(bad))))
