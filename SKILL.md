---
name: remote-machine-access
description: Manage and access remote machines via SSH or Tailscale. Use when the user references a remote machine, node, server, or host — e.g., "run this on the remote box", "check GPU usage on the node", "deploy to the cluster", "access the remote node", "SSH into the machine". Triggers on any request involving remote execution, remote commands, remote file operations, or cluster/node management.
metadata:
  version: 1.2.0
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
- Node configs **MUST** hold only connection info (a MAC address and the Wake-on-LAN fields
  below count: they are how you reach a machine that is off). **MUST NOT** add
  component-specific metadata (model lists, Docker images, recipes, GPU specs, project paths)
  (a parent config merges into every sub-component's context, and such data duplicates what
  the component owns and goes stale).

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
| `mac` | No | NIC MAC address (quote it). Needed to wake the machine with Wake-on-LAN |
| `wol` | No | Wake-on-LAN state: `tested`, `untested` (default) or `none` |
| `wol_broadcast` | No | Broadcast address for the packet (default: `lan_ip` with the last octet 255) |
| `wol_same_as` | No | Other OS side of a dual-boot machine: the node file that carries `mac` and `wol` |

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

> **`hostname` should be the name `ssh` resolves, not a long FQDN, when a `~/.ssh/config`
> Host block supplies the user and key.** `scripts/check-node.py` and the resolution order
> connect to `hostname` verbatim, so a full tailnet name skips the Host block and logs in as
> your local user. Put the alias in `hostname` and keep the user and key in the Host block.

## Dual-boot Machines

Give each OS its own node file: `<host>` for the Windows side and `<host>-ubuntu` for the
Linux side. The tailnet names must differ (Tailscale renames the second one otherwise).
Only one OS is reachable at a time, so a timeout on one entry usually means the box booted
into the other OS. Create the Linux entry after the install, not before.

## Waking Machines (Wake-on-LAN)

A machine that is off cannot be reached by SSH. If it supports Wake-on-LAN (WoL), `scripts/wake.py`
wakes it with a magic packet. The node file records which machines can be woken: `mac` says how,
`wol` says whether it has been shown to work.

```yaml
# .remote-nodes/gpu-box.yaml
host: gpu-box
hostname: gpu-box
lan_ip: 192.168.1.50
mac: "aa:bb:cc:dd:ee:ff"
# tested: a magic packet woke it from a full shutdown. untested: not tried. none: does not work.
wol: tested
```

Run the script from the directory that holds `.remote-nodes/`, with `uv` (it reads the dependencies
from the script's header). `<skill>` is the folder this skill is installed in.

```bash
uv run <skill>/scripts/wake.py list                 # every machine with a MAC: LAN IP, wol state
uv run <skill>/scripts/wake.py wake gpu-box         # send the packet, wait for ping and SSH
uv run <skill>/scripts/wake.py wake gpu-box --dry-run
```

**Requirements**

- `uv` (https://docs.astral.sh/uv/). It installs the script's two Python dependencies, `typer` and
  `pyyaml`, on first run. Without `uv`, use Python 3.10 or newer and `pip install typer pyyaml`.
- `ping` and `ssh` on the PATH. The script uses them to wait for the machine.
- The `wakeonlan` command is optional. The script uses it when found and otherwise sends the packet
  itself with Python's socket module.
- The computer running the script must be on the **same LAN** as the target. A magic packet is a
  layer 2 broadcast and does not cross a router or a VPN. The script asks the routing table and
  refuses a send that cannot arrive, with the reason.
- The target must be set up for WoL: enabled in the BIOS/UEFI (some boards also need a deep-sleep
  or ErP-style power saving setting off), a wired NIC that supports it, and the OS must leave the NIC
  armed at shutdown (on Linux, `ethtool <if>` shows `Wake-on: g`). Many Linux drivers come up with
  it off, so check after a reboot, not only after setting it.

**Behavior**

- Nothing is sent when the machine already answers ping (`--force` overrides). `wol: none` also
  stops the script (`--force` overrides).
- After sending it waits for ping, then for SSH on the node files of that machine. A timeout means
  check the NIC link light, how the machine was shut down, and the BIOS settings above.
- The broadcast address defaults to `lan_ip` with the last octet set to 255 (a /24). Set
  `wol_broadcast` for any other netmask.
- **Dual-boot machines** share one NIC and MAC, so a wake starts the machine, not an OS: the
  bootloader picks the OS. Put `mac` and `wol` in one node file and `wol_same_as: <that node>` in the
  other; the script reports which side answered SSH.
- To find out which machines can be woken, run `list` rather than copying its output into docs.
  Update `wol` to `tested` or `none` when you try a machine.

**Powering a machine off** needs no script. Linux: `ssh -t <host> 'sudo systemctl poweroff'` (`-t`
so sudo can ask for a password; never type or store the password for the user). Windows:
`ssh <host> 'shutdown /s /t 5'`.

## Windows Nodes

- The remote shell is `cmd.exe`. It mangles quotes and `%`, caps the command line at about
  8191 characters, and Windows OpenSSH wraps PowerShell errors in CLIXML noise.
- Use `scripts/winrun.py <ssh-host> -c '<powershell>'`, or pass a `.ps1` file, or `-` for
  stdin. It sends short scripts as `-EncodedCommand`, copies long ones to `%TEMP%` and runs
  them, deletes the copy, keeps the real exit code, and prints PowerShell error text while
  dropping progress and the OpenSSH post-quantum warning.
- Windows has no Tailscale SSH server, so `tailscale ssh` fails. Use plain `ssh` to the
  tailnet name.
- `scp` takes forward slashes in remote paths (`C:/Users/me/file`).
- Do not name a PowerShell helper function `H` (alias of `Get-History`, it silently drops
  output).
- If a node drops off the tailnet in the middle of a session, check Windows Update history
  before blaming sleep: a feature update reboots the machine.

## First Access to a Machine That Only Has Password Auth

The agent never types a password. Have the user open one authenticated connection, then
install a key over it so nothing else needs a password:

1. The user runs, in their own terminal (one password prompt, then it backgrounds):
   `ssh -fN -o ControlMaster=yes -o ControlPath=$HOME/.ssh/cm-<host> -o ControlPersist=30m <user>@<host>`
   Check it with `ssh -O check -o ControlPath=... <user>@<host>`. Send commands through it
   with `-o ControlPath=... -o ControlMaster=no -o BatchMode=yes`
   (`SSH_OPTS` does the same for `winrun.py`).
2. Install the public key.
   - Linux: append to `~/.ssh/authorized_keys` over the master (or `ssh-copy-id` through it).
   - Windows administrator account: append to `C:\ProgramData\ssh\administrators_authorized_keys`
     (not `~\.ssh\authorized_keys`; `Match Group administrators` in `sshd_config` redirects it),
     then run `icacls <file> /inheritance:r /grant SYSTEM:(F) /grant BUILTIN\Administrators:(F)`,
     or sshd ignores the file. Probe admin status first.
3. Pin the host key without trusting first use: read the node's
   `ssh_host_ed25519_key.pub` over the master, compare it with `ssh-keyscan -t ed25519 <host>`
   (filter the `#` banner line, or the comparison false-fails), then append to `known_hosts`.
4. Add a `Host <name>` block to `~/.ssh/config` (back the file up first), prove it with
   `ssh -o ControlPath=none -o BatchMode=yes <name> true`, then close the master with
   `ssh -O exit`.
5. Create the node file with `hostname` set to that alias.

The Windows OpenSSH 9.5 build prints a post-quantum key-exchange warning on every login.
It is noise.

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
3. **Validate, then verify reachability.** `scripts/check-node.py` imports PyYAML, which the
   system Python may lack; run it as `uv run --with pyyaml python scripts/check-node.py <host>`.

```bash
uv run --with pyyaml python scripts/check-node.py gpu-box
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
