"""Человек в контуре — остановка графа на дорогом и необратимом.

Живёт в дополнениях, а не в ядре, сознательно: это ввод-вывод, а не теория
графов. Ядро описывает, как устроен граф; способ спросить человека — вопрос
интерфейса, и у каждого он свой (терминал, телеграм, веб-форма).

Главное правило узла одобрения: показывать РОВНО то, что произойдёт, и во
что это обойдётся. Не «одобряете?», а «отправлю 2400 писем сегменту биллинга,
оценочно $12 — да или нет?». Человек должен решать за пять секунд.
"""

from __future__ import annotations

from typing import Callable

from first_graph.graph import State


def human_gate(
    state: State,
    describe: Callable[[State], str],
    ask: Callable[[str], bool] | None = None,
) -> tuple[State, bool]:
    """Человек в контуре — для дорогого, необратимого и рискованного.

    Показывает ровно то, что произойдёт, а не спрашивает «одобряете?».
    `ask` подменяется в тестах; по умолчанию спрашивает в терминале.
    """
    summary = describe(state)
    if ask is None:

        def ask(text: str) -> bool:
            return input(f"{text}\nПродолжить? [y/N]: ").strip().lower() == "y"

    approved = ask(summary)
    state = dict(state)
    state["approved"] = approved
    return state, approved
