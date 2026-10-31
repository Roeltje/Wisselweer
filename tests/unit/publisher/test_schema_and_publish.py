from __future__ import annotations

import json
import os
import subprocess
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.unit.publisher.helpers import COLD, NOW, uniform
from wisselweer.publisher.national import NationalAdviceService
from wisselweer.publisher.public_schema import PublicAdvice
from wisselweer.publisher.publish import (
    PublishError,
    build_sftp_command,
    publish_sftp,
    write_local,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def advice():
    return NationalAdviceService(uniform(COLD)).compute(NOW)


def test_extra_fields_forbidden(advice):
    data = advice.model_dump(mode="json")
    PublicAdvice.model_validate(data)
    with pytest.raises(ValidationError):
        PublicAdvice.model_validate(data | {"vehicle": "x"})
    with pytest.raises(ValidationError):
        PublicAdvice.model_validate(data | {"source": data["source"] | {"extra": 1}})
    with pytest.raises(ValidationError):
        PublicAdvice.model_validate(
            data | {"regions": [{"name": "A", "status": "KEEP_CURRENT", "x": 1}]}
        )
    with pytest.raises(ValidationError):
        PublicAdvice.model_validate(data | {"status": "NOPE"})
    with pytest.raises(ValidationError):
        PublicAdvice.model_validate(data | {"generated_at": "2026-11-10T08:00:00"})  # naïef


def test_frozen(advice):
    with pytest.raises(ValidationError):
        advice.status = "KEEP_CURRENT"


def test_example_site_file_validates():
    raw = (ROOT / "public-site" / "advice.json").read_text(encoding="utf-8")
    PublicAdvice.model_validate_json(raw)


def test_write_local_atomic(advice, tmp_path):
    target = write_local(advice, tmp_path)
    assert target == tmp_path / "advice.json"
    assert not (tmp_path / "advice.json.tmp").exists()
    assert oct(target.stat().st_mode & 0o777) == "0o644"
    assert PublicAdvice.model_validate_json(target.read_text()) == advice
    assert json.loads(target.read_text())["generated_at"].endswith("Z")


def test_write_local_requires_existing_dir(advice, tmp_path):
    with pytest.raises(PublishError):
        write_local(advice, tmp_path / "nope")


def test_invalid_data_keeps_existing_file(advice, tmp_path):
    target = write_local(advice, tmp_path)
    before = target.read_bytes()
    bad = PublicAdvice.model_construct(**{**dict(advice), "status": "KAPOT"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(PublishError):
            write_local(bad, tmp_path)
    assert target.read_bytes() == before
    assert not (tmp_path / "advice.json.tmp").exists()
    assert os.listdir(tmp_path) == ["advice.json"]


class _Run:
    def __init__(self, rc=0):
        self.calls = []
        self.rc = rc

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.rc, "", "secret stderr")


def test_sftp_command_without_shell(monkeypatch, tmp_path):
    run = _Run()
    monkeypatch.setattr(subprocess, "run", run)
    f = tmp_path / "advice.json"
    f.write_text("{}")
    publish_sftp(
        f, "example.org", "deploy", Path("/k/id"), "/public/", port=2222, known_hosts=Path("/k/kh")
    )
    ((cmd, kw),) = run.calls
    assert isinstance(cmd, list) and not kw.get("shell")
    assert cmd[0] == "sftp" and cmd[-1] == "deploy@example.org"
    assert ["-b", "-"] == cmd[1:3] and "BatchMode=yes" in cmd and "StrictHostKeyChecking=yes" in cmd
    assert cmd[cmd.index("-i") + 1] == "/k/id" and cmd[cmd.index("-P") + 1] == "2222"
    assert "UserKnownHostsFile=/k/kh" in cmd
    assert kw["timeout"] > 0
    assert kw["input"].splitlines() == [
        f'put "{f}" "/public/advice.json.tmp"',
        'rename "/public/advice.json.tmp" "/public/advice.json"',
    ]


@pytest.mark.parametrize(
    "kw",
    [
        {"host": "evil.org; rm -rf /"},
        {"host": "-oProxyCommand=x"},
        {"host": "a b"},
        {"user": "x@y"},
        {"user": "-bad"},
        {"remote_dir": "/a/../b"},
        {"remote_dir": '/a" ; put x'},
        {"remote_dir": "/a b"},
        {"port": 0},
    ],
)
def test_sftp_rejects_odd_arguments(monkeypatch, tmp_path, kw):
    run = _Run()
    monkeypatch.setattr(subprocess, "run", run)
    args = {"host": "example.org", "user": "deploy", "remote_dir": "/p", "port": 22} | kw
    with pytest.raises(PublishError):
        publish_sftp(
            tmp_path / "advice.json",
            args["host"],
            args["user"],
            Path("/k"),
            args["remote_dir"],
            port=args["port"],
        )
    assert run.calls == []


def test_sftp_failure_and_timeout_hide_details(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _Run(rc=255))
    with pytest.raises(PublishError) as ei:
        publish_sftp(tmp_path / "a.json", "example.org", "deploy", Path("/k/secret-key"), "/p")
    assert "secret" not in str(ei.value)

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(PublishError, match="time-out"):
        publish_sftp(tmp_path / "a.json", "example.org", "deploy", Path("/k"), "/p")


def test_build_command_default_known_hosts():
    cmd = build_sftp_command(Path("/k"), "h.example", "u")
    assert not any(a.startswith("UserKnownHostsFile") for a in cmd)
