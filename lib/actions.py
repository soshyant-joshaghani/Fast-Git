"""Remote SSH helpers used by ping/exec/restore-flat."""

from __future__ import annotations

import shlex
from typing import Any

import paramiko

from .ssh import remote_cwd_cmd, run_command


def restore_flat_stack(
    client: paramiko.SSHClient,
    server: dict[str, Any],
    *,
    branch: str | None = None,
) -> dict[str, Any]:
    """Fetch origin and hard-reset the remote clone to the rewritten tip."""
    sid = server.get("id", "?")
    if branch:
        br = shlex.quote(branch)
        script = f"""
echo "==> [{sid}] restore-flat (git only)"
git fetch origin
git reset --hard origin/{br}
git log -1 --oneline
"""
    else:
        script = f"""
echo "==> [{sid}] restore-flat (git only)"
git fetch origin
branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$branch" == "HEAD" ]]; then
  echo "error: detached HEAD on host — pass --branch <name>"
  exit 1
fi
git reset --hard "origin/${{branch}}"
git log -1 --oneline
"""
    full = remote_cwd_cmd(server, script.strip())
    code, out, err = run_command(client, full, timeout=600, get_pty=False, stream=True)
    combined = (out or "").rstrip()
    if err and err.strip():
        combined = (combined + "\n" + err.strip()).strip()
    return {
        "status": "success" if code == 0 else "failed",
        "output": "" if code == 0 else combined,
        "error": "" if code == 0 else f"exit code {code}",
    }


def run_raw(
    client: paramiko.SSHClient,
    server: dict[str, Any],
    command: str,
    *,
    in_project: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run an arbitrary remote shell command."""
    full = (
        remote_cwd_cmd(server, command)
        if in_project
        else f"bash -lc {shlex.quote(command)}"
    )
    code, out, err = run_command(client, full, timeout=timeout, stream=True)
    combined = (out or "").rstrip()
    if err and err.strip():
        combined = (combined + "\n" + err.strip()).strip()
    return {
        "status": "success" if code == 0 else "failed",
        "output": "" if code == 0 else combined,
        "error": "" if code == 0 else f"exit code {code}",
    }
