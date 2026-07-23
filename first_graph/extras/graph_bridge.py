"""Мост между графом знаний кода и графом агентов.

Слово «граф» в этой волне значит две разные вещи, и их никто не соединил:
  граф знаний — что код собой представляет (что с чем связано);
  граф агентов — кто какую работу делает и в каком порядке.

Здесь они встречаются. Инструмент Graphify (или любой, кто отдаёт node-link
JSON) строит граф знаний репозитория локально, без модели. Мы берём этот граф
и делаем с ним две вещи, которые статьи советуют, но не показывают на деле:

1. РАЗВОРАЧИВАЕМ работу по сообществам, а не по файлам. «По агенту на файл» на
   реальном репозитории — это тысяча агентов. Сообщества (кластеры связанного
   кода) дают десяток осмысленных кусков вместо тысячи алфавитных.

2. ПРОВЕРЯЕМ находки агентов по рёбрам графа. Агент заявил «функция A зовёт
   B» — смотрим, есть ли такое ребро. Нет ребра — находка не подтверждена.
   Это якорь реальности, только для утверждений о структуре кода: правду даёт
   детерминированный парсер, а не ещё одна модель.

Формат входа — обычный node-link JSON (nodes + links), как у graphify-out/
graph.json. Мы читаем ФАЙЛ, а не текстовый вывод CLI: свой парсер — свои
гарантии. Схема Graphify задокументирована и стабильна; если она сменится,
ломается здесь, в одном месте, а не размазано по регуляркам.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

EXTRACTED = "EXTRACTED"  # связь явно есть в исходнике
INFERRED = "INFERRED"    # связь домыслена резолвером графа


class GraphFormatError(ValueError):
    """graph.json не похож на node-link граф."""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    confidence: str  # EXTRACTED или INFERRED

    @property
    def extracted(self) -> bool:
        return self.confidence == EXTRACTED


@dataclass
class Community:
    """Кластер связанного кода — единица работы для одного агента."""

    id: int
    name: str
    node_ids: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.node_ids)


@dataclass
class KnowledgeGraph:
    """Граф знаний кода: узлы, рёбра, сообщества."""

    node_label: dict[str, str]           # id -> человекочитаемая метка
    node_community: dict[str, int]       # id -> номер сообщества
    edges: list[Edge]
    communities: dict[int, Community]

    @property
    def node_count(self) -> int:
        return len(self.node_label)

    def label(self, node_id: str) -> str:
        return self.node_label.get(node_id, node_id)

    def has_edge(self, source: str, target: str) -> Edge | None:
        """Ищет ребро между двумя узлами по id ИЛИ по метке, в обе стороны.

        Агент называет сущности как в коде (метками), а граф хранит id —
        поэтому принимаем оба и не заставляем звонящего знать внутренние id.
        """
        src = self._resolve(source)
        tgt = self._resolve(target)
        if src is None or tgt is None:
            return None
        for edge in self.edges:
            if {edge.source, edge.target} == {src, tgt}:
                return edge
        return None

    def _resolve(self, name: str) -> str | None:
        if name in self.node_label:
            return name
        for node_id, label in self.node_label.items():
            if label == name:
                return node_id
        return None

    def biggest_communities(self, limit: int) -> list[Community]:
        """Крупнейшие сообщества — по ним и разворачиваем работу."""
        ordered = sorted(self.communities.values(), key=lambda c: c.size, reverse=True)
        return ordered[:limit]


def load_graph(path: str | Path) -> KnowledgeGraph:
    """Читает node-link JSON (формат Graphify) в граф знаний."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    if "nodes" not in raw or "links" not in raw:
        raise GraphFormatError(
            "это не node-link граф: нужны разделы nodes и links. "
            "Ожидался graph.json от graphify или совместимый формат."
        )

    node_label: dict[str, str] = {}
    node_community: dict[str, int] = {}
    communities: dict[int, Community] = {}

    for node in raw["nodes"]:
        node_id = str(node.get("id", node.get("label", "")))
        if not node_id:
            continue
        node_label[node_id] = str(node.get("label", node_id))
        comm = node.get("community")
        if comm is not None:
            node_community[node_id] = int(comm)
            сообщество = communities.setdefault(
                int(comm),
                Community(id=int(comm), name=str(node.get("community_name", f"#{comm}"))),
            )
            сообщество.node_ids.append(node_id)

    edges = [
        Edge(
            source=str(link["source"]),
            target=str(link["target"]),
            relation=str(link.get("relation", "")),
            confidence=str(link.get("confidence", INFERRED)),
        )
        for link in raw["links"]
        if "source" in link and "target" in link
    ]

    return KnowledgeGraph(
        node_label=node_label,
        node_community=node_community,
        edges=edges,
        communities=communities,
    )


# ── проверка находок агента по графу ───────────────────────────


@dataclass(frozen=True)
class Claim:
    """Утверждение агента о структуре кода: «A связан с B»."""

    source: str
    target: str
    note: str = ""


@dataclass
class Checked:
    """Находка агента, сверенная с графом."""

    claim: Claim
    edge: Edge | None

    @property
    def confirmed(self) -> bool:
        return self.edge is not None

    @property
    def status(self) -> str:
        if self.edge is None:
            return "НЕ ПОДТВЕРЖДЕНА — такого ребра в графе нет"
        if self.edge.extracted:
            return f"подтверждена ({self.edge.relation}, явно в коде)"
        return f"подтверждена по домыслу ({self.edge.relation}, INFERRED — не факт)"


def verify_claims(graph: KnowledgeGraph, claims: list[Claim]) -> list[Checked]:
    """Сверяет каждое утверждение агента с рёбрами графа.

    Это и есть якорь для находок о структуре: агент может сказать что угодно,
    но ребро либо есть в детерминированно построенном графе, либо нет.
    Подтверждение по INFERRED-ребру помечается отдельно — это домысел резолвера,
    а не факт из исходника.
    """
    return [Checked(claim=c, edge=graph.has_edge(c.source, c.target)) for c in claims]


def render_verification(checked: list[Checked]) -> str:
    confirmed = [c for c in checked if c.confirmed]
    rejected = [c for c in checked if not c.confirmed]
    inferred = [c for c in confirmed if c.edge and not c.edge.extracted]

    lines = ["ПРОВЕРКА НАХОДОК ПО ГРАФУ", ""]
    for c in checked:
        mark = "✓" if c.confirmed else "✗"
        lines.append(f"  {mark} {c.claim.source} → {c.claim.target}: {c.status}")
    lines.append("")
    lines.append(f"ИТОГ: подтверждено {len(confirmed)} из {len(checked)}, "
                 f"отклонено {len(rejected)}")
    if inferred:
        lines.append(f"      из подтверждённых {len(inferred)} держатся на домысле (INFERRED)")
    if rejected:
        lines.append("      отклонённые — кандидаты на галлюцинацию агента")
    return "\n".join(lines)
