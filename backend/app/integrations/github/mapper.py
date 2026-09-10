"""Pure GitHub payload -> normalized shape translation."""

import re
from datetime import UTC, datetime

from app.integrations.base import GH_REPO, NormalizedDeploy, NormalizedResource, NormalizedUser

# Matches `Revert "..."`, `revert: ...`, `rollback ...` — the conventions teams
# actually use. Deliberately anchored so "reverted-to-baseline" in a feature
# description doesn't count.
ROLLBACK_PATTERN = re.compile(r"^\s*(revert|rollback)\b", re.IGNORECASE)
REVERTS_SHA_PATTERN = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.IGNORECASE)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def is_rollback(commit_message: str | None) -> bool:
    return bool(commit_message and ROLLBACK_PATTERN.match(commit_message))


def reverted_sha(commit_message: str | None) -> str | None:
    if not commit_message:
        return None
    match = REVERTS_SHA_PATTERN.search(commit_message)
    return match.group(1) if match else None


def map_user(payload: dict) -> NormalizedUser:
    return NormalizedUser(
        external_id=str(payload["id"]),
        handle=payload.get("login"),
        email=(payload.get("email") or "").lower() or None,
        name=payload.get("name") or payload.get("login"),
    )


def map_repo(payload: dict) -> NormalizedResource:
    return NormalizedResource(
        resource_type=GH_REPO,
        external_id=payload["full_name"],
        name=payload["full_name"],
    )


def map_deployment(
    payload: dict,
    repo_full_name: str,
    state: str = "success",
    commit_message: str | None = None,
    pr_number: int | None = None,
    pr_merged_at: str | None = None,
) -> NormalizedDeploy:
    """`state` comes from the deployment's latest status, which is a separate
    GitHub endpoint — the caller resolves it and passes it in."""
    rollback = is_rollback(commit_message)
    return NormalizedDeploy(
        external_id=f"{repo_full_name}:{payload['id']}",
        repo_full_name=repo_full_name,
        deployed_at=parse_ts(payload.get("created_at")),
        status="success" if state in ("success", "active") else "failure",
        environment=payload.get("environment"),
        sha=payload.get("sha"),
        ref=payload.get("ref"),
        actor_external_id=str((payload.get("creator") or {}).get("id") or "") or None,
        pr_number=pr_number,
        pr_merged_at=parse_ts(pr_merged_at),
        is_rollback=rollback,
        reverts_sha=reverted_sha(commit_message),
        raw=payload,
    )
