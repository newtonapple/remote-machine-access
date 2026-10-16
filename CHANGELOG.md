# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `scripts/wake.py` counts a machine as up when it answers SSH as well as ping. Windows drops ping by
  default, so a Windows machine that had booted was reported as a failed wake.

## [1.2.0] - 2026-10-15

### Added

- `scripts/wake.py` (typer, run with `uv`): `list` shows every machine that has a MAC with its
  Wake-on-LAN state; `wake` sends a magic packet (with `wakeonlan` when installed, otherwise with
  Python's socket module), refuses a send that cannot reach the target's LAN, skips machines that
  already answer ping, and waits for ping and SSH. Dependencies: `uv` (or Python 3.10 and
  `pip install typer pyyaml`), `ping`, `ssh`.
- Node-file fields `mac`, `wol`, `wol_broadcast`, `wol_same_as`.
- SKILL.md section Waking Machines (Wake-on-LAN): requirements, target setup, behavior, and how to
  power a machine off over SSH.

## [1.1.0] - 2026-10-12

### Added

- `scripts/winrun.py`: run PowerShell on a Windows node over SSH without cmd.exe quoting
  problems. Short scripts go as `-EncodedCommand`, long ones are copied to `%TEMP%` and run
  (the 8191-character command-line limit), the remote exit code is kept, PowerShell error
  text is shown while CLIXML progress and the OpenSSH post-quantum warning are dropped.
- SKILL.md sections: Dual-boot Machines, Windows Nodes, and First Access to a Machine That
  Only Has Password Auth (user-opened ControlMaster connection, key install including the
  Windows administrator key file and its ACL, host key pinning, `~/.ssh/config` alias).

### Changed

- SKILL.md: `hostname` should be the name `ssh` resolves (the `~/.ssh/config` alias), because
  `check-node.py` connects to it verbatim and a full FQDN skips the Host block.
- SKILL.md: run `check-node.py` through `uv run --with pyyaml`, since it imports PyYAML.

## [1.0.0] - 2026-06-14

### Added

- Initial release of the `remote-machine-access` skill — harness-agnostic (Claude
  Code, Codex, pi, opencode, and others via the `.agents/skills/` convention).
- SKILL.md covering: hard rules (no credentials in configs, `ssh -T` for
  non-interactive commands, temporary-tunnel cleanup, filename/`host` match,
  connection-only node configs), SSH target construction, `hostname` resolution
  order, config format, discovery & merge, the symlink pattern for sharing one
  config across nested components, and workflows for adding nodes, running
  commands, tunnels, and file transfers.
- `scripts/check-node.py` for config validation and SSH/Tailscale connectivity
  checks.
- Repo README (install via the agent-agnostic `.agents/skills/` layout with
  symlinks into each harness's skills directory), MIT license, and this changelog.

[1.1.0]: https://github.com/newtonapple/remote-machine-access/releases/tag/v1.1.0
[1.0.0]: https://github.com/newtonapple/remote-machine-access/releases/tag/v1.0.0
