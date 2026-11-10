"""Güvenlik duvarı kontrolü: Linux'ta atlanır, Windows'ta netsh çıkış koduna bakılır."""

import subprocess

import pytest

from instructor_app import firewall


def test_skipped_when_not_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firewall, "is_windows", lambda: False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("netsh çağrılmamalı"))
    assert firewall.missing_rules() == []
    assert firewall.add_rules_elevated(firewall.RULES) is False


def test_add_rule_command_has_ports() -> None:
    commands = [firewall.add_rule_command(rule) for rule in firewall.RULES]
    assert 'name="LabSinav WebSocket"' in commands[0]
    assert "protocol=TCP localport=8765" in commands[0]
    assert "protocol=UDP localport=50555" in commands[1]


def test_missing_rules_uses_netsh_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firewall, "is_windows", lambda: True)
    asked: list[str] = []

    def fake_run(command, **kwargs):
        asked.append(command[-1])
        found = command[-1] == "name=LabSinav WebSocket"  # sadece TCP kuralı var
        return subprocess.CompletedProcess(command, 0 if found else 1)

    monkeypatch.setattr(firewall.subprocess, "run", fake_run)
    assert firewall.missing_rules() == [firewall.RULES[1]]
    assert asked == ["name=LabSinav WebSocket", "name=LabSinav Kesif"]


def test_netsh_failure_does_not_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(firewall, "is_windows", lambda: True)

    def broken_run(command, **kwargs):
        raise OSError("netsh yok")

    monkeypatch.setattr(firewall.subprocess, "run", broken_run)
    assert firewall.missing_rules() == []
