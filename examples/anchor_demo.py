"""Агенты согласились. Реальность — нет.

Демонстрация якоря: два агента отчитываются об успехе, третий их
подтверждает — и все трое ошибаются, потому что никто не запускал тесты.
Якорь запускает их сам.

    python3 examples/anchor_demo.py

Ничего не мокается: pytest запускается по-настоящему, на настоящем коде
с настоящей ошибкой, которую этот скрипт создаёт во временной папке.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from first_graph.anchors import anchor  # noqa: E402
from first_graph.graph import Trace  # noqa: E402

# Код с ошибкой: скидка 20% посчитана как умножение на 0.2 вместо 0.8.
# Ровно та ошибка, которую агент «просмотрит», а тест поймает.
СЛОМАННЫЙ_КОД = '''
def цена_со_скидкой(цена: float, скидка_процентов: float) -> float:
    return цена * (скидка_процентов / 100)
'''

ТЕСТ = '''
from товар import цена_со_скидкой

def test_скидка_20_процентов_оставляет_80():
    assert цена_со_скидкой(1000, 20) == 800
'''


def агент_разработчик(state: dict) -> dict:
    """Написал код и уверен в нём."""
    print("  🤖 разработчик: функция готова, логика скидки простая — всё верно ✓")
    return {**state, "код_готов": True}


def агент_ревьюер(state: dict) -> dict:
    """Прочитал отчёт разработчика и согласился."""
    print("  🤖 ревьюер:     посмотрел код, замечаний нет, тесты должны проходить ✓")
    return {**state, "ревью_пройдено": True}


def агент_тимлид(state: dict) -> dict:
    """Прочитал обоих и подтвердил."""
    print("  🤖 тимлид:      оба подтвердили, забираем в релиз ✓")
    return {**state, "одобрено": True}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        проект = Path(tmp)
        (проект / "товар.py").write_text(СЛОМАННЫЙ_КОД, encoding="utf-8")
        (проект / "test_товар.py").write_text(ТЕСТ, encoding="utf-8")

        trace = Trace()
        state: dict = {"задача": "скидка на товар"}

        print("\nЧТО ГОВОРЯТ АГЕНТЫ")
        for шаг in (агент_разработчик, агент_ревьюер, агент_тимлид):
            state = шаг(state)

        все_согласны = all(
            state.get(k) for k in ("код_готов", "ревью_пройдено", "одобрено")
        )
        print(f"\n  Единогласно: {'ДА' if все_согласны else 'нет'} — три из трёх ✓")

        print("\nЧТО ГОВОРИТ РЕАЛЬНОСТЬ")
        state, прошло = anchor(
            state,
            command=[sys.executable, "-m", "pytest", "-q", "--no-header"],
            cwd=проект,
            trace=trace,
        )
        print(f"  ⚓ {state['anchors'][-1]}")

        print()
        if прошло:
            print("  Якорь подтвердил. Можно дальше.")
            return 0

        print("  ⛔ ГРАФ ОСТАНОВЛЕН")
        print()
        print("  Три агента сказали «готово». Ни один не запускал тесты.")
        print("  Якорь запустил — и нашёл ошибку в расчёте скидки.")
        print()
        print("  Агенты согласились. Реальность — нет.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
