"""Четыре примитива графа агентов.

Весь «graph engineering» стоит на четырёх вещах: узел, ребро, роутер и состояние.
Фреймворк для этого не нужен — нужны функции, словарь и условия.

Этот модуль — рабочая реализация этих четырёх примитивов, а не псевдокод.
Он намеренно маленький: его можно прочитать целиком за пять минут.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

# Состояние — обычный словарь, который течёт по рёбрам.
# Каждый узел читает из него и пишет в него.
State = dict[str, Any]

# Узел — функция: состояние на входе, состояние на выходе.
# Узел не знает, что было до него и что будет после. Он знает только свою работу.
Node = Callable[[State], State]

DEFAULT_MAX_WORKERS = 8


class GraphError(RuntimeError):
    """Ошибка исполнения графа, которую видно снаружи."""


@dataclass
class Step:
    """Один шаг прогона — для трассировки execution graph."""

    name: str
    ok: bool
    error: str | None = None


@dataclass
class Trace:
    """Execution graph: что реально произошло, в отличие от того, что могло."""

    steps: list[Step] = field(default_factory=list)

    def record(self, name: str, ok: bool, error: str | None = None) -> None:
        self.steps.append(Step(name=name, ok=ok, error=error))

    @property
    def failed(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def __str__(self) -> str:
        lines = []
        for step in self.steps:
            mark = "✓" if step.ok else "✗"
            suffix = f" — {step.error}" if step.error else ""
            lines.append(f"  {mark} {step.name}{suffix}")
        return "\n".join(lines)


def node(name: str) -> Callable[[Node], Node]:
    """Помечает функцию как узел и даёт ей имя для трассировки."""

    def decorator(func: Node) -> Node:
        func.node_name = name  # type: ignore[attr-defined]
        return func

    return decorator


def name_of(fn: Node) -> str:
    return getattr(fn, "node_name", getattr(fn, "__name__", "node"))


def sequence(state: State, nodes: Sequence[Node], trace: Trace | None = None) -> State:
    """Последовательная цепь: A → B → C.

    Самый простой граф. Годится, только когда каждый шаг реально читает вывод
    предыдущего. Если это не так — половина ожиданий здесь лишняя, и это ловит
    модуль `arrows`.
    """
    for fn in nodes:
        try:
            state = fn(state)
            if trace:
                trace.record(name_of(fn), ok=True)
        except Exception as exc:  # noqa: BLE001 — узел не должен ронять весь граф молча
            if trace:
                trace.record(name_of(fn), ok=False, error=str(exc))
            raise GraphError(f"узел {name_of(fn)} упал: {exc}") from exc
    return state


def router(
    state: State,
    choose: Callable[[State], str],
    routes: dict[str, Node],
    default: Node | None = None,
) -> State:
    """Роутер: смотрит состояние и выбирает путь.

    Решение может принимать модель, но САМА маршрутизация — код. Поэтому
    одинаковая классификация всегда даёт один и тот же путь: никаких сюрпризов
    «модель решила пропустить проверку» — пропуск пришлось бы вписать в граф.
    """
    key = choose(state)
    target = routes.get(key, default)
    if target is None:
        raise GraphError(
            f"роутер вернул «{key}», но такого маршрута нет "
            f"и запасной не задан (есть: {', '.join(sorted(routes))})"
        )
    return target(state)


def fan_out(
    state: State,
    branches: Iterable[Node],
    max_workers: int = DEFAULT_MAX_WORKERS,
    trace: Trace | None = None,
) -> list[State | None]:
    """Веер: независимые узлы работают одновременно.

    Барьер: ждём все ветки. Упавшая ветка возвращает None, а не роняет весь
    прогон — восемь хороших результатов это отчёт, а не ошибка.
    Отфильтровать None обязан вызывающий.
    """
    branches = list(branches)
    if not branches:
        return []

    results: list[State | None] = [None] * len(branches)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fn, dict(state)): (i, fn) for i, fn in enumerate(branches)
        }
        for future in concurrent.futures.as_completed(futures):
            index, fn = futures[future]
            try:
                results[index] = future.result()
                if trace:
                    trace.record(name_of(fn), ok=True)
            except Exception as exc:  # noqa: BLE001 — локализуем отказ в ветке
                results[index] = None
                if trace:
                    trace.record(name_of(fn), ok=False, error=str(exc))
    return results


def gate(
    state: State,
    build: Node,
    verify: Callable[[State], bool],
    max_attempts: int = 3,
    on_reject: Callable[[State, int], State] | None = None,
    trace: Trace | None = None,
) -> tuple[State, bool]:
    """Цикл с воротами: делающий и проверяющий — РАЗНЫЕ узлы.

    Если тот же узел проверяет собственную работу, он одобряет собственные
    ошибки: то же рассуждение, что породило изъян, его и оценивает.

    Возвращает (состояние, прошло ли). Число попыток ограничено сверху —
    цикл, который не сходится, это счёт за токены, а не настойчивость.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts должен быть не меньше 1")

    for attempt in range(1, max_attempts + 1):
        state = build(state)
        passed = verify(state)
        if trace:
            trace.record(f"{name_of(build)}#{attempt}", ok=passed)
        if passed:
            return state, True
        if on_reject is not None:
            state = on_reject(state, attempt)
    return state, False
