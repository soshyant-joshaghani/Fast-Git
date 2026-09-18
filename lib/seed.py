"""Project seed: create GitLab project, push local repo, write CI config."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .gitlab_api import GitLabAPI
from .ssh import echo


def _slugify(name: str) -> str:
    s = name.strip().lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    return s.strip("-._") or "project"


def detect_ctrl_script(project_dir: Path) -> str | None:
    """Find __ctrl__/*-ctrl.sh inside a Fast-* project."""
    ctrl = project_dir / "__ctrl__"
    if not ctrl.is_dir():
        return None
    for path in sorted(ctrl.glob("*-ctrl.sh")):
        return path.name
    return None


def git_run(project_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=check,
    )


def ensure_git_repo(project_dir: Path) -> None:
    if not (project_dir / ".git").is_dir():
        raise SystemExit(f"Not a git repository: {project_dir}")


def set_remote(project_dir: Path, remote_name: str, url: str) -> None:
    existing = git_run(project_dir, "remote", check=False)
    remotes = {line.strip() for line in (existing.stdout or "").splitlines() if line.strip()}
    if remote_name in remotes:
        git_run(project_dir, "remote", "set-url", remote_name, url)
    else:
        git_run(project_dir, "remote", "add", remote_name, url)


def push_all(project_dir: Path, remote_name: str = "gitlab") -> None:
    echo(f"==> git push --all {remote_name}")
    proc = git_run(project_dir, "push", "--all", remote_name, check=False)
    if proc.returncode != 0:
        echo(proc.stderr or proc.stdout)
        raise SystemExit(f"git push --all failed (exit {proc.returncode})")
    tags = git_run(project_dir, "push", "--tags", remote_name, check=False)
    if tags.returncode != 0 and "no refs" not in (tags.stderr or "").lower():
        echo(f"    (tags push note: {(tags.stderr or tags.stdout).strip()})")


def write_ci_file(project_dir: Path, content: str, *, force: bool = False) -> Path:
    ci_path = project_dir / ".gitlab-ci.yml"
    if ci_path.is_file() and not force:
        echo(f"==> .gitlab-ci.yml already exists — left unchanged (use --force-ci to overwrite)")
        return ci_path
    ci_path.write_text(content, encoding="utf-8", newline="\n")
    echo(f"==> wrote {ci_path}")
    return ci_path


def load_profile(name: str) -> Any:
    key = name.strip().lower().replace("-", "_")
    if key in {"fast_family", "fast-family", "family"}:
        from profiles import fast_family as mod
    elif key == "python":
        from profiles import python as mod
    elif key == "docker":
        from profiles import docker as mod
    elif key in {"generic", "none", "bare"}:
        from profiles import generic as mod
    else:
        raise SystemExit(
            f"Unknown profile '{name}'. Choose: fast-family, python, docker, generic"
        )
    return mod


def seed_project(
    project_path: str | Path,
    *,
    profile: str = "generic",
    name: str | None = None,
    visibility: str = "private",
    remote_name: str = "gitlab",
    force_ci: bool = False,
    skip_push: bool = False,
    skip_ci: bool = False,
    api: GitLabAPI | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_path).resolve()
    if not project_dir.is_dir():
        raise SystemExit(f"Project path not found: {project_dir}")
    ensure_git_repo(project_dir)

    project_name = name or project_dir.name
    path = _slugify(project_name)
    client = api or GitLabAPI()
    echo(f"==> creating GitLab project '{project_name}' (path={path})")
    project = client.create_project(
        project_name,
        path=path,
        visibility=visibility,
        description=f"Seeded by Fast-Git from {project_dir.name}",
    )
    http_url = client.http_clone_url(project)
    web_url = project.get("web_url", "")
    echo(f"    web: {web_url}")
    echo(f"    git: {http_url}")

    if not skip_ci:
        mod = load_profile(profile)
        ci = mod.render_ci(project_dir)
        if ci:
            write_ci_file(project_dir, ci, force=force_ci)

    set_remote(project_dir, remote_name, http_url)
    if not skip_push:
        # Prefer token auth over interactive password for HTTP remotes
        token = client.token
        auth_url = http_url
        if "://" in http_url:
            # http(s)://oauth2:TOKEN@host/group/project.git
            scheme, rest = http_url.split("://", 1)
            auth_url = f"{scheme}://oauth2:{token}@{rest}"
            set_remote(project_dir, remote_name, auth_url)
        try:
            push_all(project_dir, remote_name)
        finally:
            # Restore clean remote URL without embedded token
            set_remote(project_dir, remote_name, http_url)

    return {
        "name": project.get("name"),
        "path": project.get("path_with_namespace") or path,
        "web_url": web_url,
        "http_url": http_url,
        "id": project.get("id"),
    }
