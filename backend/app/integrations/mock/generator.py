"""Deterministic fake data shaped exactly like PagerDuty and GitHub API responses.

It emits provider-native payloads rather than normalized objects on purpose: the
mock path then runs through the same mappers as production, so the offline
developer experience exercises real translation code.
"""

import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

SEED = 20260909

TEAM_PROFILES = [
    # (key, service/repo label, pages per weekday, after-hours bias, rollback rate, timezone)
    ("platform", "Platform API", 1.4, 0.22, 0.06, "Europe/London"),
    ("payments", "Payments", 3.1, 0.46, 0.19, "America/New_York"),
    ("mobile", "Mobile Gateway", 0.7, 0.12, 0.04, "Africa/Accra"),
]

TEAM_TIMEZONES = {key: tz for key, _label, _r, _ah, _rb, tz in TEAM_PROFILES}

PEOPLE = [
    ("PUSER01", "Ada Okonkwo", "ada@example.com", "platform"),
    ("PUSER02", "Ben Silva", "ben@example.com", "platform"),
    ("PUSER03", "Chi Zhang", "chi@example.com", "platform"),
    ("PUSER04", "Dara Nkemelu", "dara@example.com", "payments"),
    ("PUSER05", "Eli Rosen", "eli@example.com", "payments"),
    ("PUSER06", "Fen Adeyemi", "fen@example.com", "payments"),
    ("PUSER07", "Gia Moretti", "gia@example.com", "mobile"),
    ("PUSER08", "Hana Bello", "hana@example.com", "mobile"),
    ("PUSER09", "Ivo Sørensen", "ivo@example.com", "mobile"),
]

INCIDENT_TITLES = [
    "High error rate on checkout endpoint",
    "p99 latency above SLO",
    "Database connection pool exhausted",
    "Queue depth growing unbounded",
    "Health check failing in eu-west-1",
    "Elevated 5xx from upstream provider",
    "Disk usage above 90%",
    "Certificate expiring in 48 hours",
]


def _service_id(key: str) -> str:
    return f"PSVC{key[:3].upper()}"


def _schedule_id(key: str) -> str:
    return f"PSCH{key[:3].upper()}"


def _repo(key: str) -> str:
    return f"acme/{key}"


def users() -> list[dict]:
    return [
        {"id": pid, "name": name, "email": email, "summary": name, "type": "user"}
        for pid, name, email, _team in PEOPLE
    ]


def services() -> list[dict]:
    return [
        {"id": _service_id(key), "name": label, "summary": label, "type": "service"}
        for key, label, *_ in TEAM_PROFILES
    ]


def schedules() -> list[dict]:
    return [
        {
            "id": _schedule_id(key),
            "name": f"{label} on-call",
            "summary": f"{label} on-call",
            "type": "schedule",
        }
        for key, label, *_ in TEAM_PROFILES
    ]


def repos() -> list[dict]:
    return [{"full_name": _repo(key), "name": key} for key, *_ in TEAM_PROFILES]


def _team_members(team_key: str) -> list[tuple[str, str, str, str]]:
    return [p for p in PEOPLE if p[3] == team_key]


def _local_time(
    rng: random.Random, day: datetime, tz_name: str, hour: int, minute: int
) -> datetime:
    """Builds a wall-clock time in the team's own zone, then converts to UTC —
    otherwise a 09:00 UTC 'business hours' incident is 04:00 in New York and the
    fixture data would look like a permanent after-hours crisis."""
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(tz_name))
    return local.astimezone(UTC)


def _incident_time(
    rng: random.Random, day: datetime, tz_name: str, after_hours_bias: float
) -> datetime:
    """Business-hours incidents cluster in the working day; the rest land at night."""
    if rng.random() < after_hours_bias:
        hour = rng.choice([0, 1, 2, 3, 4, 5, 6, 7, 19, 20, 21, 22, 23])
    else:
        hour = rng.randint(9, 17)
    return _local_time(rng, day, tz_name, hour, rng.randint(0, 59))


def incidents(since: datetime, until: datetime) -> list[dict]:
    rng = random.Random(SEED)
    out: list[dict] = []
    counter = 0
    day = since.replace(hour=0, minute=0, second=0, microsecond=0)

    while day < until:
        for team_key, label, base_rate, ah_bias, _rb, tz_name in TEAM_PROFILES:
            rate = base_rate * (0.55 if day.weekday() >= 5 else 1.0)
            for _ in range(_poisson(rng, rate)):
                counter += 1
                created = _incident_time(rng, day, tz_name, ah_bias)
                if created >= until:
                    continue
                ack_delay = timedelta(minutes=rng.randint(1, 25))
                resolve_delay = ack_delay + timedelta(minutes=rng.randint(4, 320))
                responders = _team_members(team_key)
                primary = rng.choice(responders)
                out.append(
                    {
                        "id": f"PINC{counter:05d}",
                        "incident_number": counter,
                        "title": rng.choice(INCIDENT_TITLES),
                        "status": "resolved",
                        "urgency": "high" if rng.random() < 0.7 else "low",
                        "created_at": created.isoformat().replace("+00:00", "Z"),
                        "last_status_change_at": (created + resolve_delay)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "resolved_at": (created + resolve_delay).isoformat().replace("+00:00", "Z"),
                        "service": {
                            "id": _service_id(team_key),
                            "summary": label,
                            "type": "service",
                        },
                        "priority": {"summary": rng.choice(["P1", "P2", "P3"])},
                        "acknowledgements": [
                            {
                                "at": (created + ack_delay).isoformat().replace("+00:00", "Z"),
                                "acknowledger": {"id": primary[0], "type": "user"},
                            }
                        ],
                        "_mock_responders": [primary[0]]
                        + ([rng.choice(responders)[0]] if rng.random() < 0.3 else []),
                        "_mock_ack_at": (created + ack_delay).isoformat().replace("+00:00", "Z"),
                    }
                )
        day += timedelta(days=1)
    return out


def log_entries(incident: dict) -> list[dict]:
    """Notification + acknowledgement entries for one incident."""
    entries: list[dict] = []
    for idx, user_id in enumerate(dict.fromkeys(incident["_mock_responders"])):
        entries.append(
            {
                "id": f"{incident['id']}-notify-{idx}",
                "type": "notify_log_entry",
                "created_at": incident["created_at"],
                "user": {"id": user_id, "type": "user"},
                "channel": {"type": "push_notification" if idx == 0 else "sms"},
            }
        )
    entries.append(
        {
            "id": f"{incident['id']}-ack-0",
            "type": "acknowledge_log_entry",
            "created_at": incident["_mock_ack_at"],
            "user": {"id": incident["_mock_responders"][0], "type": "user"},
            "channel": {"type": "website"},
        }
    )
    return entries


def oncalls(since: datetime, until: datetime) -> list[dict]:
    """Weekly rotation per team, starting Mondays."""
    out: list[dict] = []
    start = since - timedelta(days=since.weekday())
    start = start.replace(hour=9, minute=0, second=0, microsecond=0)

    for team_key, label, *_ in TEAM_PROFILES:
        members = _team_members(team_key)
        week = start
        idx = 0
        while week < until:
            person = members[idx % len(members)]
            out.append(
                {
                    "start": week.isoformat().replace("+00:00", "Z"),
                    "end": (week + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                    "user": {"id": person[0], "summary": person[1], "type": "user"},
                    "schedule": {
                        "id": _schedule_id(team_key),
                        "summary": f"{label} on-call",
                        "type": "schedule",
                    },
                    "escalation_level": 1,
                }
            )
            week += timedelta(days=7)
            idx += 1
    return out


def deployments(since: datetime, until: datetime) -> list[dict]:
    """GitHub Deployments API shaped payloads, with revert deploys mixed in."""
    rng = random.Random(SEED + 1)
    out: list[dict] = []
    counter = 0
    day = since.replace(hour=0, minute=0, second=0, microsecond=0)

    while day < until:
        if day.weekday() < 5:
            for team_key, _label, _rate, _ah, rollback_rate, tz_name in TEAM_PROFILES:
                for _ in range(rng.randint(0, 4)):
                    counter += 1
                    at = _local_time(rng, day, tz_name, rng.randint(9, 18), rng.randint(0, 59))
                    if at >= until:
                        continue
                    sha = f"{rng.getrandbits(80):020x}"
                    actor = rng.choice(_team_members(team_key))
                    is_rollback = rng.random() < rollback_rate
                    message = (
                        f'Revert "feat: change in {team_key}"'
                        if is_rollback
                        else f"feat: ship {team_key} update"
                    )
                    out.append(
                        {
                            "id": counter,
                            "sha": sha,
                            "ref": "main",
                            "environment": "production",
                            "created_at": at.isoformat().replace("+00:00", "Z"),
                            "updated_at": at.isoformat().replace("+00:00", "Z"),
                            "creator": {"id": 1000 + counter, "login": actor[2].split("@")[0]},
                            "_mock_repo": _repo(team_key),
                            "_mock_state": "success" if rng.random() > 0.05 else "failure",
                            "_mock_message": message,
                            "_mock_pr_number": counter if rng.random() < 0.8 else None,
                        }
                    )
        day += timedelta(days=1)
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth sampler — stdlib random has no Poisson."""
    target = 2.718281828459045**-lam
    k, product = 0, 1.0
    while True:
        product *= rng.random()
        if product <= target:
            return k
        k += 1


def window(days: int = 90) -> tuple[datetime, datetime]:
    until = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return until - timedelta(days=days), until
