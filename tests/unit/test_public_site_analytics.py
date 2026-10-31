"""Analytics op de publieke site is opt-in: geen hard-coded host, geen config in git."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "public-site"


def test_analytics_js_has_no_hardcoded_host() -> None:
    src = (SITE / "analytics.js").read_text(encoding="utf-8")
    assert not re.search(r"https?://", src)


def test_analytics_json_is_not_committed() -> None:
    assert not (SITE / "analytics.json").exists() or _ignored("public-site/analytics.json")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "public-site/analytics.json" in ignore


def test_example_uses_placeholders_only() -> None:
    raw = (SITE / "analytics.example.json").read_text(encoding="utf-8")
    assert "example.org" in raw
    assert "00000000-0000-0000-0000-000000000000" in raw


def _ignored(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
