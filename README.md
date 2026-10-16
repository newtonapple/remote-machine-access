# remote-machine-access

An agent skill for managing and accessing remote machines over SSH or Tailscale. It works
with any agent harness that supports the skills convention — Claude Code, Codex, pi,
opencode, and others — via the agent-agnostic `.agents/skills/` layout.

It teaches the agent to discover machine configs in `.remote-nodes/<host>.yaml`, connect
via SSH or Tailscale SSH, run commands, transfer files, and add new nodes — **without
storing any credentials** in config files (auth comes from SSH keys, ssh-agent,
`~/.ssh/config`, or Tailscale).

## Install

Skills can live in a tool-specific directory (`~/.claude/skills/` for Claude Code) or in
the agent-agnostic `~/.agents/skills/` convention shared across agent tools. Keeping one
source of truth in `.agents/skills/` and symlinking it into each tool's skills directory
avoids duplicating the skill per tool.

### Recommended — agent-agnostic, symlinked per tool

```bash
# User-level: one source of truth, exposed to each harness via a symlink
git clone https://github.com/newtonapple/remote-machine-access.git \
  ~/.agents/skills/remote-machine-access
mkdir -p ~/.claude/skills
ln -s ~/.agents/skills/remote-machine-access ~/.claude/skills/remote-machine-access
```

Symlink into other harnesses' skills directories the same way (e.g. Codex, pi, opencode).

```bash
# Project-level: same idea with repo-relative paths
git clone https://github.com/newtonapple/remote-machine-access.git \
  .agents/skills/remote-machine-access
mkdir -p .claude/skills
ln -s ../../.agents/skills/remote-machine-access .claude/skills/remote-machine-access
```

### Simple — Claude Code only

Clone straight into the Claude skills directory (user- or project-level):

```bash
git clone https://github.com/newtonapple/remote-machine-access.git \
  ~/.claude/skills/remote-machine-access      # or: .claude/skills/remote-machine-access
```

The skill activates automatically when a request involves a remote machine, node, server,
or host (e.g. "run this on the node", "SSH into the box", "deploy to the cluster").

## Node config

Define each machine in `.remote-nodes/<host>.yaml` (filename matches `host:`). Minimal form:

```yaml
host: gpu-box
hostname: gpu-box
```

Optional fields (`user`, `port`, `identity_file`, `description`, `lan_ip`, `tailscale_ip`)
are documented in [SKILL.md](SKILL.md). Prefer the minimal form and let `~/.ssh/config`
supply the user, key, and real hostname.

## Validate a node

```bash
uv run --with pyyaml python scripts/check-node.py <host>
```

Checks that the YAML parses, required fields are present, the filename matches `host`, and
the machine is reachable via SSH (and Tailscale, if configured).

## Repo contents

| Path | Purpose |
|---|---|
| `SKILL.md` | The skill: rules, config format, and connection/command/transfer workflows |
| `scripts/check-node.py` | Config validation + connectivity check |
| `scripts/winrun.py` | Run PowerShell on a Windows node over SSH (encoding, long scripts, exit codes) |
| `scripts/wake.py` | Wake-on-LAN: list the machines that have a MAC and their wake state, send a magic packet, wait for ping and SSH. Needs `uv` (installs `typer` and `pyyaml`) and a sender on the target's LAN; see SKILL.md |
| `tests/test_wake.py` | Unit tests for `wake.py` (`uv run --with pytest --with typer --with pyyaml pytest tests -q`) |
| `CHANGELOG.md` | Release history ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)) |
| `VERSION` | Current version |

## License

[MIT](LICENSE)
