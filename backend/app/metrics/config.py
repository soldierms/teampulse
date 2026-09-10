from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings

WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


@dataclass(frozen=True, slots=True)
class WorkingHours:
    start: time
    end: time
    weekend_days: frozenset[str]

    def is_weekend(self, weekday_index: int) -> bool:
        return WEEKDAY_NAMES[weekday_index] in self.weekend_days


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    weight: float
    good: float
    bad: float


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    working_hours: WorkingHours
    change_failure_window_minutes: int
    components: dict[str, ScoreComponent]


def _parse_time(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def load_metrics_config(path: Path | None = None) -> MetricsConfig:
    path = path or get_settings().metrics_config_path
    raw = yaml.safe_load(Path(path).read_text())

    hours = raw.get("working_hours", {})
    weekend = {d.lower() for d in hours.get("weekend_days", ["saturday", "sunday"])}
    unknown = weekend - set(WEEKDAY_NAMES)
    if unknown:
        raise ValueError(f"Unknown weekend_days in metrics config: {sorted(unknown)}")

    components = {
        key: ScoreComponent(
            weight=float(cfg["weight"]), good=float(cfg["good"]), bad=float(cfg["bad"])
        )
        for key, cfg in (raw.get("toil_score", {}).get("components", {}) or {}).items()
    }

    return MetricsConfig(
        working_hours=WorkingHours(
            start=_parse_time(hours.get("start", "09:00")),
            end=_parse_time(hours.get("end", "18:00")),
            weekend_days=frozenset(weekend),
        ),
        change_failure_window_minutes=int(raw.get("change_failure", {}).get("window_minutes", 60)),
        components=components,
    )


@lru_cache
def get_metrics_config() -> MetricsConfig:
    return load_metrics_config()
