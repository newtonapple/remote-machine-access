#!/usr/bin/env python3
"""
Validate a remote-node config and check connectivity.

Usage:
  python3 scripts/check-node.py <path-to-config.yaml>
  python3 scripts/check-node.py <hostname>            # search .remote-nodes/<hostname>.yaml
  python3 scripts/check-node.py <hostname> --dir <dir> # search <dir>/.remote-nodes/<hostname>.yaml

Exit codes:
  0 — all checks passed, machine reachable
  1 — config invalid (YAML, missing fields, filename mismatch)
  2 — config valid but machine unreachable
"""

import os
import sys
import subprocess
import yaml

REQUIRED_FIELDS = ["host", "hostname"]


def resolve_config(arg, search_dir=None):
    """Resolve a path or hostname to a config file."""
    if arg.endswith(".yaml") or arg.endswith(".yml"):
        path = arg
        if not os.path.isfile(path):
            print(f"✗ File not found: {path}")
            sys.exit(1)
        return path

    # Treat arg as hostname — look in .remote-nodes/
    candidates = []
    if search_dir:
        candidates.append(os.path.join(search_dir, ".remote-nodes", f"{arg}.yaml"))
        candidates.append(os.path.join(search_dir, ".remote-nodes", f"{arg}.yml"))
    # Also check current dir
    candidates.append(os.path.join(".remote-nodes", f"{arg}.yaml"))
    candidates.append(os.path.join(".remote-nodes", f"{arg}.yml"))

    for c in candidates:
        if os.path.isfile(c):
            return c

    print(f"✗ No config found for host '{arg}'")
    print(f"  Searched:")
    for c in candidates:
        print(f"    - {os.path.relpath(c) if os.path.exists(os.path.dirname(c)) else c}")
    sys.exit(1)


def validate(config_path):
    """Validate config format. Returns (config_dict, [error_msgs])."""
    errors = []

    # 1. Basic file check
    if not os.path.isfile(config_path):
        errors.append(f"File not found: {config_path}")
        return None, errors

    # 2. Parse YAML
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML parse error: {e}")
        return None, errors

    if not isinstance(cfg, dict):
        errors.append("Config is not a YAML mapping")
        return None, errors

    # 3. Required fields
    for field in REQUIRED_FIELDS:
        if field not in cfg or not cfg[field]:
            errors.append(f"Missing required field: '{field}'")

    if errors:
        return cfg, errors

    # 4. Filename matches host
    filename = os.path.splitext(os.path.basename(config_path))[0]
    if filename != cfg["host"]:
        errors.append(f"Filename '{filename}' does not match host '{cfg['host']}'")

    return cfg, errors


def check_ssh(cfg):
    """Try SSH connectivity. Returns (reachable: bool, detail: str)."""
    hostname = cfg["hostname"]
    user = cfg.get("user")
    port = cfg.get("port", 22)
    identity = cfg.get("identity_file")

    # Build SSH target
    target = f"{user}@{hostname}" if user else hostname

    # Build command
    cmd = ["ssh", target, "-p", str(port), "-T", "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
           "echo OK"]
    if identity:
        cmd.insert(2, "-i")
        cmd.insert(3, os.path.expanduser(identity))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and "OK" in result.stdout:
            return True, f"SSH to {target}:{port} — OK"
        else:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            return False, f"SSH to {target}:{port} — FAILED ({detail})"
    except subprocess.TimeoutExpired:
        return False, f"SSH to {target}:{port} — TIMEOUT (15s)"
    except FileNotFoundError:
        return False, "SSH command not found"


def check_tailscale(cfg):
    """Try Tailscale SSH connectivity. Returns (reachable: bool, detail: str)."""
    hostname = cfg["hostname"]
    user = cfg.get("user")

    target = f"{user}@{hostname}" if user else hostname

    try:
        result = subprocess.run(
            ["tailscale", "ssh", target, "echo OK"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and "OK" in result.stdout:
            return True, f"Tailscale to {target} — OK"
        else:
            return False, f"Tailscale to {target} — FAILED ({result.stderr.strip()})"
    except subprocess.TimeoutExpired:
        return False, f"Tailscale to {target} — TIMEOUT (15s)"
    except FileNotFoundError:
        return False, "Tailscale command not found"


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(1)

    arg = sys.argv[1]
    search_dir = None
    if "--dir" in sys.argv:
        idx = sys.argv.index("--dir")
        if idx + 1 < len(sys.argv):
            search_dir = sys.argv[idx + 1]

    config_path = resolve_config(arg, search_dir)
    print(f"Config: {os.path.relpath(config_path)}")
    print()

    # Validate
    print("── Validation ──")
    cfg, errors = validate(config_path)
    if errors:
        for e in errors:
            print(f"  ✗ {e}")
        print()
        print("  ❌ Config invalid — fix errors and re-run")
        sys.exit(1)
    else:
        print("  ✓ YAML parses correctly")
        print("  ✓ Required fields present")
        print("  ✓ Filename matches host field")
        print()

    # Connectivity
    print("── Connectivity ──")
    ssh_ok, ssh_detail = check_ssh(cfg)
    print(f"  {'✓' if ssh_ok else '✗'} {ssh_detail}")

    if not ssh_ok:
        ts_ok, ts_detail = check_tailscale(cfg)
        print(f"  {'✓' if ts_ok else '✗'} {ts_detail}")
        if ts_ok:
            print()
            print("  ✓ Machine reachable via Tailscale SSH")
            sys.exit(0)
        else:
            print()
            print("  ❌ Machine unreachable — check hostname, network, and credentials")
            sys.exit(2)
    else:
        print("  ✓ Machine reachable via SSH")
        sys.exit(0)


if __name__ == "__main__":
    main()