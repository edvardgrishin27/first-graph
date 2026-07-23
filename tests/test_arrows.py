"""Тесты детектора фальшивых стрелок.

Главный тест внизу воспроизводит кейс, ради которого всё затевалось:
девять шагов, сорок минут, шесть фальшивых стрелок из восьми.
"""

from __future__ import annotations

import pytest

from first_graph.arrows import (
    PipelineError,
    PipelineStep,
    audit,
    from_dicts,
)


def test_настоящая_стрелка_когда_данные_пересекают():
    steps = [
        PipelineStep(id="извлечь", writes=frozenset({"сырые"})),
        PipelineStep(id="почистить", reads=frozenset({"сырые"}), writes=frozenset({"чистые"})),
    ]

    report = audit(steps)

    assert len(report.arrows) == 1
    assert report.arrows[0].real is True
    assert report.arrows[0].carries == frozenset({"сырые"})
    assert report.fake_arrows == []


def test_фальшивая_стрелка_когда_данные_не_пересекают():
    # Классика: «сделай саммари файла И ПОТОМ проверь погоду».
    # Погода не читает саммари — ребра нет.
    steps = [
        PipelineStep(id="саммари", reads=frozenset({"файл"}), writes=frozenset({"конспект"})),
        PipelineStep(id="погода", writes=frozenset({"прогноз"})),
    ]

    report = audit(steps)

    assert len(report.fake_arrows) == 1
    assert report.fake_arrows[0].source == "саммари"
    assert report.fake_arrows[0].target == "погода"
    # Независимые шаги обязаны оказаться на одном уровне
    assert report.levels == [["саммари", "погода"]]


def test_независимые_шаги_идут_одновременно():
    steps = [
        PipelineStep(id="a", writes=frozenset({"x"}), duration=5),
        PipelineStep(id="b", writes=frozenset({"y"}), duration=5),
        PipelineStep(id="c", writes=frozenset({"z"}), duration=5),
    ]

    report = audit(steps)

    assert report.levels == [["a", "b", "c"]]
    assert report.sequential_time == 15
    assert report.parallel_time == 5
    assert report.speedup == pytest.approx(3.0)


def test_сходящиеся_шаги_ждут_всех_родителей():
    steps = [
        PipelineStep(id="a", writes=frozenset({"x"}), duration=2),
        PipelineStep(id="b", writes=frozenset({"y"}), duration=7),
        PipelineStep(id="слить", reads=frozenset({"x", "y"}), duration=1),
    ]

    report = audit(steps)

    assert report.levels == [["a", "b"], ["слить"]]
    # Критический путь идёт через самую медленную ветку: 7 + 1
    assert report.parallel_time == 8
    assert report.sequential_time == 10


def test_настоящая_цепь_не_ускоряется():
    # Если каждый шаг реально читает предыдущий — распараллеливать нечего.
    # Инструмент обязан честно сказать «ускорения нет», а не выдумать его.
    steps = [
        PipelineStep(id="a", writes=frozenset({"x"}), duration=3),
        PipelineStep(id="b", reads=frozenset({"x"}), writes=frozenset({"y"}), duration=3),
        PipelineStep(id="c", reads=frozenset({"y"}), writes=frozenset({"z"}), duration=3),
    ]

    report = audit(steps)

    assert report.fake_arrows == []
    assert report.speedup == pytest.approx(1.0)
    assert report.levels == [["a"], ["b"], ["c"]]


def test_читает_ближайшего_писателя_а_не_первого():
    steps = [
        PipelineStep(id="первый", writes=frozenset({"v"})),
        PipelineStep(id="перезаписал", writes=frozenset({"v"})),
        PipelineStep(id="читатель", reads=frozenset({"v"})),
    ]

    report = audit(steps)

    # «читатель» увидит значение от «перезаписал», а не от «первый»
    assert report.levels == [["первый", "перезаписал"], ["читатель"]]


def test_ловит_чтение_того_чего_никто_не_писал():
    steps = [
        PipelineStep(id="a", reads=frozenset({"ниоткуда"}), writes=frozenset({"x"})),
        PipelineStep(id="b", reads=frozenset({"x"})),
    ]

    report = audit(steps)

    assert report.unresolved == {"a": frozenset({"ниоткуда"})}


def test_пустой_пайплайн_это_ошибка():
    with pytest.raises(PipelineError, match="пуст"):
        audit([])


def test_повторяющийся_id_это_ошибка():
    steps = [PipelineStep(id="a"), PipelineStep(id="a")]
    with pytest.raises(PipelineError, match="повторяющийся"):
        audit(steps)


def test_отрицательная_длительность_это_ошибка():
    with pytest.raises(PipelineError, match="отрицательная"):
        PipelineStep(id="a", duration=-1)


def test_сборка_из_словарей():
    steps = from_dicts(
        [
            {"id": "a", "writes": ["x"], "duration": 2},
            {"id": "b", "reads": ["x"]},
        ]
    )

    assert steps[0].writes == frozenset({"x"})
    assert steps[0].duration == 2
    assert steps[1].duration == 1.0  # значение по умолчанию


def test_словарь_без_id_это_ошибка():
    with pytest.raises(PipelineError, match="нет поля id"):
        from_dicts([{"writes": ["x"]}])


def test_отчёт_рендерится_и_называет_главное():
    steps = [
        PipelineStep(id="саммари", writes=frozenset({"конспект"})),
        PipelineStep(id="погода", writes=frozenset({"прогноз"})),
    ]

    text = audit(steps).render()

    assert "ФАЛЬШИВАЯ" in text
    assert "одновременно" in text
    assert "Ускорение" in text


# ─────────────────────────────────────────────────────────────────────
# Тот самый кейс: аудит репозитория, девять шагов, сорок минут за ночь.
# Шесть стрелок из девяти оказались фальшивыми — стало четыре минуты.
# Здесь он воспроизведён числами, а не пересказан.
# ─────────────────────────────────────────────────────────────────────


def _ночной_аудит() -> list[PipelineStep]:
    """Девять независимых проверок, которые кто-то выстроил в очередь."""
    независимые = [
        ("линтер", 4.0),
        ("типы", 5.0),
        ("тесты", 12.0),
        ("уязвимости", 6.0),
        ("лицензии", 3.0),
        ("мёртвый_код", 4.0),
        ("размер_бандла", 3.0),
    ]
    steps = [
        PipelineStep(id="клонировать", writes=frozenset({"репо"}), duration=1.0),
    ]
    for name, duration in независимые:
        steps.append(
            PipelineStep(
                id=name,
                reads=frozenset({"репо"}),
                writes=frozenset({f"{name}_итог"}),
                duration=duration,
            )
        )
    steps.append(
        PipelineStep(
            id="отчёт",
            reads=frozenset({f"{name}_итог" for name, _ in независимые}),
            duration=1.0,
        )
    )
    return steps


def test_ночной_аудит_сорок_минут_превращаются_в_четырнадцать():
    report = audit(_ночной_аудит())

    # Шесть стрелок между независимыми проверками — фальшивые.
    # (клонировать→линтер настоящая, ... , размер_бандла→отчёт настоящая)
    assert len(report.fake_arrows) == 6

    # Все семь проверок обязаны оказаться на одном уровне
    assert report.levels[0] == ["клонировать"]
    assert len(report.levels[1]) == 7
    assert report.levels[2] == ["отчёт"]

    # По очереди: 1 + 4+5+12+6+3+4+3 + 1 = 39
    assert report.sequential_time == 39.0
    # По графу: клонировать(1) + самая долгая проверка(12) + отчёт(1) = 14
    assert report.parallel_time == 14.0
    assert report.speedup > 2.7


def test_фальшивые_стрелки_только_между_независимыми_проверками():
    report = audit(_ночной_аудит())

    fake_pairs = {(a.source, a.target) for a in report.fake_arrows}

    # Стрелка от клонирования к первой проверке — настоящая: она несёт «репо»
    assert ("клонировать", "линтер") not in fake_pairs
    # А вот между самими проверками данные не ходят
    assert ("линтер", "типы") in fake_pairs
    assert ("тесты", "уязвимости") in fake_pairs


# ─────────────────────────────────────────────────────────────────────
# Цена ожидания: не всякая фальшивая стрелка стоит денег
# ─────────────────────────────────────────────────────────────────────


def test_фальшивая_стрелка_на_критическом_пути_стоит_времени():
    steps = [
        PipelineStep(id="старт", writes=frozenset({"x"}), duration=1),
        PipelineStep(id="долгий", reads=frozenset({"x"}), writes=frozenset({"a"}), duration=10),
        PipelineStep(id="тоже_долгий", reads=frozenset({"x"}), writes=frozenset({"b"}), duration=10),
    ]

    report = audit(steps)
    дорогая = next(a for a in report.arrows if a.source == "долгий")

    assert дорогая.real is False
    assert дорогая.cost == 10  # ждать зря — ровно длительность соседа
    assert дорогая in report.costly_arrows


def _с_запасом() -> list[PipelineStep]:
    """Ветка B короткая, а критический путь идёт через длинный хвост ветки A.

    Поэтому даже если B зря подождёт A, общий срок не сдвинется — у ветки запас.
    """
    return [
        PipelineStep(id="старт", writes=frozenset({"x"}), duration=1),
        PipelineStep(id="A", reads=frozenset({"x"}), writes=frozenset({"a"}), duration=10),
        PipelineStep(id="B", reads=frozenset({"x"}), writes=frozenset({"b"}), duration=2),
        PipelineStep(id="хвост_A", reads=frozenset({"a"}), writes=frozenset({"c"}), duration=20),
        PipelineStep(id="слить", reads=frozenset({"b", "c"}), duration=1),
    ]


def test_фальшивая_стрелка_на_ветке_с_запасом_бесплатна():
    report = audit(_с_запасом())
    бесплатная = next(a for a in report.arrows if a.source == "A" and a.target == "B")

    assert бесплатная.real is False
    assert бесплатная.cost == 0
    assert бесплатная not in report.costly_arrows


def test_у_настоящих_стрелок_цены_нет():
    steps = [
        PipelineStep(id="a", writes=frozenset({"x"}), duration=3),
        PipelineStep(id="b", reads=frozenset({"x"}), duration=3),
    ]

    assert all(a.cost == 0 for a in audit(steps).arrows if a.real)


def test_отчёт_разделяет_дорогие_и_бесплатные():
    текст = audit(_с_запасом()).render()

    assert "бесплатная" in текст
    assert "реально стоят времени" in текст


def test_кейс_из_ролика_визуальный_план_бесплатен_а_humanizer_нет():
    # Проверено на реальном пайплайне выпуска: находка про визуальный план
    # верна как факт (данные не пересекают стрелку), но общий срок не меняет.
    # Денег стоит соседняя — humanizer за фактчеком.
    import json
    from pathlib import Path

    файл = Path(__file__).resolve().parent.parent / "examples" / "news-release.json"
    steps = from_dicts(json.loads(файл.read_text(encoding="utf-8"))["steps"])
    report = audit(steps)

    визуальный = next(a for a in report.arrows if a.target == "визуальный_план")
    humanizer = next(a for a in report.arrows if a.target == "humanizer")

    assert визуальный.real is False and визуальный.cost == 0
    assert humanizer.real is False and humanizer.cost == 15


# ─────────────────────────────────────────────────────────────────────
# Детектор гонок: два писателя одного ключа на одном уровне
# ─────────────────────────────────────────────────────────────────────


def test_гонка_когда_двое_пишут_один_ключ_параллельно():
    steps = [
        PipelineStep(id="старт", writes=frozenset({"x"}), duration=1),
        PipelineStep(id="A", reads=frozenset({"x"}), writes=frozenset({"общий"}), duration=5),
        PipelineStep(id="B", reads=frozenset({"x"}), writes=frozenset({"общий"}), duration=5),
    ]

    report = audit(steps)

    assert "общий" in report.races
    assert set(report.races["общий"]) == {"A", "B"}


def test_нет_гонки_когда_пишут_разное():
    steps = [
        PipelineStep(id="A", writes=frozenset({"a"}), duration=5),
        PipelineStep(id="B", writes=frozenset({"b"}), duration=5),
    ]

    assert audit(steps).races == {}


def test_нет_гонки_когда_писатели_на_разных_уровнях():
    # Последовательные писатели одного ключа — это перезапись, а не гонка.
    steps = [
        PipelineStep(id="A", writes=frozenset({"x"}), duration=1),
        PipelineStep(id="B", reads=frozenset({"x"}), writes=frozenset({"x"}), duration=1),
    ]

    assert audit(steps).races == {}


def test_гонка_печатается_в_отчёте():
    steps = [
        PipelineStep(id="старт", writes=frozenset({"x"}), duration=1),
        PipelineStep(id="A", reads=frozenset({"x"}), writes=frozenset({"файл"}), duration=5),
        PipelineStep(id="B", reads=frozenset({"x"}), writes=frozenset({"файл"}), duration=5),
    ]

    текст = audit(steps).render()

    assert "ГОНКА" in текст
    assert "файл" in текст


# ─────────────────────────────────────────────────────────────────────
# Честный планировщик: ускорение при лимите работников
# ─────────────────────────────────────────────────────────────────────


def test_один_работник_это_последовательное_время():
    steps = [
        PipelineStep(id="старт", writes=frozenset({"x"}), duration=1),
        PipelineStep(id="A", reads=frozenset({"x"}), writes=frozenset({"a"}), duration=5),
        PipelineStep(id="B", reads=frozenset({"x"}), writes=frozenset({"b"}), duration=5),
    ]

    report = audit(steps)

    # Один работник не может параллелить — время равно сумме длительностей.
    assert report.capped_time(1) == report.sequential_time
    assert report.capped_speedup(1) == pytest.approx(1.0)


def test_лимит_работников_между_один_и_бесконечность():
    # Семь независимых проверок по 3 единицы + обрамление.
    steps = [PipelineStep(id="старт", writes=frozenset({"x"}), duration=1)]
    for i in range(7):
        steps.append(PipelineStep(id=f"p{i}", reads=frozenset({"x"}),
                                  writes=frozenset({f"r{i}"}), duration=3))

    report = audit(steps)

    без_лимита = report.parallel_time
    при_двух = report.capped_time(2)
    при_семи = report.capped_time(7)

    # Чем меньше работников, тем дольше; при семи — как идеально.
    assert report.capped_time(1) > при_двух > при_семи
    assert при_семи == без_лимита


def test_больше_работников_чем_шагов_не_быстрее_идеала():
    steps = [
        PipelineStep(id="A", writes=frozenset({"a"}), duration=4),
        PipelineStep(id="B", writes=frozenset({"b"}), duration=4),
    ]

    report = audit(steps)

    assert report.capped_time(100) == report.parallel_time


def test_ноль_работников_это_ошибка():
    report = audit([PipelineStep(id="a")])

    with pytest.raises(ValueError, match="не меньше 1"):
        report.capped_time(0)
