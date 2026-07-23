"""Окупается ли второй проверяющий на другой модели.

Во всех статьях про графы повторяют: агент, который проверяет свою же работу,
одобрит собственные ошибки — поэтому проверять должна другая модель. Звучит
логично. Но платить вдвое за второго судью стоит только если он реально что-то
ловит СВЕРХ первого. На ВАШИХ задачах, а не в теории.

Этот инструмент отвечает ровно на это. Он НЕ пытается доказать, существует ли
самопредпочтение вообще (это дорого измерить и всё равно спорно — см.
experiments/echo/README.md). Он отвечает на денежный вопрос: на ваших данных
второй судья на другой модели ловит больше изъянов, чем первый, или нет?

Причина не важна — самопредпочтение это или просто разные слепые зоны у двух
моделей. Для решения «платить или нет» важен только факт: ловит или не ловит.

Честная опора — pytest, а не мнение третьей модели: где на самом деле изъян,
устанавливает запуск тестов (anchor из ядра). Судьи сравниваются с этой
правдой, а не друг с другом.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from first_graph.anchors import anchor
from first_graph.extras.claude_cli import Reply

# Тип функции-судьи: получает код, возвращает (одобрил ли, во что обошёлся).
# Абстракция нужна, чтобы подменять реальный вызов заглушкой в тестах и в
# --dry-run — без единого обращения к модели.
JudgeFn = "callable"


@dataclass(frozen=True)
class Case:
    """Задача, где модель вероятно ошибётся, и тест, который это поймает.

    solution — код-кандидат (в реальном прогоне его пишет модель; в тестах и
               демо подставляется готовый — верный или с изъяном).
    test — pytest-файл, который падает на изъяне и проходит на верном решении.
    module_name — имя, под которым solution кладётся на диск для импорта.
    """

    name: str
    solution: str
    test: str
    module_name: str = "solution"


def has_flaw(case: Case) -> bool:
    """Правду устанавливает pytest, а не мнение. Изъян = тесты не прошли.

    Отказ в сторону безопасности наследуется от anchor: если pytest не удалось
    запустить, считаем «не доказано, что чисто» — то есть флаг изъяна. Иначе
    сломанное окружение молча раздуло бы «чистые» решения.
    """
    with tempfile.TemporaryDirectory() as tmp:
        проект = Path(tmp)
        (проект / f"{case.module_name}.py").write_text(case.solution, encoding="utf-8")
        (проект / f"test_{case.module_name}.py").write_text(case.test, encoding="utf-8")

        import sys

        _, passed = anchor(
            {},
            command=[sys.executable, "-m", "pytest", "-q", "--no-header"],
            cwd=проект,
        )
    return not passed


@dataclass
class Verdict:
    """Что сказал один судья про один изъянный случай."""

    case: str
    approved: bool  # True = «всё ок» = ПРОПУСТИЛ изъян
    cost_usd: float

    @property
    def caught(self) -> bool:
        """Поймал изъян = НЕ одобрил изъянный код."""
        return not self.approved


@dataclass
class JudgeResult:
    """Итог одного судьи по всем изъянным случаям."""

    label: str
    model: str
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def caught(self) -> int:
        return sum(1 for v in self.verdicts if v.caught)

    @property
    def total(self) -> int:
        return len(self.verdicts)

    @property
    def cost_usd(self) -> float:
        return sum(v.cost_usd for v in self.verdicts)

    def caught_set(self) -> set[str]:
        return {v.case for v in self.verdicts if v.caught}


@dataclass
class Comparison:
    """Сравнение двух судей и денежный вердикт."""

    first: JudgeResult
    second: JudgeResult
    flawed_cases: list[str]

    @property
    def second_only(self) -> set[str]:
        """Изъяны, которые поймал ТОЛЬКО второй судья — за них и платят."""
        return self.second.caught_set() - self.first.caught_set()

    @property
    def first_only(self) -> set[str]:
        return self.first.caught_set() - self.second.caught_set()

    @property
    def both(self) -> set[str]:
        return self.first.caught_set() & self.second.caught_set()

    @property
    def extra_cost(self) -> float:
        """Во сколько обошёлся второй судья."""
        return self.second.cost_usd

    @property
    def pays_off(self) -> bool:
        """Окупается, если поймал хоть что-то, чего не поймал первый."""
        return len(self.second_only) > 0

    def render(self) -> str:
        n = len(self.flawed_cases)
        lines = [
            "ОКУПАЕТСЯ ЛИ ВТОРОЙ ПРОВЕРЯЮЩИЙ",
            "",
            f"Изъянных решений (правду установил pytest): {n}",
            "",
            f"  {self.first.label} ({self.first.model}):",
            f"    поймал изъянов: {self.first.caught} из {n}",
            f"    стоимость: ${self.first.cost_usd:.4f}",
            "",
            f"  {self.second.label} ({self.second.model}):",
            f"    поймал изъянов: {self.second.caught} из {n}",
            f"    стоимость: ${self.second.cost_usd:.4f}",
            "",
            "РАЗБОР ПО ИЗЪЯНАМ",
            f"  поймали оба:            {len(self.both)}",
            f"  поймал только первый:   {len(self.first_only)}",
            f"  поймал ТОЛЬКО второй:   {len(self.second_only)}"
            + (f"  ← {', '.join(sorted(self.second_only))}" if self.second_only else ""),
            "",
            "ВЕРДИКТ",
        ]
        if self.pays_off:
            lines.append(
                f"  Второй судья поймал {len(self.second_only)} изъянов, которые "
                f"пропустил первый, за ${self.extra_cost:.4f}."
            )
            lines.append("  На этих данных второй проверяющий окупается.")
        else:
            lines.append(
                f"  Второй судья не поймал НИЧЕГО сверх первого, а стоил "
                f"${self.extra_cost:.4f}."
            )
            lines.append("  На этих данных вы платите вдвое зря.")
        lines.append("")
        lines.append("  Причину — самопредпочтение это или разные слепые зоны —")
        lines.append("  инструмент не различает и не должен: для решения о деньгах")
        lines.append("  важен только факт «ловит / не ловит». Данных мало —")
        lines.append("  это оценка на ваших примерах, а не закон.")
        return "\n".join(lines)


def judge_flawed(
    cases: list[Case],
    first: JudgeFn,
    second: JudgeFn,
    first_label: str,
    second_label: str,
    first_model: str,
    second_model: str,
) -> Comparison:
    """Прогоняет обоих судей по ИЗЪЯННЫМ случаям и сравнивает.

    first/second — функции (Case) -> Reply, где Reply.text содержит вердикт
    («ОДОБРИТЬ»/«ОТКЛОНИТЬ» первым словом), а Reply.cost_usd — цену вызова.
    Чистые случаи в сравнение не идут: там ловить нечего, они бы только
    разбавили цифры (эту ошибку поймал состязательный рецензент прошлой версии).
    """
    flawed = [c for c in cases if has_flaw(c)]

    first_res = JudgeResult(label=first_label, model=first_model)
    second_res = JudgeResult(label=second_label, model=second_model)

    for case in flawed:
        for судья, res in ((first, first_res), (second, second_res)):
            reply: Reply = судья(case)
            res.verdicts.append(
                Verdict(
                    case=case.name,
                    approved=_approved(reply.text),
                    cost_usd=reply.cost_usd,
                )
            )

    return Comparison(
        first=first_res,
        second=second_res,
        flawed_cases=[c.name for c in flawed],
    )


def _approved(text: str) -> bool:
    """Читает вердикт судьи из первого слова. Неразборчивое = не одобрил.

    Отказ в сторону безопасности: если судья ответил невнятно, считаем, что
    он НЕ дал добро (поймал). Так мы не завышаем «пропуски» из-за парсинга.
    """
    head = text.strip().upper()
    return head.startswith(("ОДОБР", "APPROVE", "OK", "ПРОШ", "PASS"))
