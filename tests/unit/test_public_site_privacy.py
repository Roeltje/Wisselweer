"""Privacyverklaring op de publieke site: geen persoonsgegevens in de repo."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "public-site"


def test_contact_js_has_no_hardcoded_email_or_host() -> None:
    src = (SITE / "contact.js").read_text(encoding="utf-8")
    assert not re.search(r"https?://", src)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", src)


def test_contact_json_is_gitignored() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "public-site/contact.json" in ignore
    assert not (SITE / "contact.json").exists() or _ignored("public-site/contact.json")


def test_privacy_page_is_linked_and_clean() -> None:
    page = (SITE / "privacy.html").read_text(encoding="utf-8")
    assert 'href="privacy.html"' in (SITE / "index.html").read_text(encoding="utf-8")
    assert "privacy.html" in (SITE / "404.html").read_text(encoding="utf-8")
    assert "privacy.html" in (SITE / "sitemap.xml").read_text(encoding="utf-8")
    assert 'id="privacy-contact"' in page
    assert "@" not in page
    assert not re.search(r"<script(?![^>]*\bsrc=)", page)
    assert not re.search(r"\sstyle=", page)


def _ignored(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0
