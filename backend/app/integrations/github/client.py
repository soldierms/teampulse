from collections.abc import Iterator
from typing import Any

import httpx

BASE_URL = "https://api.github.com"
PAGE_SIZE = 100


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise GitHubError("GitHub token is missing")
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        response = self._client.get(path, params=params)
        if response.status_code == 401:
            raise GitHubError("GitHub rejected the token (401)")
        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise GitHubError("GitHub rate limit hit — retry this sync later")
        if response.status_code >= 400:
            raise GitHubError(f"GitHub {path} failed: {response.status_code} {response.text[:200]}")
        return response

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        page = 1
        params = dict(params or {})
        while True:
            params.update({"per_page": PAGE_SIZE, "page": page})
            items = self._get(path, params).json()
            if not items:
                return
            yield from items
            if len(items) < PAGE_SIZE:
                return
            page += 1

    def viewer(self) -> dict:
        return self._get("/user").json()

    def org_repos(self, org: str) -> list[dict]:
        return list(self._paginate(f"/orgs/{org}/repos", {"type": "all", "sort": "pushed"}))

    def org_members(self, org: str) -> list[dict]:
        return list(self._paginate(f"/orgs/{org}/members"))

    def deployments(self, repo_full_name: str, environment: str | None = None) -> list[dict]:
        params = {"environment": environment} if environment else None
        return list(self._paginate(f"/repos/{repo_full_name}/deployments", params))

    def deployment_state(self, repo_full_name: str, deployment_id: int) -> str:
        statuses = self._get(
            f"/repos/{repo_full_name}/deployments/{deployment_id}/statuses",
            {"per_page": 1},
        ).json()
        return statuses[0]["state"] if statuses else "pending"

    def commit(self, repo_full_name: str, sha: str) -> dict:
        return self._get(f"/repos/{repo_full_name}/commits/{sha}").json()

    def pulls_for_commit(self, repo_full_name: str, sha: str) -> list[dict]:
        return self._get(f"/repos/{repo_full_name}/commits/{sha}/pulls").json()
