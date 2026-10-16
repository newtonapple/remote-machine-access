"""Tests for scripts/wake.py.

Run from the skill directory:
  uv run --with pytest --with typer --with pyyaml pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
import yaml
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import wake  # noqa: E402

runner = CliRunner()


def write_node(d: Path, name: str, **fields) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(yaml.safe_dump({"host": name, "hostname": name, **fields}))


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A directory with .remote-nodes/: a dual-boot machine (gpu-box + gpu-box-win) and a plain node."""
    nodes = tmp_path / ".remote-nodes"
    write_node(nodes, "gpu-box", lan_ip="192.168.1.50", mac="aa:bb:cc:dd:ee:ff", wol="tested")
    write_node(nodes, "gpu-box-win", lan_ip="192.168.1.50", wol_same_as="gpu-box")
    write_node(nodes, "nas", lan_ip="192.168.1.60")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wake, "on_link", lambda ip: True)
    return tmp_path


def test_load_nodes_merges_parent_and_cwd_with_cwd_winning(tmp_path, monkeypatch):
    write_node(tmp_path / ".remote-nodes", "a", description="parent")
    write_node(tmp_path / ".remote-nodes", "b")
    child = tmp_path / "child"
    write_node(child / ".remote-nodes", "a", description="child")
    monkeypatch.chdir(child)
    nodes = wake.load_nodes()
    assert set(nodes) == {"a", "b"} and nodes["a"]["description"] == "child"


def test_machine_of_resolves_either_side_of_a_dual_boot_machine(repo):
    nodes = wake.load_nodes()
    assert wake.machine_of(nodes, "gpu-box-win") == ("gpu-box", ["gpu-box", "gpu-box-win"])
    assert wake.machine_of(nodes, "gpu-box") == ("gpu-box", ["gpu-box", "gpu-box-win"])


def test_machine_of_rejects_a_loop(tmp_path, monkeypatch):
    nodes = tmp_path / ".remote-nodes"
    write_node(nodes, "x", wol_same_as="y")
    write_node(nodes, "y", wol_same_as="x")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(typer.Exit):
        wake.machine_of(wake.load_nodes(), "x")


def test_default_broadcast_is_the_slash_24():
    assert wake.default_broadcast("192.168.1.50") == "192.168.1.255"


def test_list_shows_machines_with_a_mac_and_their_state(repo):
    out = runner.invoke(wake.app, ["list"])
    assert out.exit_code == 0
    assert "gpu-box" in out.output and "aa:bb:cc:dd:ee:ff" in out.output and "tested" in out.output
    assert "nas" not in out.output  # no MAC, so it is not a wake target


def test_wake_dry_run_prints_the_plan_and_sends_nothing(repo, monkeypatch):
    sent = []
    monkeypatch.setattr(wake, "send_magic_packet", lambda *a: sent.append(a))
    out = runner.invoke(wake.app, ["wake", "gpu-box-win", "--dry-run"])
    assert out.exit_code == 0 and "aa:bb:cc:dd:ee:ff" in out.output and "192.168.1.255" in out.output
    assert sent == []


def test_wake_refuses_a_node_without_a_mac(repo):
    assert runner.invoke(wake.app, ["wake", "nas", "--dry-run"]).exit_code == 2


def test_wake_refuses_wol_none_unless_forced(repo, monkeypatch):
    write_node(repo / ".remote-nodes", "gpu-box", lan_ip="192.168.1.50", mac="aa:bb:cc:dd:ee:ff", wol="none")
    assert runner.invoke(wake.app, ["wake", "gpu-box", "--dry-run"]).exit_code == 2
    assert runner.invoke(wake.app, ["wake", "gpu-box", "--dry-run", "--force"]).exit_code == 0


def test_wake_refuses_a_target_that_is_not_on_this_lan(repo, monkeypatch):
    monkeypatch.setattr(wake, "on_link", lambda ip: False)
    out = runner.invoke(wake.app, ["wake", "gpu-box", "--dry-run"])
    assert out.exit_code == 2 and "not on a LAN" in out.output


def test_wake_sends_nothing_when_the_machine_already_answers(repo, monkeypatch):
    sent = []
    monkeypatch.setattr(wake, "answers_ping", lambda ip: True)
    monkeypatch.setattr(wake, "send_magic_packet", lambda *a: sent.append(a))
    out = runner.invoke(wake.app, ["wake", "gpu-box"])
    assert out.exit_code == 0 and "already answers" in out.output and sent == []


def test_wake_counts_ssh_as_up_when_ping_is_blocked(repo, monkeypatch):
    """Windows drops ping by default: a booted machine only shows up over SSH."""
    sent = []
    monkeypatch.setattr(wake, "send_magic_packet", lambda *a: sent.append(a))
    monkeypatch.setattr(wake, "answers_ping", lambda ip: False)
    monkeypatch.setattr(wake, "ssh_answers", lambda cfg, t=8: cfg["host"] == "gpu-box-win")
    monkeypatch.setattr(wake.time, "sleep", lambda s: None)
    out = runner.invoke(wake.app, ["wake", "gpu-box", "--timeout", "30"])
    assert out.exit_code == 0 and len(sent) == 1
    assert "answers SSH on gpu-box-win" in out.output


def test_wake_reports_failure_when_nothing_answers(repo, monkeypatch):
    clock = iter(range(0, 10_000, 5))
    monkeypatch.setattr(wake.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(wake.time, "sleep", lambda s: None)
    monkeypatch.setattr(wake, "send_magic_packet", lambda *a: None)
    monkeypatch.setattr(wake, "answers_ping", lambda ip: False)
    monkeypatch.setattr(wake, "ssh_answers", lambda cfg, t=8: False)
    out = runner.invoke(wake.app, ["wake", "gpu-box", "--timeout", "20"])
    assert out.exit_code == 1 and "no answer" in out.output


def test_ssh_cmd_lan_keeps_the_alias_user_and_host_key(monkeypatch):
    monkeypatch.setattr(wake, "configured_hostname", lambda a: "gpu-box.example.net")
    cfg = {"host": "gpu-box", "hostname": "gpu-box", "user": "me", "lan_ip": "192.168.1.50"}
    plain, lan = wake.ssh_cmd(cfg, "echo ok"), wake.ssh_cmd(cfg, "echo ok", lan=True)
    assert "HostName=192.168.1.50" not in plain
    assert "HostName=192.168.1.50" in lan and "HostKeyAlias=gpu-box.example.net" in lan
    assert lan[-2:] == ["me@gpu-box", "echo ok"]


def test_ssh_answers_falls_back_to_lan_ip(monkeypatch):
    monkeypatch.setattr(wake, "configured_hostname", lambda a: a)
    seen = []

    def fake_run(cmd, **kw):
        lan = any(str(c).startswith("HostName=") for c in cmd)
        seen.append(lan)
        return SimpleNamespace(returncode=0 if lan else 255, stdout="ok\n" if lan else "")

    monkeypatch.setattr(wake.subprocess, "run", fake_run)
    assert wake.ssh_answers({"host": "h", "hostname": "h", "lan_ip": "192.168.1.50"}) is True
    assert seen == [False, True]
    seen.clear()
    assert wake.ssh_answers({"host": "h", "hostname": "h"}) is False  # no lan_ip, so no second try
    assert seen == [False]


def test_magic_packet_has_the_right_shape(monkeypatch):
    got = []

    class FakeSock:
        def setsockopt(self, *a): pass
        def sendto(self, data, addr): got.append((data, addr))

    monkeypatch.setattr(wake.shutil, "which", lambda name: None)
    monkeypatch.setattr(wake.socket, "socket", lambda *a: FakeSock())
    wake.send_magic_packet("aa:bb:cc:dd:ee:ff", "192.168.1.255")
    data, addr = got[0]
    assert data == b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16 and len(data) == 102
    assert [a for _, a in got] == [("192.168.1.255", 9), ("255.255.255.255", 9)]
