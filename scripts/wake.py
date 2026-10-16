#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["typer", "pyyaml"]
# ///
"""Wake machines on your LAN with Wake-on-LAN, using the node files in .remote-nodes/.

Run it with uv (the dependencies are declared above) from the directory that holds
`.remote-nodes/`:

  uv run scripts/wake.py list
  uv run scripts/wake.py wake gpu-box
  uv run scripts/wake.py wake gpu-box --dry-run

A magic packet is a layer 2 broadcast, so the computer running this script must be on the same
LAN as the machine it wakes. The script checks the routing table and refuses a send that cannot
reach the target, instead of reporting a wake that never happened.

Node-file fields (flat YAML, see SKILL.md):
  mac            NIC MAC address, quoted
  lan_ip         the machine's address on its LAN (used to find the broadcast address and to ping)
  wol            tested | untested | none (default untested)
  wol_broadcast  broadcast address (default: lan_ip with the last octet set to 255, a /24)
  wol_same_as    on one OS side of a dual-boot machine: the node file that carries mac and wol

Requirements: Python 3.10 or newer, typer and PyYAML (uv installs both from the header above),
`ping` and `ssh` on the PATH (used to wait for the machine). The `wakeonlan` command is optional:
it is used when found, otherwise the script sends the packet with Python's socket module.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer
import yaml

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)

MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


def load_nodes() -> dict[str, dict]:
    """Merge ./.remote-nodes and ../.remote-nodes (the closer one wins), keyed by host."""
    nodes: dict[str, dict] = {}
    cwd = Path.cwd()
    for d in (cwd.parent / ".remote-nodes", cwd / ".remote-nodes"):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.y*ml")):
            try:
                cfg = yaml.safe_load(f.read_text())
            except yaml.YAMLError:
                continue
            if isinstance(cfg, dict) and cfg.get("host"):
                nodes[str(cfg["host"])] = cfg
    return nodes


def machine_of(nodes: dict[str, dict], name: str) -> tuple[str, list[str]]:
    """Follow wol_same_as to the node that carries mac/wol; return (primary, every node on that machine)."""
    if name not in nodes:
        known = ", ".join(sorted(nodes)) or "(none found; run from the directory that holds .remote-nodes/)"
        typer.echo(f"No node named '{name}'. Known nodes: {known}", err=True)
        raise typer.Exit(2)
    primary, seen = name, set()
    while nodes[primary].get("wol_same_as"):
        if primary in seen:
            typer.echo(f"wol_same_as loops at '{primary}'", err=True)
            raise typer.Exit(2)
        seen.add(primary)
        nxt = str(nodes[primary]["wol_same_as"])
        if nxt not in nodes:
            typer.echo(f"'{primary}' says wol_same_as: {nxt}, but there is no node file for it", err=True)
            raise typer.Exit(2)
        primary = nxt
    members = [primary] + [h for h, c in nodes.items() if c.get("wol_same_as") == primary]
    return primary, members


def configured_hostname(alias: str) -> str:
    """The HostName that ~/.ssh/config gives an SSH alias (the host-key name on the lan_ip fallback)."""
    out = subprocess.run(["ssh", "-G", alias], capture_output=True, text=True).stdout
    return next((ln.split(None, 1)[1] for ln in out.splitlines() if ln.startswith("hostname ")), alias)


def ssh_cmd(cfg: dict, *remote: str, connect_timeout: int = 8, lan: bool = False) -> list[str]:
    host = str(cfg["hostname"])
    target = f"{cfg['user']}@{host}" if cfg.get("user") else host
    cmd = ["ssh", "-T", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout}", "-o", "ControlPath=none"]
    if lan:
        # Same user, key and host key as the alias, but connect to lan_ip: a machine that has booted but whose
        # VPN or DNS name is not up yet (a Windows box before Tailscale starts) is still reachable.
        cmd += ["-o", f"HostName={cfg['lan_ip']}", "-o", f"HostKeyAlias={configured_hostname(host)}"]
    if cfg.get("port"):
        cmd += ["-p", str(cfg["port"])]
    if cfg.get("identity_file"):
        cmd += ["-i", str(Path(str(cfg["identity_file"])).expanduser())]
    return cmd + [target, *remote]


def ssh_answers(cfg: dict, connect_timeout: int = 8) -> bool:
    """True when SSH logs in and runs a command, by the node's hostname or else by its lan_ip. `echo ok` works in
    bash and in the Windows cmd.exe shell; `true` does not exist on Windows."""
    for lan in (False, True):
        if lan and not cfg.get("lan_ip"):
            continue
        try:
            r = subprocess.run(ssh_cmd(cfg, "echo ok", connect_timeout=connect_timeout, lan=lan),
                               capture_output=True, text=True, timeout=connect_timeout + 20)
        except subprocess.SubprocessError:
            continue
        if r.returncode == 0 and "ok" in r.stdout:
            return True
    return False


def on_link(ip: str) -> Optional[bool]:
    """True when ip is on a network this computer is directly attached to, None when it cannot tell."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["route", "-n", "get", ip], capture_output=True, text=True, timeout=5).stdout
            return None if "interface:" not in out else "gateway:" not in out
        out = subprocess.run(["ip", "-4", "route", "get", ip], capture_output=True, text=True, timeout=5).stdout
        return None if not out.strip() else " via " not in out
    except (OSError, subprocess.SubprocessError):
        return None


def answers_ping(ip: str) -> bool:
    flags = ["-c1", "-t1"] if sys.platform == "darwin" else ["-c1", "-W1"]
    try:
        return subprocess.run(["ping", *flags, ip], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def default_broadcast(lan_ip: str) -> str:
    a, b, c, _ = lan_ip.split(".")
    return f"{a}.{b}.{c}.255"


def send_magic_packet(mac: str, bcast: str) -> None:
    targets = [bcast, "255.255.255.255"]
    if shutil.which("wakeonlan"):
        for t in targets:
            subprocess.run(["wakeonlan", "-i", t, mac], capture_output=True, check=False)
        typer.echo(f"sent with wakeonlan to {', '.join(targets)}")
        return
    pkt = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    for t in targets:
        s.sendto(pkt, (t, 9))
    typer.echo(f"sent {len(pkt)} bytes to {', '.join(targets)}")


@app.command("list")
def list_machines() -> None:
    """Show every machine that has a MAC in its node file, with its Wake-on-LAN state."""
    nodes = load_nodes()
    rows: dict[str, list[str]] = {}
    for name, cfg in nodes.items():
        if cfg.get("mac") or cfg.get("wol_same_as"):
            primary, members = machine_of(nodes, name)
            rows[primary] = members
    hdr = ("MACHINE", "NODES", "MAC", "LAN IP", "WOL")
    table: list[tuple[str, ...]] = [hdr]
    for primary in sorted(rows):
        c = nodes[primary]
        table.append((primary, ",".join(rows[primary]), str(c.get("mac", "-")), str(c.get("lan_ip", "-")),
                      str(c.get("wol", "untested"))))
    widths = [max(len(r[i]) for r in table) for i in range(len(hdr))]
    for r in table:
        typer.echo("  ".join(v.ljust(widths[i]) for i, v in enumerate(r)).rstrip())
    typer.echo("\nwol: tested = a magic packet woke it from a full shutdown. untested = not tried. "
               "none = known not to work.")


@app.command()
def wake(
    node: str = typer.Argument(..., help="Node name from .remote-nodes/ (either OS side of a dual-boot machine)"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for ping and SSH after sending"),
    timeout: int = typer.Option(240, help="Seconds to wait for the machine to answer ping"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be sent and stop"),
    force: bool = typer.Option(False, "--force", help="Send even if the machine already answers ping or is marked wol: none"),
) -> None:
    """Send a magic packet to a machine and wait for it to come up."""
    nodes = load_nodes()
    primary, members = machine_of(nodes, node)
    cfg = nodes[primary]
    mac = str(cfg.get("mac", "")).lower()
    lan_ip = cfg.get("lan_ip")
    if not MAC_RE.match(mac):
        typer.echo(f"{primary}.yaml has no valid mac: field (got '{cfg.get('mac')}')", err=True)
        raise typer.Exit(2)
    if not lan_ip:
        typer.echo(f"{primary}.yaml has no lan_ip", err=True)
        raise typer.Exit(2)
    if str(cfg.get("wol", "untested")) == "none" and not force:
        typer.echo(f"{primary} is marked wol: none (Wake-on-LAN does not work on it). --force sends anyway.", err=True)
        raise typer.Exit(2)

    bcast = str(cfg.get("wol_broadcast") or default_broadcast(str(lan_ip)))
    link = on_link(str(lan_ip))
    if link is False:
        typer.echo(f"{lan_ip} is not on a LAN this computer is attached to, so a broadcast from here cannot reach "
                   f"{primary}. Run the script on a machine on that LAN.", err=True)
        raise typer.Exit(2)
    if link is None:
        typer.echo("warning: could not tell whether the target is on this computer's LAN", err=True)

    typer.echo(f"wake {primary} ({'/'.join(members)}): mac {mac}, lan_ip {lan_ip}, broadcast {bcast}")
    if dry_run:
        raise typer.Exit(0)
    if not force and answers_ping(str(lan_ip)):
        typer.echo(f"{primary} already answers ping on {lan_ip}; nothing sent (--force to send anyway)")
        raise typer.Exit(0)

    sent_at = time.monotonic()
    send_magic_packet(mac, bcast)
    if not wait:
        raise typer.Exit(0)

    typer.echo(f"waiting up to {timeout}s for {primary} to answer ping or SSH ...")
    up_by = ""
    while time.monotonic() - sent_at < timeout:
        # Windows drops ping by default, so a booted Windows machine only shows up over SSH.
        if answers_ping(str(lan_ip)):
            up_by = "ping"
            break
        up_node = next((m for m in members if ssh_answers(nodes[m], 3)), None)
        if up_node:
            up_by = f"SSH on {up_node}"
            break
        time.sleep(2)
    else:
        typer.echo(f"no answer to ping or SSH after {timeout}s. Check the NIC link light, that the machine was shut "
                   f"down from an OS that leaves Wake-on-LAN armed, and the BIOS/UEFI power settings.", err=True)
        raise typer.Exit(1)
    typer.echo(f"answers {up_by} after {int(time.monotonic() - sent_at)}s")

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for m in members:
            if ssh_answers(nodes[m]):
                typer.echo(f"{m} answers SSH after {int(time.monotonic() - sent_at)}s")
                raise typer.Exit(0)
        time.sleep(4)
    typer.echo(f"up, but none of {', '.join(members)} answers SSH yet (a dual-boot machine boots its last-used "
               f"or default OS; it may be the other side, or still starting)")


if __name__ == "__main__":
    app()
