#!/usr/bin/env python3
"""
Run PowerShell on a Windows node over SSH without cmd.exe quoting problems.

Windows OpenSSH hands the remote command to cmd.exe, which mangles quotes and `%`,
caps the command line at about 8191 characters, and prints CLIXML noise on stderr.
This helper avoids all three.

Usage:
  python3 scripts/winrun.py <ssh-host> -c 'Get-Date'
  python3 scripts/winrun.py <ssh-host> path/to/script.ps1
  python3 scripts/winrun.py <ssh-host> - < script.ps1

How it runs the script:
  - short scripts: `powershell -EncodedCommand <base64 of UTF-16LE>`
  - long scripts (encoded form over ~6000 chars): scp to the node's %TEMP%, run with
    `-File`, delete afterwards

Notes:
  - <ssh-host> is whatever `ssh` resolves (an ~/.ssh/config alias is best, because it
    carries the user and key). Extra ssh options: set SSH_OPTS, e.g.
    SSH_OPTS='-o ControlPath=/tmp/cm-box -o ControlMaster=no'.
  - Output is returned with NULs and CRs stripped. The OpenSSH post-quantum warning and
    PowerShell CLIXML progress blocks are filtered from stderr.
  - The script runs with $ProgressPreference='SilentlyContinue' and
    $ErrorActionPreference left at its default.
  - Do not name a PowerShell function `H` (it is the alias of Get-History).

Exit code is the remote PowerShell's exit code, or 2 for transport errors.
"""

import base64
import os
import re
import shlex
import subprocess
import sys

MAX_ENCODED = 6000  # keep well under cmd.exe's 8191-character limit
PREFIX = "$ProgressPreference='SilentlyContinue'\n"
NOISE = (
    "post-quantum key exchange",
    "store now, decrypt later",
    "openssh.com/pq",
    "may need to be upgraded",
)


def ssh_base():
    opts = shlex.split(os.environ.get("SSH_OPTS", ""))
    return ["ssh", "-T", "-o", "BatchMode=yes"] + opts


def clean(text):
    return text.replace("\x00", "").replace("\r", "")


def unescape_clixml(s):
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), s)


def filter_stderr(text):
    text = clean(text)
    # PowerShell wraps errors and progress in CLIXML. Keep the error strings, drop progress.
    def keep_errors(m):
        errs = re.findall(r'<S S="Error">(.*?)</S>', m.group(0), flags=re.S)
        return "\n".join(unescape_clixml(e) for e in errs)
    text = re.sub(r"#< CLIXML\s*<Objs.*?</Objs>", keep_errors, text, flags=re.S)
    text = text.replace("\r", "")
    lines = [ln for ln in text.splitlines() if ln.strip() and not any(n in ln for n in NOISE)]
    return "\n".join(lines)


def run_encoded(host, script):
    b64 = base64.b64encode(script.encode("utf-16-le")).decode()
    cmd = ssh_base() + [host, f"powershell -NoProfile -NonInteractive -EncodedCommand {b64}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def remote_temp(host):
    r = subprocess.run(ssh_base() + [host, "echo %TEMP%"], capture_output=True, text=True, timeout=60)
    temp = clean(r.stdout).strip()
    if not temp or "%" in temp:
        raise RuntimeError(f"could not read %TEMP% on {host}: {r.stderr.strip()[:200]}")
    return temp


def wrapper(remote_win):
    """Run the copied script, delete it, and keep its exit code (a trailing `& del` in
    cmd.exe would replace the exit code with del's)."""
    p = remote_win.replace("'", "''")
    return (
        f"& '{p}'; $ok=$?; $c=$LASTEXITCODE; "
        f"Remove-Item -LiteralPath '{p}' -Force -ErrorAction SilentlyContinue; "
        "if($c){exit $c} elseif(-not $ok){exit 1} else {exit 0}"
    )


def run_file(host, script):
    temp = remote_temp(host)
    name = f"winrun-{os.getpid()}.ps1"
    local = os.path.join(os.environ.get("TMPDIR", "/tmp"), name)
    with open(local, "w", encoding="utf-8-sig") as f:  # BOM so PowerShell reads UTF-8
        f.write(script)
    remote_win = temp.rstrip("\\") + "\\" + name
    remote_scp = remote_win.replace("\\", "/")
    try:
        subprocess.run(
            ["scp", "-q", "-o", "BatchMode=yes"] + shlex.split(os.environ.get("SSH_OPTS", "")) + [local, f"{host}:{remote_scp}"],
            check=True, capture_output=True, timeout=120,
        )
        cmd = ssh_base() + [
            host,
            "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand "
            + base64.b64encode(wrapper(remote_win).encode("utf-16-le")).decode(),
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    finally:
        try:
            os.remove(local)
        except OSError:
            pass


def main(argv):
    if len(argv) < 3 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(argv) >= 2 and argv[1] in ("-h", "--help") else 2
    host = argv[1]
    if argv[2] == "-c":
        if len(argv) < 4:
            print("winrun: -c needs a command", file=sys.stderr)
            return 2
        script = argv[3]
    elif argv[2] == "-":
        script = sys.stdin.read()
    else:
        with open(argv[2], encoding="utf-8") as f:
            script = f.read()
    script = PREFIX + script
    try:
        encoded_len = len(base64.b64encode(script.encode("utf-16-le")))
        r = run_encoded(host, script) if encoded_len <= MAX_ENCODED else run_file(host, script)
    except (subprocess.SubprocessError, RuntimeError, OSError) as e:
        print(f"winrun: transport error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(clean(r.stdout))
    err = filter_stderr(r.stderr)
    if err:
        print(err, file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
