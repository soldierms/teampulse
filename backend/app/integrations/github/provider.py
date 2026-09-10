from datetime import datetime
from typing import Any

from app.integrations.base import NormalizedDeploy, NormalizedResource, NormalizedUser
from app.integrations.github import mapper
from app.integrations.github.client import GitHubClient


class GitHubProvider:
    """Implements DeploySource against the live GitHub API.

    Repos are read from config["repos"] when set, otherwise discovered from
    config["org"]. Only repos claimed by a team in team_resources produce
    team-attributed metrics.
    """

    provider = "github"

    def __init__(self, credentials: dict[str, Any], config: dict[str, Any] | None = None) -> None:
        self._client = GitHubClient(credentials.get("access_token", ""))
        self._config = config or {}

    def close(self) -> None:
        self._client.close()

    def _repo_names(self) -> list[str]:
        configured = self._config.get("repos")
        if configured:
            return list(configured)
        org = self._config.get("org")
        return [r["full_name"] for r in self._client.org_repos(org)] if org else []

    def fetch_users(self) -> list[NormalizedUser]:
        org = self._config.get("org")
        if not org:
            return [mapper.map_user(self._client.viewer())]
        return [mapper.map_user(u) for u in self._client.org_members(org)]

    def list_resources(self) -> list[NormalizedResource]:
        org = self._config.get("org")
        if org:
            return [mapper.map_repo(r) for r in self._client.org_repos(org)]
        return [
            NormalizedResource(resource_type="gh_repo", external_id=name, name=name)
            for name in self._config.get("repos", [])
        ]

    def fetch_deploys(self, since: datetime) -> list[NormalizedDeploy]:
        environment = self._config.get("environment", "production")
        deploys: list[NormalizedDeploy] = []

        for repo in self._repo_names():
            for payload in self._client.deployments(repo, environment):
                created = mapper.parse_ts(payload.get("created_at"))
                if created is None or created < since:
                    continue

                state = self._client.deployment_state(repo, payload["id"])
                commit_message = None
                if payload.get("sha"):
                    commit_message = (
                        self._client.commit(repo, payload["sha"]).get("commit") or {}
                    ).get("message")

                pulls = (
                    self._client.pulls_for_commit(repo, payload["sha"])
                    if payload.get("sha")
                    else []
                )
                pr_number = pulls[0]["number"] if pulls else None
                pr_merged_at = pulls[0].get("merged_at") if pulls else None

                deploys.append(
                    mapper.map_deployment(
                        payload,
                        repo_full_name=repo,
                        state=state,
                        commit_message=commit_message,
                        pr_number=pr_number,
                        pr_merged_at=pr_merged_at,
                    )
                )
        return deploys
