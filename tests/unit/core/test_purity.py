from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import wisselweer.core as core
from wisselweer.core.messages import DEFAULT_NL

CORE_DIR = Path(core.__file__).parent
FORBIDDEN = {
    "fastapi",
    "sqlalchemy",
    "httpx",
    "requests",
    "starlette",
    "sqlite3",
    "urllib",
    "socket",
}
ALLOWED_THIRD_PARTY = {"pydantic"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_core_sources_import_only_stdlib_and_pydantic():
    for f in CORE_DIR.glob("*.py"):
        mods = _imports(f)
        assert not (mods & FORBIDDEN), (f.name, mods & FORBIDDEN)
        third = {m for m in mods if m not in sys.stdlib_module_names and m != "wisselweer"}
        assert third <= ALLOWED_THIRD_PARTY, (f.name, third)


def test_importing_core_does_not_load_web_or_db_libs():
    code = (
        "import sys, wisselweer.core\n"
        "bad = {'fastapi','sqlalchemy','httpx'} & set(sys.modules)\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-I", "-c", code], check=True)


def test_every_i18n_key_used_in_core_has_dutch_default():
    import re

    pattern = re.compile(r'"((?:reason|uncertainty|warning)\.[a-z_.]+)"')
    used: set[str] = set()
    for f in CORE_DIR.glob("*.py"):
        if f.name == "messages.py":
            continue
        used |= set(pattern.findall(f.read_text()))
    # summer_tires-varianten worden samengesteld: suffix + basis
    for base in ("warning.frost", "warning.snow", "warning.icy"):
        used.add(base + ".summer_tires")
    missing = used - set(DEFAULT_NL)
    assert not missing, missing
