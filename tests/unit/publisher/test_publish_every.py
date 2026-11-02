"""`wisselweer publish --every-hours N`: periodieke lus voor de publisher-container."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from wisselweer import cli
from wisselweer.publisher import scheduler


@pytest.mark.parametrize("waarde", ["0", "-1", "veel", "inf", "nan"])
def test_ongeldige_waarde_wordt_geweigerd(waarde, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["publish", "--every-hours", waarde])
    assert exc.value.code == 2
    assert "--every-hours" in capsys.readouterr().err


def test_zonder_optie_publiceert_een_keer(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_publish", lambda: calls.append(1) or 0)
    monkeypatch.setattr(cli, "_publish_every", lambda h: pytest.fail("lus mag niet starten"))
    assert cli.main(["publish"]) == 0
    assert calls == [1]


def test_lus_publiceert_herhaald_overleeft_fouten_en_stopt_op_sigterm(monkeypatch, capsys):
    calls: list[int] = []

    def fake_publish() -> int:
        calls.append(1)
        if len(calls) == 3:
            os.kill(os.getpid(), signal.SIGTERM)  # echt signaal: test ook de handler
        return 1 if len(calls) == 1 else 0  # een mislukte run stopt de lus niet

    monkeypatch.setattr(scheduler, "FIRST_RUN_DELAY_S", 0.0)
    monkeypatch.setattr(cli, "_publish", fake_publish)
    vorige = signal.getsignal(signal.SIGTERM)

    assert cli.main(["publish", "--every-hours", "0.00001"]) == 0  # ~36 ms tussen de runs

    assert len(calls) == 3
    assert signal.getsignal(signal.SIGTERM) is vorige  # handlers hersteld
    out = capsys.readouterr().out
    assert "gestart" in out and "gestopt" in out


def test_eerste_run_wacht_de_vertraging_af(monkeypatch):
    waits: list[float] = []

    class FakeEvent:
        def wait(self, timeout: float) -> bool:
            waits.append(timeout)
            return len(waits) > 2  # twee rondes, dan stoppen

    monkeypatch.setattr(cli.threading, "Event", FakeEvent)
    monkeypatch.setattr(cli, "_publish", lambda: 0)
    assert cli._publish_every(6) == 0
    assert waits == [scheduler.FIRST_RUN_DELAY_S, 6 * 3600.0, 6 * 3600.0]


def test_proces_stopt_snel_en_netjes_op_sigterm(tmp_path):
    """Echt proces: `docker compose stop` stuurt SIGTERM en mag niet 10 s hangen."""
    env = {
        **os.environ,
        "WISSELWEER_DATA_DIR": str(tmp_path / "data"),
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(  # noqa: S603 - vaste interpreter en module
        [sys.executable, "-m", "wisselweer.cli", "publish", "--every-hours", "6"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        assert "Publicatielus gestart" in proc.stdout.readline()  # handlers staan er nu
        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=5) == 0
        assert time.monotonic() - start < 5
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            if pipe:
                pipe.close()
