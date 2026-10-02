"""Compatibility facade; logic lives in collector, analyzer and presentation."""
from .burden_analyzer import EPSILON, METRICS, analyze
from .burden_collector import collect


def build(design, observations, report, submitted=None):
    """Collect observations and analyze against the original recomputed report."""
    return analyze(collect(design, observations, submitted), report)


def markdown(view):
    """Preserve the old rendering entry without loading presentation for build."""
    from .burden_presentation import markdown as render_markdown
    return render_markdown(view)
