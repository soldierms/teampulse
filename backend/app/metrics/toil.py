from app.metrics.config import MetricsConfig, ScoreComponent

TOIL_METRIC_KEY = "toil_score"


def component_score(value: float, component: ScoreComponent) -> float:
    """Linear 0-100 between `good` and `bad`, clamped outside that range.
    Supports inverted components where a higher raw value is healthier."""
    span = component.bad - component.good
    if span == 0:
        return 0.0
    ratio = (value - component.good) / span
    return max(0.0, min(1.0, ratio)) * 100


def toil_score(values: dict[str, float], config: MetricsConfig) -> float:
    """Weighted mean of the configured components, renormalised over the
    components we actually have data for — a team with no GitHub connection
    still gets a meaningful on-call score instead of one dragged toward zero."""
    present = {
        key: component
        for key, component in config.components.items()
        if key in values and values[key] is not None
    }
    total_weight = sum(c.weight for c in present.values())
    if not present or total_weight == 0:
        return 0.0

    weighted = sum(component_score(values[key], c) * c.weight for key, c in present.items())
    return weighted / total_weight
