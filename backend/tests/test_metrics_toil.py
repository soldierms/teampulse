from datetime import time
from pathlib import Path

import pytest

from app.metrics.config import MetricsConfig, ScoreComponent, WorkingHours, load_metrics_config
from app.metrics.toil import component_score, toil_score

BACKEND_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ScoreComponent(weight=1.0, good=0.0, bad=0.5)


def config_with(components: dict[str, ScoreComponent]) -> MetricsConfig:
    return MetricsConfig(
        working_hours=WorkingHours(
            start=time(9), end=time(18), weekend_days=frozenset({"saturday", "sunday"})
        ),
        change_failure_window_minutes=60,
        components=components,
    )


class TestComponentScore:
    def test_at_or_below_good_is_zero_toil(self):
        assert component_score(0.0, COMPONENT) == 0.0
        assert component_score(-1.0, COMPONENT) == 0.0

    def test_at_or_above_bad_is_full_toil(self):
        assert component_score(0.5, COMPONENT) == 100.0
        assert component_score(5.0, COMPONENT) == 100.0

    def test_midpoint_is_fifty(self):
        assert component_score(0.25, COMPONENT) == pytest.approx(50.0)

    def test_degenerate_range_does_not_divide_by_zero(self):
        assert component_score(3.0, ScoreComponent(weight=1.0, good=2.0, bad=2.0)) == 0.0

    def test_inverted_component_where_higher_is_healthier(self):
        """good > bad means a falling value is worse — e.g. deploy frequency."""
        inverted = ScoreComponent(weight=1.0, good=10.0, bad=0.0)
        assert component_score(10.0, inverted) == 0.0
        assert component_score(0.0, inverted) == 100.0
        assert component_score(5.0, inverted) == pytest.approx(50.0)


class TestToilScore:
    def test_weighted_average_of_components(self):
        config = config_with(
            {
                "after_hours_page_rate": ScoreComponent(weight=0.75, good=0.0, bad=1.0),
                "change_failure_rate": ScoreComponent(weight=0.25, good=0.0, bad=1.0),
            }
        )
        # 0.4 -> 40 toil at weight .75; 0.8 -> 80 toil at weight .25
        score = toil_score({"after_hours_page_rate": 0.4, "change_failure_rate": 0.8}, config)
        assert score == pytest.approx(40 * 0.75 + 80 * 0.25)

    def test_missing_components_are_renormalised_not_treated_as_zero(self):
        """A team with no GitHub connection should still get a real on-call
        score rather than one dragged toward zero by absent deploy data."""
        config = config_with(
            {
                "after_hours_page_rate": ScoreComponent(weight=0.5, good=0.0, bad=1.0),
                "change_failure_rate": ScoreComponent(weight=0.5, good=0.0, bad=1.0),
            }
        )
        score = toil_score({"after_hours_page_rate": 0.6}, config)
        assert score == pytest.approx(60.0)

    def test_no_data_at_all_is_zero(self):
        config = config_with({"after_hours_page_rate": COMPONENT})
        assert toil_score({}, config) == 0.0

    def test_extra_values_without_a_configured_weight_are_ignored(self):
        config = config_with({"after_hours_page_rate": ScoreComponent(1.0, 0.0, 1.0)})
        score = toil_score({"after_hours_page_rate": 0.3, "pages_total": 999}, config)
        assert score == pytest.approx(30.0)

    def test_score_stays_within_bounds(self):
        config = config_with(
            {
                "after_hours_page_rate": ScoreComponent(weight=0.5, good=0.0, bad=0.5),
                "change_failure_rate": ScoreComponent(weight=0.5, good=0.0, bad=0.3),
            }
        )
        worst = toil_score({"after_hours_page_rate": 1.0, "change_failure_rate": 1.0}, config)
        best = toil_score({"after_hours_page_rate": 0.0, "change_failure_rate": 0.0}, config)
        assert worst == pytest.approx(100.0)
        assert best == 0.0


class TestShippedConfig:
    def test_metrics_yaml_loads(self):
        config = load_metrics_config(BACKEND_ROOT / "metrics.yaml")
        assert config.components
        assert config.change_failure_window_minutes == 60

    def test_shipped_weights_sum_to_one(self):
        config = load_metrics_config(BACKEND_ROOT / "metrics.yaml")
        total = sum(c.weight for c in config.components.values())
        assert total == pytest.approx(1.0)

    def test_after_hours_and_change_failure_carry_the_most_weight(self):
        """The brief calls for these two to dominate — assert it so a future
        retune cannot quietly invert the product's point of view."""
        config = load_metrics_config(BACKEND_ROOT / "metrics.yaml")
        ranked = sorted(config.components.items(), key=lambda kv: kv[1].weight, reverse=True)
        assert {ranked[0][0], ranked[1][0]} == {"after_hours_page_rate", "change_failure_rate"}

    def test_unknown_weekend_day_is_rejected(self, tmp_path):
        bad = tmp_path / "metrics.yaml"
        bad.write_text("working_hours:\n  weekend_days: [caturday]\n")
        with pytest.raises(ValueError, match="caturday"):
            load_metrics_config(bad)
