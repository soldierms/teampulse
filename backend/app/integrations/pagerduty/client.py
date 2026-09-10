from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

BASE_URL = "https://api.pagerduty.com"
PAGE_LIMIT = 100


class PagerDutyError(RuntimeError):
    pass


class PagerDutyClient:
    """Thin REST v2 wrapper. Handles auth, offset pagination and error surfacing;
    all shape-translation lives in mapper.py."""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise PagerDutyError("PagerDuty API key is missing")
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Token token={api_key}",
                "Accept": "application/vnd.pagerduty+json;version=2",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PagerDutyClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._client.get(path, params=params)
        if response.status_code == 401:
            raise PagerDutyError("PagerDuty rejected the API key (401)")
        if response.status_code == 429:
            raise PagerDutyError("PagerDuty rate limit hit (429) — retry this sync later")
        if response.status_code >= 400:
            raise PagerDutyError(
                f"PagerDuty {path} failed: {response.status_code} {response.text[:200]}"
            )
        return response.json()

    def _paginate(
        self, path: str, key: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict]:
        offset = 0
        params = dict(params or {})
        while True:
            params.update({"limit": PAGE_LIMIT, "offset": offset})
            body = self._get(path, params)
            items = body.get(key, [])
            yield from items
            if not body.get("more") or not items:
                return
            offset += len(items)

    def users(self) -> list[dict]:
        return list(self._paginate("/users", "users"))

    def services(self) -> list[dict]:
        return list(self._paginate("/services", "services"))

    def schedules(self) -> list[dict]:
        return list(self._paginate("/schedules", "schedules"))

    def incidents(self, since: datetime, until: datetime) -> list[dict]:
        return list(
            self._paginate(
                "/incidents",
                "incidents",
                {
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "time_zone": "UTC",
                    "statuses[]": ["triggered", "acknowledged", "resolved"],
                },
            )
        )

    def incident_log_entries(self, incident_id: str) -> list[dict]:
        """Notification log entries are the source of truth for who was actually paged."""
        return list(
            self._paginate(
                f"/incidents/{incident_id}/log_entries",
                "log_entries",
                {"is_overview": "false"},
            )
        )

    def oncalls(self, since: datetime, until: datetime) -> list[dict]:
        return list(
            self._paginate(
                "/oncalls",
                "oncalls",
                {"since": since.isoformat(), "until": until.isoformat(), "earliest": "false"},
            )
        )
