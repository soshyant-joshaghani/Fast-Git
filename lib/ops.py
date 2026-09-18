"""Local and remote ops: status, backup, setup script runners."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import paramiko

from .config import REMOTE_DIR, ROOT
from .ssh import echo, run_command, upload_file


SETUP_SCRIPT = REMOTE_DIR / "setup-ubuntu-gitlab.sh"
STATUS_SCRIPT = REMOTE_DIR / "gitlab-status.sh"
BACKUP_SCRIPT = REMOTE_DIR / "gitlab-backup.sh"


def is_linux_like() -> bool:
    return sys.platform.startswith("linux")


def ensure_bash_script(script: Path) -> Path:
    if not script.is_file():
        raise SystemExit(f"Missing script: {script}")
    return script


def run_local_script(
    script: Path,
    *,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> int:
    """Run a remote/*.sh script on this machine (Linux/WSL)."""
    ensure_bash_script(script)
    if not is_linux_like():
        raise SystemExit(
            "GitLab Omnibus setup/status requires Linux (or WSL).\n"
            f"  On Windows: use `fast-git provision <host>` against an Ubuntu VM,\n"
            f"  or run inside WSL from {ROOT}."
        )
    bash = shutil.which("bash")
    if not bash:
        raise SystemExit("bash not found on PATH.")
    cmd = [bash, str(script), *(args or [])]
    merged = os.environ.copy()
    if env:
        merged.update(env)
    echo(f"==> running {script.name} {' '.join(args or [])}".rstrip())
    proc = subprocess.run(cmd, cwd=str(ROOT), env=merged, timeout=timeout)
    return int(proc.returncode)


def local_setup(*, skip_runner: bool = False, external_url: str | None = None) -> int:
    env: dict[str, str] = {}
    if skip_runner:
        env["FAST_GIT_SKIP_RUNNER"] = "1"
    if external_url:
        env["GITLAB_EXTERNAL_URL"] = external_url
    return run_local_script(SETUP_SCRIPT, env=env)


def local_status() -> int:
    return run_local_script(STATUS_SCRIPT)


def local_backup() -> int:
    return run_local_script(BACKUP_SCRIPT)


def local_quick_status() -> int:
    """Lightweight status without requiring the full status script (any OS for Docker)."""
    checks = [
        ("Docker", ["docker", "--version"]),
        ("Docker Compose", ["docker", "compose", "version"]),
    ]
    if is_linux_like():
        checks.extend(
            [
                ("GitLab", ["gitlab-ctl", "status"]),
                ("GitLab Runner", ["gitlab-runner", "status"]),
            ]
        )
    else:
        echo(f"OS: {platform.system()} {platform.release()} (GitLab Omnibus is Linux-only)")
        echo("Hint: provision a remote Ubuntu host, or run status inside WSL/Linux.")

    rc = 0
    for label, cmd in checks:
        if shutil.which(cmd[0]) is None:
            echo(f"[ ] {label}: not installed")
            rc = 1
            continue
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            line = (proc.stdout or proc.stderr).strip().splitlines()[:1]
            detail = line[0] if line else "ok"
            echo(f"[ok] {label}: {detail}")
        else:
            echo(f"[!] {label}: exit {proc.returncode}")
            rc = 1
    return rc


def provision_remote(
    client: paramiko.SSHClient,
    server: dict[str, Any],
    *,
    external_url: str | None = None,
    skip_runner: bool = False,
) -> dict[str, Any]:
    """Upload and run setup-ubuntu-gitlab.sh on a remote host."""
    ensure_bash_script(SETUP_SCRIPT)
    remote_tmp = "/tmp/fast-git-setup-ubuntu-gitlab.sh"
    echo(f"[{server['id']}] uploading {SETUP_SCRIPT.name}")
    upload_file(client, SETUP_SCRIPT, remote_tmp)
    env_exports = []
    if external_url:
        env_exports.append(f"export GITLAB_EXTERNAL_URL={external_url!r}")
    if skip_runner:
        env_exports.append("export FAST_GIT_SKIP_RUNNER=1")
    env_prefix = " && ".join(env_exports)
    if env_prefix:
        env_prefix += " && "
    cmd = (
        f"chmod +x {remote_tmp} && {env_prefix}bash {remote_tmp}"
    )
    # Omnibus install can take a long time
    code, out, err = run_command(client, cmd, timeout=3600, stream=True)
    output = (out or err).strip()
    return {
        "status": "success" if code == 0 else "failed",
        "output": output,
        "error": "" if code == 0 else f"exit {code}",
    }


def remote_status(client: paramiko.SSHClient, server: dict[str, Any]) -> dict[str, Any]:
    ensure_bash_script(STATUS_SCRIPT)
    remote_tmp = "/tmp/fast-git-gitlab-status.sh"
    upload_file(client, STATUS_SCRIPT, remote_tmp)
    code, out, err = run_command(
        client, f"chmod +x {remote_tmp} && bash {remote_tmp}", timeout=120, stream=False
    )
    return {
        "status": "success" if code == 0 else "failed",
        "output": (out or err).strip(),
        "error": "" if code == 0 else f"exit {code}",
    }
