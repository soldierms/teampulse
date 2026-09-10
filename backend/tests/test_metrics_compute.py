from datetime import UTC, datetime, time, timedelta

import pytest

from app.metrics.compute import (
    DeployEvent,
    IncidentEvent,
    PageEvent,
    change_failure_rate,
    deploy_metrics,
    on_call_hours,
    page_metrics,
    pages_per_person_per_week,
    percentile,
    resolution_metrics,
)
from app.metrics.config import WorkingHours

HOURS = WorkingHours(
    start=time(9, 0), end=time(18, 0), weekend_days=frozenset({"saturday", "sunday"})
)

WED = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)  # Wednesday midday
WED_NIGHT = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)
SAT = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)  # Saturday midday


def page(at: datetime, user_id: str = "u1", is_ack: bool = False) -> PageEvent:
    return PageEvent(user_id=user_id, paged_at=at, timezone="UTC", is_ack=is_ack)


class TestPercentile:
    def test_nearest_rank_returns_an_observed_value(self):
        values = [float(n) for n in range(1, 11)]
        assert percentile(values, 0.95) == 10.0
        assert percentile(values, 0.5) == 5.0

    def test_single_value(self):
        assert percentile([42.0], 0.95) == 42.0

    def test_empty_is_zero_not_an_error(self):
        assert percentile([], 0.95) == 0.0

    def test_unsorted_input_is_sorted_first(self):
        assert percentile([9.0, 1.0, 5.0], 0.5) == 5.0


class TestPageMetrics:
    def test_counts_and_rates(self):
        pages = [page(WED), page(WED_NIGHT), page(SAT)]
        result = page_metrics(pages, HOURS)

        assert result["pages_total"] == 3
        assert result["pages_after_hours"] == 2  # the 03:00 and the Saturday
        assert result["pages_weekend"] == 1
        assert result["after_hours_page_rate"] == pytest.approx(2 / 3)
        assert result["weekend_page_rate"] == pytest.approx(1 / 3)

    def test_acknowledgements_do_not_count_as_pages(self):
        """Otherwise every page answered by its recipient would count twice."""
        pages = [page(WED_NIGHT), page(WED_NIGHT, is_ack=True)]
        result = page_metrics(pages, HOURS)

        assert result["pages_total"] == 1
        assert result["after_hours_page_rate"] == 1.0

    def test_no_pages_gives_zero_rates_not_division_by_zero(self):
        result = page_metrics([], HOURS)
        assert result["pages_total"] == 0
        assert result["after_hours_page_rate"] == 0.0
        assert result["weekend_page_rate"] == 0.0

    def test_window_rate_is_not_the_mean_of_daily_rates(self):
        """A multi-day rate must come from the counts across the whole window.
        Averaging per-day rates lets a quiet day weigh as much as a brutal one,
        which made the same person read 33% on one screen and 64% on another."""
        busy_day = [page(WED_NIGHT) for _ in range(9)] + [page(WED)]
        quiet_day = [page(datetime(2026, 9, 10, 12, 0, tzinfo=UTC))]

        combined = page_metrics(busy_day + quiet_day, HOURS)
        mean_of_daily = (
            page_metrics(busy_day, HOURS)["after_hours_page_rate"]
            + page_metrics(quiet_day, HOURS)["after_hours_page_rate"]
        ) / 2

        assert combined["after_hours_page_rate"] == pytest.approx(9 / 11)
        assert combined["after_hours_page_rate"] != pytest.approx(mean_of_daily)


class TestPagesPerPersonPerWeek:
    def test_normalises_by_headcount_and_window(self):
        pages = [page(WED, user_id=f"u{i % 2}") for i in range(14)]
        assert pages_per_person_per_week(pages, headcount=2, window_days=7) == pytest.approx(7.0)

    def test_scales_for_a_longer_window(self):
        pages = [page(WED) for _ in range(30)]
        # 30 pages, 3 people, 30 days -> 30 / (3 * 30/7)
        assert pages_per_person_per_week(pages, headcount=3, window_days=30) == pytest.approx(
            30 / (3 * 30 / 7)
        )

    def test_unattributed_pages_are_excluded(self):
        """An unmapped provider identity must not deflate the per-person average."""
        pages = [page(WED, user_id="u1"), PageEvent(None, WED, "UTC")]
        assert pages_per_person_per_week(pages, headcount=1, window_days=7) == pytest.approx(1.0)

    def test_empty_team_is_zero(self):
        assert pages_per_person_per_week([page(WED)], headcount=0, window_days=7) == 0.0


class TestResolutionMetrics:
    def test_mean_and_p95(self):
        incidents = [
            IncidentEvent(WED, WED + timedelta(minutes=10)),
            IncidentEvent(WED, WED + timedelta(minutes=20)),
            IncidentEvent(WED, WED + timedelta(minutes=120)),
        ]
        result = resolution_metrics(incidents)

        assert result["incidents_total"] == 3
        assert result["incidents_resolved"] == 3
        assert result["mean_resolution_minutes"] == pytest.approx(50.0)
        assert result["p95_resolution_minutes"] == pytest.approx(120.0)

    def test_unresolved_incidents_count_but_do_not_skew_duration(self):
        incidents = [IncidentEvent(WED, WED + timedelta(minutes=30)), IncidentEvent(WED, None)]
        result = resolution_metrics(incidents)

        assert result["incidents_total"] == 2
        assert result["incidents_resolved"] == 1
        assert result["mean_resolution_minutes"] == pytest.approx(30.0)

    def test_negative_durations_from_bad_provider_data_are_ignored(self):
        incidents = [IncidentEvent(WED, WED - timedelta(minutes=5))]
        result = resolution_metrics(incidents)
        assert result["incidents_resolved"] == 0
        assert result["mean_resolution_minutes"] == 0.0


class TestDeployMetrics:
    def test_frequency_is_per_week(self):
        deploys = [DeployEvent(WED, "acme/api") for _ in range(10)]
        result = deploy_metrics(deploys, window_days=30)

        assert result["deploys_total"] == 10
        assert result["deploy_frequency_per_week"] == pytest.approx(10 / (30 / 7))

    def test_no_deploys(self):
        result = deploy_metrics([], window_days=7)
        assert result["deploys_total"] == 0
        assert result["deploy_frequency_per_week"] == 0.0


class TestChangeFailureRate:
    def test_deploy_followed_by_a_rollback_counts_as_failed(self):
        deploys = [
            DeployEvent(WED, "acme/api"),
            DeployEvent(WED + timedelta(minutes=30), "acme/api", is_rollback=True),
        ]
        # The first deploy failed; the rollback itself was clean.
        assert change_failure_rate(deploys, [], window_minutes=60) == pytest.approx(0.5)

    def test_rollback_outside_the_window_does_not_count(self):
        deploys = [
            DeployEvent(WED, "acme/api"),
            DeployEvent(WED + timedelta(minutes=90), "acme/api", is_rollback=True),
        ]
        assert change_failure_rate(deploys, [], window_minutes=60) == 0.0

    def test_rollback_in_a_different_repo_does_not_blame_this_deploy(self):
        deploys = [
            DeployEvent(WED, "acme/api"),
            DeployEvent(WED + timedelta(minutes=10), "acme/web", is_rollback=True),
        ]
        assert change_failure_rate(deploys, [], window_minutes=60) == 0.0

    def test_incident_shortly_after_a_deploy_counts_as_failed(self):
        deploys = [DeployEvent(WED, "acme/api")]
        incidents = [IncidentEvent(WED + timedelta(minutes=15), None)]
        assert change_failure_rate(deploys, incidents, window_minutes=60) == 1.0

    def test_incident_at_the_deploy_instant_counts(self):
        deploys = [DeployEvent(WED, "acme/api")]
        incidents = [IncidentEvent(WED, None)]
        assert change_failure_rate(deploys, incidents, window_minutes=60) == 1.0

    def test_incident_beyond_the_window_does_not_count(self):
        deploys = [DeployEvent(WED, "acme/api")]
        incidents = [IncidentEvent(WED + timedelta(minutes=61), None)]
        assert change_failure_rate(deploys, incidents, window_minutes=60) == 0.0

    def test_incident_before_the_deploy_does_not_count(self):
        deploys = [DeployEvent(WED, "acme/api")]
        incidents = [IncidentEvent(WED - timedelta(minutes=5), None)]
        assert change_failure_rate(deploys, incidents, window_minutes=60) == 0.0

    def test_a_failed_deploy_counts_without_needing_a_rollback(self):
        deploys = [DeployEvent(WED, "acme/api", status="failure")]
        assert change_failure_rate(deploys, [], window_minutes=60) == 1.0

    def test_no_deploys_is_zero_not_undefined(self):
        assert change_failure_rate([], [IncidentEvent(WED, None)], window_minutes=60) == 0.0

    def test_mixed_batch(self):
        deploys = [
            DeployEvent(WED, "acme/api"),  # rolled back
            DeployEvent(WED + timedelta(minutes=5), "acme/api", is_rollback=True),
            DeployEvent(WED + timedelta(hours=6), "acme/api"),  # clean
            DeployEvent(WED + timedelta(hours=8), "acme/api", status="failure"),
        ]
        assert change_failure_rate(deploys, [], window_minutes=60) == pytest.approx(0.5)


class TestOnCallHours:
    def test_shift_fully_inside_the_window(self):
        shifts = [(WED, WED + timedelta(hours=8))]
        assert on_call_hours(shifts, WED - timedelta(days=1), WED + timedelta(days=1)) == 8.0

    def test_shift_is_clipped_to_the_window(self):
        """A week-long rotation contributes only the part inside the bucket."""
        shift_start = datetime(2026, 9, 7, tzinfo=UTC)
        shift_end = datetime(2026, 9, 14, tzinfo=UTC)
        window_start = datetime(2026, 9, 9, tzinfo=UTC)
        window_end = datetime(2026, 9, 10, tzinfo=UTC)

        assert on_call_hours([(shift_start, shift_end)], window_start, window_end) == 24.0

    def test_shift_entirely_outside_the_window_contributes_nothing(self):
        shifts = [(WED - timedelta(days=10), WED - timedelta(days=9))]
        assert on_call_hours(shifts, WED, WED + timedelta(days=1)) == 0.0

    def test_multiple_shifts_add_up(self):
        shifts = [
            (WED, WED + timedelta(hours=2)),
            (WED + timedelta(hours=4), WED + timedelta(hours=7)),
        ]
        assert on_call_hours(shifts, WED, WED + timedelta(days=1)) == 5.0
