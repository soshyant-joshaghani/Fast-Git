"""GitLab REST API helpers for project create/list/remove."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from .config import gitlab_url, read_token


class GitLabAPI:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.base_url = (base_url or gitlab_url()).rstrip("/")
        self.token = token or read_token()
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"PRIVATE-TOKEN": self.token})

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v4{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.session.request(
            method,
            self._url(path),
            timeout=self.timeout,
            **kwargs,
        )
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise SystemExit(
                f"GitLab API {method} {path} failed ({resp.status_code}): {detail}"
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def list_projects(self, *, membership: bool = True) -> list[dict[str, Any]]:
        params = {"per_page": 100, "order_by": "id", "sort": "asc"}
        if membership:
            params["membership"] = "true"
        page = 1
        out: list[dict[str, Any]] = []
        while True:
            params["page"] = page
            batch = self._request("GET", "/projects", params=params)
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out

    def get_project(self, path_or_id: str | int) -> dict[str, Any] | None:
        encoded = quote(str(path_or_id), safe="")
        resp = self.session.get(
            self._url(f"/projects/{encoded}"),
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise SystemExit(
                f"GitLab API GET /projects/{encoded} failed ({resp.status_code}): "
                f"{resp.text[:500]}"
            )
        return resp.json()

    def create_project(
        self,
        name: str,
        *,
        path: str | None = None,
        visibility: str = "private",
        description: str = "",
        initialize_with_readme: bool = False,
    ) -> dict[str, Any]:
        existing = self.get_project(path or name)
        if existing:
            return existing
        payload = {
            "name": name,
            "path": path or name,
            "visibility": visibility,
            "description": description,
            "initialize_with_readme": initialize_with_readme,
        }
        return self._request("POST", "/projects", json=payload)

    def delete_project(self, path_or_id: str | int) -> None:
        encoded = quote(str(path_or_id), safe="")
        self._request("DELETE", f"/projects/{encoded}")

    def http_clone_url(self, project: dict[str, Any]) -> str:
        return project.get("http_url_to_repo") or project.get("web_url", "") + ".git"

    def ssh_clone_url(self, project: dict[str, Any]) -> str:
        return project.get("ssh_url_to_repo") or ""
