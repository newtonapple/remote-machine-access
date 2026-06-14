---
name: remote-machine-access
description: Manage and access remote machines via SSH or Tailscale. Use when the user references a remote machine, node, server, or host — e.g., "run this on the remote box", "check GPU usage on the node", "deploy to the cluster", "access the remote node", "SSH into the machine". Triggers on any request involving remote execution, remote commands, remote file operations, or cluster/node management.
---

# Remote Machine Access

Manage remote machines defined in `.remote-nodes/<host>.yaml`: discover them, connect via
SSH or Tailscale, run commands, transfer files, and add new nodes.

## Rules

- **MUST NOT** store passwords, private keys, or secrets in configs. Authentication comes
  only from SSH keys, ssh-agent, `~/.ssh/config`, or Tailscale SSH.
- **MUST** run non-interactive commands with `ssh -T` (no PTY) — otherwise SIGHUP can kill
  backgrounded processes when `~/.ssh/config` sets `RequestTTY=yes`.
- **MUST** clean up any temporary tunnel you create (see [Tunnels](#tunnels)).
- **MUST** name each config file `<host>.yaml`, matching its `host:` field.
- Node configs **MUST** hold only connection info. **MUST NOT** add component-specific
  metadata (model lists, Docker images, recipes, GPU specs, project paths) — a parent
  config merges into every sub-component's context, and such data duplicates what the
  component owns and goes stale.

## Building the SSH Target

Every `ssh`/`scp`/`rsync`/`tailscale ssh` command uses the same target:

- If `user:` is set in the config, use `user@hostname`.
- If `user:` is omitted, use bare `hostname` and let `~/.ssh/config` supply the user
  (verify with `ssh -G <host>`).

Examples below use a bare host (`gpu-box`); substitute `user@gpu-box` when a user is set.

**`hostname` resolution order** (try until one connects):

1. DNS / mDNS (e.g. `gpu-box.local`)
2. `~/.ssh/config` Host alias
3. Tailscale MagicDNS (if Tailscale is up)
4. `tailscale_ip` fallback
5. `lan_ip` fallback

Fall back to `tailscale ssh` when direct `ssh` fails or the node is only reachable on the
tailnet.

## Config Format

A config is a flat YAML file at `.remote-nodes/<host>.yaml` defining one machine.

| Field | Required | Description |
|---|---|---|
| `host` | Yes | Identifier; must match the filename |
| `hostname` | Yes | Resolvable SSH target — DNS name, IP, or Tailscale MagicDNS |
| `user` | No | SSH username (omit if set in `~/.ssh/config`) |
| `port` | No | SSH port (default 22) |
| `identity_file` | No | SSH key path (else ssh-agent / default keys) |
| `description` | No | Human-readable note |
| `lan_ip` | No | LAN IP for direct access / fallback |
| `tailscale_ip` | No | Tailscale IP fallback |

Default to the minimal form; add fields only when `~/.ssh/config` doesn't supply them:

```yaml
# minimal
host: gpu-box
hostname: gpu-box
```

```yaml
# with explicit fields
host: gpu-box
user: alice
hostname: gpu-box
port: 22
identity_file: ~/.ssh/id_ed25519
description: GPU workstation
lan_ip: 192.168.1.50
tailscale_ip: 100.64.0.1
```

> **Parser note:** keep configs flat (no nested mappings) and put comments on their own
> lines, not inline after a value — some tooling reads these with a simple line parser,
> not a full YAML library.

## Discovery & Resolution

To resolve a host the user names ("run this on gpu-box"):

1. Look in `./.remote-nodes/` first, then the parent dir's `.remote-nodes/` (**one level
   up only**). Merge both; the closer dir wins for a duplicate `host`.
2. Read the matching `<host>.yaml`, build the target, try `ssh` then `tailscale ssh`.

**Sharing one config across deeply-nested components:** because discovery scans only one
level up, a component more than one level below a shared config can't see it. Symlink
rather than copy, to keep a single source of truth:

```bash
# from the component's .remote-nodes/ dir; adjust ../ depth to reach the shared config
ln -s ../../../.remote-nodes/<host>.yaml <host>.yaml
```

## Adding a Node

1. **Pick the directory:** the one the user names; else the current dir's `.remote-nodes/`;
   else a named subproject's `.remote-nodes/`. Create it if missing.
2. Write `<dir>/.remote-nodes/<host>.yaml` (filename = `host`) using the minimal form.
3. **Validate, then verify reachability:**

```bash
python3 -c "import yaml; c=yaml.safe_load(open('.remote-nodes/gpu-box.yaml')); \
  assert c.get('host') and c.get('hostname'), 'missing host/hostname'; print('config OK')"
ssh -T gpu-box "hostname"        # or: tailscale ssh gpu-box "hostname"
```

## Running Commands

```bash
ssh -T gpu-box "nvidia-smi"                  # non-interactive (always -T)
ssh -T gpu-box -i ~/.ssh/id_ed25519 "docker ps"
ssh gpu-box                                  # interactive session
tailscale ssh gpu-box "uptime"               # via Tailscale

# multi-line
ssh -T gpu-box <<'EOF'
  cd /path/to/project && git pull
EOF
```

## Tunnels

Use `-N -f` for background tunnels. **Always kill temporary tunnels when done.**

```bash
ssh -L 8000:localhost:8000 gpu-box -N -f     # local: localhost:8000 → remote:8000
ssh -R 3000:localhost:3000 gpu-box -N -f     # remote: remote:3000 → local:3000
ssh -D 1080 gpu-box -N -f                     # dynamic SOCKS proxy

pkill -f 'ssh -[LRD]'                         # kill all tunnels (or kill <pid>)
lsof -i :8000                                 # verify gone
```

## File Transfers

```bash
scp ./file gpu-box:/remote/path/             # push (scp gpu-box:/path ./ to pull)
scp -r ./dir gpu-box:/remote/dir/            # recursive
rsync -avz ./dir/ gpu-box:/remote/dir/       # sync (add --dry-run to preview)
rsync -avz --delete ./dir/ gpu-box:/remote/dir/   # mirror (deletes extra dest files)
rsync -avz --exclude='.git' ./ gpu-box:/remote/proj/
rsync -avz gpu-box:/remote/dir/ ./local/     # pull
```
