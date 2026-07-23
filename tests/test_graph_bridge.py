"""Тесты моста между графом знаний кода и графом агентов.

Главное здесь — проверка находок по графу: агент может заявить что угодно,
а ребро либо есть в детерминированно построенном графе, либо нет. Это якорь
реальности для утверждений о структуре кода.

Тесты гоняются и на синтетике, и на РЕАЛЬНОЙ фикстуре — куске graph.json,
построенного Graphify на репозитории requests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from first_graph.extras.graph_bridge import (
    Claim,
    GraphFormatError,
    KnowledgeGraph,
    load_graph,
    render_verification,
    verify_claims,
)

ФИКСТУРА = Path(__file__).resolve().parent / "fixtures" / "graph_sample.json"


def _мини_граф(tmp_path, nodes, links) -> KnowledgeGraph:
    файл = tmp_path / "g.json"
    файл.write_text(json.dumps({"nodes": nodes, "links": links}), encoding="utf-8")
    return load_graph(файл)


# ─────────────────────────────────────────────────────────────
# Чтение формата
# ─────────────────────────────────────────────────────────────


def test_читает_node_link_формат(tmp_path):
    граф = _мини_граф(
        tmp_path,
        nodes=[
            {"id": "a", "label": "A.py", "community": 1, "community_name": "ядро"},
            {"id": "b", "label": "B.py", "community": 1, "community_name": "ядро"},
        ],
        links=[{"source": "a", "target": "b", "relation": "imports",
                "confidence": "EXTRACTED"}],
    )

    assert граф.node_count == 2
    assert граф.label("a") == "A.py"
    assert len(граф.edges) == 1


def test_не_node_link_это_ошибка(tmp_path):
    файл = tmp_path / "bad.json"
    файл.write_text(json.dumps({"что-то": "другое"}), encoding="utf-8")

    with pytest.raises(GraphFormatError, match="node-link"):
        load_graph(файл)


def test_узлы_группируются_в_сообщества(tmp_path):
    граф = _мини_граф(
        tmp_path,
        nodes=[
            {"id": "a", "label": "A", "community": 1, "community_name": "ядро"},
            {"id": "b", "label": "B", "community": 1, "community_name": "ядро"},
            {"id": "c", "label": "C", "community": 2, "community_name": "тесты"},
        ],
        links=[],
    )

    assert len(граф.communities) == 2
    assert граф.communities[1].size == 2
    assert граф.communities[1].name == "ядро"


def test_разворот_по_крупнейшим_сообществам(tmp_path):
    nodes = (
        [{"id": f"a{i}", "label": f"A{i}", "community": 1, "community_name": "большое"}
         for i in range(5)]
        + [{"id": f"b{i}", "label": f"B{i}", "community": 2, "community_name": "малое"}
           for i in range(2)]
    )
    граф = _мини_граф(tmp_path, nodes, links=[])

    топ = граф.biggest_communities(1)

    assert len(топ) == 1
    assert топ[0].name == "большое"
    assert топ[0].size == 5


# ─────────────────────────────────────────────────────────────
# ЯКОРЬ: проверка находок по графу
# ─────────────────────────────────────────────────────────────


def test_находка_подтверждается_если_ребро_есть(tmp_path):
    граф = _мини_граф(
        tmp_path,
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        links=[{"source": "a", "target": "b", "relation": "calls",
                "confidence": "EXTRACTED"}],
    )

    [итог] = verify_claims(граф, [Claim("a", "b")])

    assert итог.confirmed is True
    assert "явно в коде" in итог.status


def test_находка_отклоняется_если_ребра_нет(tmp_path):
    # Агент заявил связь, которой в графе нет — кандидат на галлюцинацию.
    граф = _мини_граф(
        tmp_path,
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        links=[],
    )

    [итог] = verify_claims(граф, [Claim("a", "b")])

    assert итог.confirmed is False
    assert "НЕ ПОДТВЕРЖДЕНА" in итог.status


def test_подтверждение_по_домыслу_помечается_отдельно(tmp_path):
    # INFERRED-ребро — домысел резолвера, не факт из исходника.
    граф = _мини_граф(
        tmp_path,
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        links=[{"source": "a", "target": "b", "relation": "uses",
                "confidence": "INFERRED"}],
    )

    [итог] = verify_claims(граф, [Claim("a", "b")])

    assert итог.confirmed is True
    assert "INFERRED" in итог.status


def test_находку_можно_называть_метками_а_не_id(tmp_path):
    # Агент знает сущности как в коде (метки), а не внутренние id графа.
    граф = _мини_граф(
        tmp_path,
        nodes=[{"id": "src_a", "label": "adapters.py"},
               {"id": "src_b", "label": "models.py"}],
        links=[{"source": "src_a", "target": "src_b", "relation": "imports",
                "confidence": "EXTRACTED"}],
    )

    [итог] = verify_claims(граф, [Claim("adapters.py", "models.py")])

    assert итог.confirmed is True


def test_ребро_ищется_в_обе_стороны(tmp_path):
    граф = _мини_граф(
        tmp_path,
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        links=[{"source": "a", "target": "b", "relation": "calls",
                "confidence": "EXTRACTED"}],
    )

    # спросили b→a, а ребро a→b — всё равно найдено
    [итог] = verify_claims(граф, [Claim("b", "a")])

    assert итог.confirmed is True


def test_отчёт_считает_подтверждённые_и_отклонённые(tmp_path):
    граф = _мини_граф(
        tmp_path,
        nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
               {"id": "c", "label": "C"}],
        links=[{"source": "a", "target": "b", "relation": "calls",
                "confidence": "EXTRACTED"}],
    )

    checked = verify_claims(граф, [Claim("a", "b"), Claim("a", "c")])
    текст = render_verification(checked)

    assert "подтверждено 1 из 2" in текст
    assert "галлюцинац" in текст.lower()


# ─────────────────────────────────────────────────────────────
# На РЕАЛЬНОМ графе (Graphify на requests)
# ─────────────────────────────────────────────────────────────


def test_реальный_граф_читается():
    граф = load_graph(ФИКСТУРА)

    assert граф.node_count == 60
    assert len(граф.edges) > 0
    assert len(граф.communities) > 0


def test_реальное_ребро_подтверждается():
    # Из фикстуры: docs_conf импортирует src_requests_init (EXTRACTED).
    граф = load_graph(ФИКСТУРА)

    [итог] = verify_claims(граф, [Claim("docs_conf", "src_requests_init")])

    assert итог.confirmed is True
    assert итог.edge.relation == "imports"


def test_выдуманное_ребро_на_реальном_графе_отклоняется():
    граф = load_graph(ФИКСТУРА)

    # такой связи в requests нет
    [итог] = verify_claims(граф, [Claim("docs_conf", "flask_theme_support.py")])

    assert итог.confirmed is False


def test_реальные_метки_EXTRACTED_и_INFERRED_на_месте():
    граф = load_graph(ФИКСТУРА)

    метки = {e.confidence for e in граф.edges}

    # в графе Graphify обе метки должны встречаться
    assert метки <= {"EXTRACTED", "INFERRED"}
    assert "EXTRACTED" in метки
