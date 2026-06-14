# remote-machine-access

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill for managing and
accessing remote machines over SSH or Tailscale.

It teaches the agent to discover machine configs in `.remote-nodes/<host>.yaml`, connect
via SSH or Tailscale SSH, run commands, transfer files, and add new nodes — **without
storing any credentials** in config files (auth comes from SSH keys, ssh-agent,
`~/.ssh/config`, or Tailscale).

## Install

Clone into your Claude skills directory:

```bash
# User-level (available in every project)
git clone https://github.com/<owner>/remote-machine-access.git \
  ~/.claude/skills/remote-machine-access

# or project-level
git clone https://github.com/<owner>/remote-machine-access.git \
  .claude/skills/remote-machine-access
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
python3 scripts/check-node.py <host>
```

Checks that the YAML parses, required fields are present, the filename matches `host`, and
the machine is reachable via SSH (and Tailscale, if configured).

## Repo contents

| Path | Purpose |
|---|---|
| `SKILL.md` | The skill: rules, config format, and connection/command/transfer workflows |
| `scripts/check-node.py` | Config validation + connectivity check |
