"""first-graph — ваш первый граф агентов, без фреймворка.

Два модуля:
  graph  — четыре примитива: узел, ребро, роутер, состояние
  arrows  — детектор фальшивых стрелок: где пайплайн ждёт зря
  anchors — якорь реальности: проверка, которую нельзя обмануть словами
"""

from first_graph.anchors import Evidence, anchor
from first_graph.arrows import Arrow, PipelineStep, Report, audit, from_dicts
from first_graph.graph import (
    GraphError,
    Node,
    State,
    Trace,
    fan_out,
    gate,
    node,
    router,
    sequence,
)

__version__ = "0.1.0"

__all__ = [
    "Arrow",
    "Evidence",
    "GraphError",
    "Node",
    "PipelineStep",
    "Report",
    "State",
    "Trace",
    "anchor",
    "audit",
    "fan_out",
    "from_dicts",
    "gate",
    "node",
    "router",
    "sequence",
]
