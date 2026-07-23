"""Граф знаний решает, как делить работу, и он же проверяет находки.

Слово «граф» в этой волне значит две разные вещи — граф знаний кода и граф
агентов. Их никто не соединил. Это демо соединяет.

    python3 examples/graph_bridge_demo.py

Работает на готовой фикстуре — куске graph.json, построенного Graphify на
репозитории requests. Свой граф строится так:

    pip install graphifyy        # внимание: две «y»
    graphify .                   # локально, без модели, ~2 минуты

Ничего не выдумывается: рёбра берутся из реального графа, метки EXTRACTED/
INFERRED — как их проставил детерминированный парсер Graphify.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from first_graph.extras.graph_bridge import (  # noqa: E402
    Claim,
    load_graph,
    render_verification,
    verify_claims,
)

ФИКСТУРА = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "graph_sample.json"


def main() -> int:
    if not ФИКСТУРА.exists():
        print("нет фикстуры graph_sample.json — запустите из репозитория")
        return 2

    граф = load_graph(ФИКСТУРА)

    print("ГРАФ ЗНАНИЙ (Graphify на requests, кусок для демо)")
    print(f"  узлов: {граф.node_count}, рёбер: {len(граф.edges)}, "
          f"сообществ: {len(граф.communities)}\n")

    # ── Половина первая: как делить работу ──
    print("КАК РАЗДАТЬ РАБОТУ АГЕНТАМ")
    print("  «по агенту на файл» = по агенту на каждый из "
          f"{граф.node_count} узлов — расточительно.")
    print("  По сообществам — куски связанного кода:")
    for c in граф.biggest_communities(4):
        print(f"    {c.name}: {c.size} узлов  → один агент")
    print()

    # ── Половина вторая: проверка находок по графу ──
    print("АГЕНТ ВЕРНУЛ НАХОДКИ О СТРУКТУРЕ — СВЕРЯЕМ С ГРАФОМ")
    находки = [
        Claim("docs_conf", "src_requests_init", "агент: conf импортирует requests"),
        Claim("src_requests_adapters", "src_requests_init", "агент: adapters тянет из init"),
        Claim("docs_conf", "flask_theme_support.py", "агент: conf зовёт flask-тему"),
    ]
    checked = verify_claims(граф, находки)
    print(render_verification(checked))
    print()

    отсеяно = [c for c in checked if not c.confirmed]
    print("СМЫСЛ")
    print("  Граф знаний дважды поработал в одном прогоне:")
    print("  — подсказал, как делить работу (по сообществам, не по файлам);")
    print(f"  — отсеял {len(отсеяно)} находку агента, которой в коде нет.")
    print("  Проверку сделал детерминированный парсер, а не вторая модель.")
    print("  Это якорь реальности — только для утверждений о структуре кода.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
