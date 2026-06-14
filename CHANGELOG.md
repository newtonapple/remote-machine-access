# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.0]: https://github.com/newtonapple/remote-machine-access/releases/tag/v1.0.0
