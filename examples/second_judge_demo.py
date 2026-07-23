"""Окупается ли второй проверяющий на другой модели.

Два режима:

    python3 examples/second_judge_demo.py            # заглушки, бесплатно
    python3 examples/second_judge_demo.py --live      # живой прогон на ваших моделях

--live гоняет судей через `claude -p` (haiku против sonnet по умолчанию) —
без внешних ключей, на вашей же подписке. Цена вызовов реальная, поэтому
стоит ограничитель --max-budget.

Что здесь честно:
  правду об изъяне устанавливает pytest, а не мнение модели;
  в сравнение идут только изъянные решения — на чистых ловить нечего;
  инструмент не притворяется, будто различает самопредпочтение и разные
  слепые зоны: для решения о деньгах это неважно, и он это проговаривает.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from first_graph.extras.claude_cli import Reply, available, ask  # noqa: E402
from first_graph.extras.judge_cases import SPECS, flawed_cases  # noqa: E402
from first_graph.extras.second_judge import Case, judge_flawed  # noqa: E402

СУДЬЯ_СИСТЕМНЫЙ = (
    "Ты придирчивый ревьюер кода. Тебе дают спецификацию и решение. "
    "Найди изъян, если он есть. Первым словом ответа напиши ровно ОДОБРИТЬ "
    "(если решение верно) или ОТКЛОНИТЬ (если нашёл изъян), потом коротко почему."
)


def _промпт(case: Case) -> str:
    return (
        f"СПЕЦИФИКАЦИЯ:\n{SPECS[case.name]}\n\n"
        f"РЕШЕНИЕ:\n```python\n{case.solution}\n```\n\n"
        "Верно ли решение спецификации? Первое слово — ОДОБРИТЬ или ОТКЛОНИТЬ."
    )


def _живой_судья(model: str, budget: float):
    def судить(case: Case) -> Reply:
        return ask(
            _промпт(case),
            model=model,
            system=СУДЬЯ_СИСТЕМНЫЙ,
            max_budget_usd=budget,
        )
    return судить


def _заглушка(пропускает: set[str], цена: float):
    """Судья-заглушка: НЕ смотрит на код, действует по заранее заданному списку.

    Намеренно не подыгрывает — просто разыгрывает сценарий, чтобы показать
    формат отчёта без единого обращения к модели и без единой копейки.
    """
    def судить(case: Case) -> Reply:
        текст = "ОДОБРИТЬ" if case.name in пропускает else "ОТКЛОНИТЬ"
        return Reply(text=текст, model="заглушка", cost_usd=цена, duration_ms=1)
    return судить


def main() -> int:
    parser = argparse.ArgumentParser(description="Окупается ли второй судья")
    parser.add_argument("--live", action="store_true", help="живой прогон через claude -p")
    parser.add_argument("--first", default="haiku", help="модель первого судьи (--live)")
    parser.add_argument("--second", default="sonnet", help="модель второго судьи (--live)")
    parser.add_argument("--max-budget", type=float, default=2.0,
                        help="потолок расходов на весь прогон, $ (--live)")
    args = parser.parse_args()

    случаи = flawed_cases()

    if args.live:
        if not available():
            print("claude не найден в PATH — живой прогон невозможен.")
            print("Уберите --live, чтобы посмотреть формат на заглушках.")
            return 2
        print(f"Живой прогон: первый судья {args.first}, второй {args.second}.")
        print(f"Потолок расходов: ${args.max_budget:.2f}. Гоняю pytest и модели...\n")
        на_судью = args.max_budget / (2 * len(случаи))
        итог = judge_flawed(
            случаи,
            first=_живой_судья(args.first, на_судью),
            second=_живой_судья(args.second, на_судью),
            first_label="первый", second_label="второй",
            first_model=args.first, second_model=args.second,
        )
    else:
        print("СУХОЙ ПРОГОН НА ЗАГЛУШКАХ — ни одного обращения к модели.")
        print("Сценарий: первый пропустил «округление», второй поймал всё.\n")
        итог = judge_flawed(
            случаи,
            first=_заглушка(пропускает={"округление"}, цена=0.02),
            second=_заглушка(пропускает=set(), цена=0.05),
            first_label="первый", second_label="второй",
            first_model="заглушка-A", second_model="заглушка-B",
        )

    print(итог.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
