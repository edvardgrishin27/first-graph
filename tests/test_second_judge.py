"""Тесты инструмента «окупается ли второй судья».

Самый важный тест — не про арифметику сравнения, а про опору: pytest должен
реально отличать верное решение от изъянного. Если он этого не делает, весь
инструмент меряет шум. Поэтому первым делом проверяем именно это.
"""

from __future__ import annotations

import pytest

from first_graph.extras.claude_cli import Reply
from first_graph.extras.judge_cases import (
    ЧИСТЫЕ_И_ИЗЪЯННЫЕ,
    clean_cases,
    flawed_cases,
)
from first_graph.extras.second_judge import (
    Case,
    Comparison,
    JudgeResult,
    Verdict,
    _approved,
    has_flaw,
    judge_flawed,
)

# ─────────────────────────────────────────────────────────────
# ОПОРА: pytest реально отличает верное от изъянного
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", list(ЧИСТЫЕ_И_ИЗЪЯННЫЕ))
def test_изъянное_решение_pytest_ловит(name):
    _, изъянный = ЧИСТЫЕ_И_ИЗЪЯННЫЕ[name]

    assert has_flaw(изъянный) is True, f"тест задачи «{name}» не поймал изъян"


@pytest.mark.parametrize("name", list(ЧИСТЫЕ_И_ИЗЪЯННЫЕ))
def test_верное_решение_pytest_пропускает(name):
    чистый, _ = ЧИСТЫЕ_И_ИЗЪЯННЫЕ[name]

    assert has_flaw(чистый) is False, f"тест задачи «{name}» валит верное решение"


def test_все_четыре_ловушки_действительно_ловушки():
    # Иначе конвейер судил бы «чистые» решения как изъянные.
    assert all(has_flaw(c) for c in flawed_cases())
    assert not any(has_flaw(c) for c in clean_cases())


def test_не_собравшийся_код_это_тоже_изъян():
    сломанный = Case(
        name="битый",
        solution="def scaled(  # синтаксис оборван",
        test="from solution import scaled\ndef test_x(): assert scaled(1,1)==0",
    )

    assert has_flaw(сломанный) is True


# ─────────────────────────────────────────────────────────────
# Чтение вердикта судьи
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["ОДОБРИТЬ", "одобряю", "APPROVE", "OK", "прошло", "PASS"])
def test_одобрение_распознаётся(text):
    assert _approved(text) is True


@pytest.mark.parametrize("text", ["ОТКЛОНИТЬ", "нашёл баг", "REJECT", "", "мусор"])
def test_неодобрение_и_муть_считаются_поймал(text):
    # Отказ в сторону безопасности: невнятный ответ = НЕ одобрил.
    assert _approved(text) is False


# ─────────────────────────────────────────────────────────────
# Сравнение судей и денежный вердикт
# ─────────────────────────────────────────────────────────────


def _судья(одобряет: set[str], цена: float):
    """Заглушка судьи: одобряет случаи из набора (= пропускает их изъян)."""
    def судить(case: Case) -> Reply:
        текст = "ОДОБРИТЬ" if case.name in одобряет else "ОТКЛОНИТЬ"
        return Reply(text=текст, model="stub", cost_usd=цена, duration_ms=1)
    return судить


def _прогон(первый_одобряет, второй_одобряет, цена1=0.02, цена2=0.05) -> Comparison:
    случаи = flawed_cases()
    return judge_flawed(
        случаи,
        first=_судья(первый_одобряет, цена1),
        second=_судья(второй_одобряет, цена2),
        first_label="первый",
        second_label="второй",
        first_model="model-a",
        second_model="model-b",
    )


def test_второй_ловит_то_что_первый_пропустил():
    # Первый пропускает «округление», второй — ловит всё.
    итог = _прогон(первый_одобряет={"округление"}, второй_одобряет=set())

    assert "округление" in итог.second_only
    assert итог.pays_off is True


def test_второй_не_ловит_ничего_сверх_первого():
    # Оба пропускают одно и то же — второй не окупается.
    итог = _прогон(первый_одобряет={"округление"}, второй_одобряет={"округление"})

    assert итог.second_only == set()
    assert итог.pays_off is False


def test_экономика_считается_на_поимках_второго():
    итог = _прогон(первый_одобряет=set(), второй_одобряет=set(), цена2=0.05)

    # Оба поймали всё → второй ничего не добавил → не окупается,
    # хотя формально «поймал много».
    assert итог.pays_off is False
    assert итог.extra_cost == pytest.approx(0.05 * len(итог.flawed_cases))


def test_разбор_складывается_в_общее_число():
    итог = _прогон(первый_одобряет={"округление"}, второй_одобряет={"интервалы"})

    n = len(итог.flawed_cases)
    assert len(итог.both) + len(итог.first_only) + len(итог.second_only) + \
        _пропустили_оба(итог) == n


def _пропустили_оба(итог: Comparison) -> int:
    поймал_хоть_кто = итог.first.caught_set() | итог.second.caught_set()
    return len(set(итог.flawed_cases) - поймал_хоть_кто)


def test_чистые_случаи_в_сравнение_не_попадают():
    # judge_flawed сам отбирает изъянные — подсунем смесь.
    смесь = flawed_cases() + clean_cases()
    итог = judge_flawed(
        смесь,
        first=_судья(set(), 0.01),
        second=_судья(set(), 0.01),
        first_label="a", second_label="b",
        first_model="x", second_model="y",
    )

    # В сравнении только изъянные — их ровно четыре, чистые отсеяны.
    assert len(итог.flawed_cases) == len(flawed_cases())


def test_отчёт_называет_вердикт():
    окупается = _прогон(первый_одобряет={"округление"}, второй_одобряет=set())
    текст = окупается.render()

    assert "окупается" in текст.lower()
    assert "округление" in текст


def test_отчёт_честно_говорит_когда_не_окупается():
    зря = _прогон(первый_одобряет={"округление"}, второй_одобряет={"округление"})
    текст = зря.render()

    assert "зря" in текст.lower()


def test_отчёт_проговаривает_что_не_различает_причину():
    текст = _прогон(первый_одобряет=set(), второй_одобряет=set()).render()

    assert "самопредпочтение" in текст.lower()
    assert "оценка" in текст.lower()
