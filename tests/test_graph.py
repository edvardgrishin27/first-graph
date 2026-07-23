"""Тесты примитивов ядра.

CLAIMS.md поймал дыру: fan_out, router, gate и sequence были покрыты только
косвенно. Если из ролика прозвучит «всё покрыто тестами» — это должно быть
правдой, а не фигурой речи.
"""

from __future__ import annotations

import pytest

from first_graph.graph import (
    GraphError,
    Trace,
    fan_out,
    gate,
    node,
    router,
    sequence,
)


def приплюсовать(ключ: str, значение: str):
    @node(ключ)
    def шаг(state):
        return {**state, ключ: значение}
    return шаг


def упасть(сообщение: str):
    @node("падучий")
    def шаг(state):
        raise RuntimeError(сообщение)
    return шаг


# ── sequence ─────────────────────────────────────────────


def test_цепь_прогоняет_узлы_по_порядку():
    итог = sequence({}, [приплюсовать("a", "1"), приплюсовать("b", "2")])

    assert итог == {"a": "1", "b": "2"}


def test_цепь_пишет_трассу():
    trace = Trace()

    sequence({}, [приплюсовать("a", "1")], trace=trace)

    assert len(trace.steps) == 1
    assert trace.steps[0].name == "a"


def test_падение_узла_в_цепи_называет_виновника():
    trace = Trace()

    with pytest.raises(GraphError, match="падучий"):
        sequence({}, [упасть("ой")], trace=trace)

    assert len(trace.failed) == 1
    assert "ой" in trace.failed[0].error


# ── router ───────────────────────────────────────────────


def test_роутер_ведёт_по_выбранной_ветке():
    итог = router(
        {"вид": "код"},
        choose=lambda s: s["вид"],
        routes={"код": приплюсовать("путь", "кодер"),
                "текст": приплюсовать("путь", "писатель")},
    )

    assert итог["путь"] == "кодер"


def test_одинаковый_вход_всегда_даёт_один_путь():
    # Маршрутизация — код, а не модель: детерминизм обязателен.
    аргументы = dict(
        choose=lambda s: s["вид"],
        routes={"код": приплюсовать("путь", "кодер")},
    )
    пути = {router({"вид": "код"}, **аргументы)["путь"] for _ in range(20)}

    assert пути == {"кодер"}


def test_неизвестный_маршрут_без_запасного_это_ошибка():
    with pytest.raises(GraphError, match="такого маршрута нет"):
        router({"вид": "??"}, choose=lambda s: s["вид"], routes={"код": приплюсовать("a", "1")})


def test_запасной_маршрут_ловит_неизвестное():
    итог = router(
        {"вид": "??"},
        choose=lambda s: s["вид"],
        routes={"код": приплюсовать("путь", "кодер")},
        default=приплюсовать("путь", "запасной"),
    )

    assert итог["путь"] == "запасной"


# ── fan_out ──────────────────────────────────────────────


def test_веер_возвращает_результаты_в_порядке_веток():
    итог = fan_out({}, [приплюсовать("n", "1"), приплюсовать("n", "2"), приплюсовать("n", "3")])

    assert [r["n"] for r in итог] == ["1", "2", "3"]


def test_упавшая_ветка_даёт_None_и_не_роняет_остальные():
    # Восемь хороших результатов — это отчёт, а не ошибка.
    итог = fan_out({}, [приплюсовать("a", "1"), упасть("сломалось"), приплюсовать("c", "3")])

    assert итог[1] is None
    assert [r for r in итог if r is not None] != []
    assert len([r for r in итог if r is not None]) == 2


def test_веер_не_даёт_веткам_видеть_чужие_правки():
    итог = fan_out({"общее": "0"}, [приплюсовать("своё", "a"), приплюсовать("своё", "b")])

    assert "своё" not in {k for r in итог for k in r if r["своё"] == "b"} - {"своё", "общее"}
    assert итог[0]["своё"] == "a" and итог[1]["своё"] == "b"


def test_пустой_веер_это_пустой_список():
    assert fan_out({}, []) == []


def test_веер_пишет_в_трассу_и_успехи_и_отказы():
    trace = Trace()

    fan_out({}, [приплюсовать("a", "1"), упасть("ой")], trace=trace)

    assert len(trace.steps) == 2
    assert len(trace.failed) == 1


# ── gate ─────────────────────────────────────────────────


def test_ворота_пропускают_когда_проверка_прошла():
    _, прошло = gate({}, build=приплюсовать("ответ", "ок"), verify=lambda s: True)

    assert прошло is True


def test_ворота_повторяют_до_предела_и_сдаются():
    попытки = []

    @node("строитель")
    def строитель(state):
        попытки.append(1)
        return state

    _, прошло = gate({}, build=строитель, verify=lambda s: False, max_attempts=3)

    assert прошло is False
    assert len(попытки) == 3  # цикл ограничен сверху, а не крутится вечно


def test_отказ_передаётся_в_следующую_попытку():
    замечания = []

    @node("строитель")
    def строитель(state):
        замечания.append(state.get("замечание"))
        return state

    gate(
        {},
        build=строитель,
        verify=lambda s: False,
        max_attempts=2,
        on_reject=lambda s, n: {**s, "замечание": f"попытка {n}"},
    )

    assert замечания == [None, "попытка 1"]


def test_ноль_попыток_это_ошибка():
    with pytest.raises(ValueError, match="не меньше 1"):
        gate({}, build=приплюсовать("a", "1"), verify=lambda s: True, max_attempts=0)
