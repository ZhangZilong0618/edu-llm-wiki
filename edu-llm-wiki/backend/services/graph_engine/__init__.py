"""Learning-graph v2 engine.

Public entry points are re-exported from this package so existing callers
can keep importing ``from services.graph_engine import build_graph``. The
``graph_store`` module owns persistence; the engines under this package are
pure functions of the parsed pages.
"""

from .builder import build_graph, get_node_neighborhood  # noqa: F401
from .insights import generate_learner_insights  # noqa: F401

__all__ = ["build_graph", "get_node_neighborhood", "generate_learner_insights"]
