from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SERVERS_PATH = ROOT / "servers.json"
SAFE_DIR = ROOT / "safe"
REMOTE_DIR = ROOT / "remote"


def expand_path(path: str) -> str:
    """Expand ~ / env vars; resolve relative paths against Fast-Git root."""
    expanded = os.path.expanduser(os.path.expandvars(path))
    p = Path(expanded)
    if not p.is_absolute():
        p = ROOT / p
    return str(p.resolve())


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or SERVERS_PATH
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)


def read_host_file(path: str | Path) -> str:
    """First non-empty, non-comment line from an address .txt file."""
    p = Path(expand_path(str(path)))
    if not p.is_file():
        return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    return ""


def read_token(path: str | Path | None = None) -> str:
    """Read GitLab API token from safe/gitlab.token or GITLAB_TOKEN env."""
    env = (os.environ.get("GITLAB_TOKEN") or "").strip()
    if env:
        return env
    token_path = Path(expand_path(str(path or SAFE_DIR / "gitlab.token")))
    if not token_path.is_file():
        raise SystemExit(
            f"GitLab token not found. Set GITLAB_TOKEN or create {SAFE_DIR / 'gitlab.token'} "
            f"(see safe/gitlab.token.example)."
        )
    for line in token_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    raise SystemExit(f"Token file is empty: {token_path}")


def gitlab_url() -> str:
    """Base GitLab URL (no trailing slash)."""
    url = (os.environ.get("GITLAB_URL") or "").strip().rstrip("/")
    if url:
        return url
    url_file = SAFE_DIR / "gitlab.url"
    if url_file.is_file():
        for line in url_file.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                return text.rstrip("/")
    return "http://127.0.0.1"


def hydrate_server(server: dict[str, Any]) -> dict[str, Any]:
    """Resolve host from host_file (preferred) or inline host."""
    out = dict(server)
    host_file = out.get("host_file")
    if host_file:
        from_file = read_host_file(host_file)
        if from_file:
            out["host"] = from_file
    return out


def list_servers(
    cfg: dict[str, Any] | None = None,
    *,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    data = cfg or load_config()
    defaults = data.get("defaults", {})
    out: list[dict[str, Any]] = []
    for raw in data.get("servers", []):
        server = hydrate_server({**defaults, **raw})
        if not include_disabled and server.get("enabled", True) is False:
            continue
        out.append(server)
    return out


def resolve_targets(
    selector: str,
    *,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    """Resolve 'all', a server id, or a host string matching an entry."""
    servers = list_servers(include_disabled=include_disabled)
    key = selector.strip().lower()
    if key in {"all", "*"}:
        return servers

    by_id = [s for s in servers if s["id"].lower() == key]
    if by_id:
        return by_id

    by_host = [s for s in servers if (s.get("host") or "").lower() == key]
    if by_host:
        return by_host

    known = ", ".join(s["id"] for s in list_servers(include_disabled=True)) or "(none)"
    raise SystemExit(f"Unknown target '{selector}'. Known ids: {known}")


def require_host(server: dict[str, Any]) -> str:
    host = (server.get("host") or "").strip()
    if not host:
        hint = server.get("host_file") or "servers.json host / host_file"
        raise SystemExit(
            f"Server '{server['id']}' has empty host — fill {hint} first."
        )
    return host


def server_from_host(
    host: str,
    *,
    user: str = "ubuntu",
    port: int = 22,
    key: str | None = None,
) -> dict[str, Any]:
    """Build an ad-hoc server dict for `provision <host>` without servers.json."""
    key_path = key or "safe/provision-privatekey.pem"
    return {
        "id": host.replace(".", "-"),
        "host": host,
        "user": user,
        "port": port,
        "key": key_path,
        "enabled": True,
    }
