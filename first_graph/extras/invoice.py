"""Счёт по узлам графа.

Важное отличие от того, что ожидают: этот модуль НИЧЕГО НЕ ИЗМЕРЯЕТ.

Библиотека first-graph не вызывает моделей — она оркестрирует. Считать здесь
токены было бы враньём: мы их не видим. Поэтому счёт принимает отчёт об
использовании из ВАШЕГО реального прогона и раскладывает его по узлам графа.

Формулировка, которая должна звучать вслух: «мы не меряем — мы показываем
ваш настоящий счёт в разрезе графа».

Тарифы тоже не зашиты. Прайс — обязательный вход с обязательной датой, потому
что цены меняются, а счёт без даты прайса — это невоспроизводимый бенчмарк,
ровно тот, за который принято критиковать чужие README.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ЗА_СКОЛЬКО_ТОКЕНОВ = Decimal(1_000_000)


class PriceError(ValueError):
    """Проблема с прайс-листом: нет даты, нет модели, кривые числа."""


@dataclass(frozen=True)
class Usage:
    """Факт из реального прогона: узел, модель, сколько токенов ушло."""

    node: str
    model: str
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError(f"узел {self.node}: отрицательные токены")


@dataclass(frozen=True)
class Prices:
    """Прайс-лист с обязательной датой проверки."""

    checked_on: str
    currency: str
    per_million: dict[str, tuple[Decimal, Decimal]]

    def cost(self, model: str, in_tokens: int, out_tokens: int) -> Decimal:
        if model not in self.per_million:
            raise PriceError(
                f"в прайсе нет модели «{model}». Известные: "
                f"{', '.join(sorted(self.per_million))}. "
                "Счёт не угадывает цену — допишите её в прайс."
            )
        цена_вход, цена_выход = self.per_million[model]
        return (
            цена_вход * Decimal(in_tokens) + цена_выход * Decimal(out_tokens)
        ) / ЗА_СКОЛЬКО_ТОКЕНОВ


@dataclass(frozen=True)
class Line:
    """Строка счёта."""

    node: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: Decimal


@dataclass(frozen=True)
class Invoice:
    """Счёт: строки, итог и дата прайса, по которому он посчитан."""

    lines: tuple[Line, ...]
    prices: Prices

    @property
    def total(self) -> Decimal:
        return sum((line.cost for line in self.lines), Decimal(0))

    @property
    def total_tokens(self) -> int:
        return sum(line.input_tokens + line.output_tokens for line in self.lines)

    def render(self, title: str = "СЧЁТ ПО УЗЛАМ") -> str:
        знак = self.prices.currency
        ширина = max((len(line.node) for line in self.lines), default=4) + 2

        строки = [title, ""]
        строки.append(f"  {'узел':<{ширина}} {'модель':<18} {'токены':>12}  сумма")
        строки.append(f"  {'─' * (ширина + 44)}")
        for line in sorted(self.lines, key=lambda l: l.cost, reverse=True):
            токены = f"{line.input_tokens:,}/{line.output_tokens:,}".replace(",", " ")
            строки.append(
                f"  {line.node:<{ширина}} {line.model:<18} {токены:>12}  "
                f"{знак}{line.cost:.4f}"
            )
        строки.append(f"  {'─' * (ширина + 44)}")
        всего = f"{self.total_tokens:,}".replace(",", "\u00a0")
        строки.append(f"  {'ИТОГО':<{ширина}} {'':<18} {всего:>12}  "
                      f"{знак}{self.total:.4f}")
        строки.append("")
        строки.append(f"  Тарифы на {self.prices.checked_on}. "
                      "Цены меняются — сверьте на день расчёта.")
        return "\n".join(строки)


def load_prices(path: str | Path) -> Prices:
    """Читает прайс из JSON. Без даты проверки — отказ."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    checked_on = raw.get("checked_on")
    if not checked_on:
        raise PriceError(
            "в прайсе нет поля checked_on. Счёт без даты тарифов — "
            "невоспроизводимое число, а не доказательство."
        )

    models = raw.get("per_million")
    if not isinstance(models, dict) or not models:
        raise PriceError("в прайсе нет раздела per_million со ставками моделей")

    per_million: dict[str, tuple[Decimal, Decimal]] = {}
    for model, ставки in models.items():
        try:
            per_million[model] = (
                Decimal(str(ставки["input"])),
                Decimal(str(ставки["output"])),
            )
        except (KeyError, TypeError, ArithmeticError) as exc:
            raise PriceError(
                f"кривая ставка для «{model}»: нужны поля input и output"
            ) from exc

    return Prices(
        checked_on=str(checked_on),
        currency=str(raw.get("currency", "$")),
        per_million=per_million,
    )


def invoice(usage: list[Usage], prices: Prices) -> Invoice:
    """Раскладывает реальный отчёт об использовании по узлам графа."""
    if not usage:
        raise ValueError("отчёт об использовании пуст — считать нечего")

    lines = tuple(
        Line(
            node=item.node,
            model=item.model,
            input_tokens=item.input_tokens,
            output_tokens=item.output_tokens,
            cost=prices.cost(item.model, item.input_tokens, item.output_tokens),
        )
        for item in usage
    )
    return Invoice(lines=lines, prices=prices)


def what_if(usage: list[Usage], prices: Prices, reassign: dict[str, str]) -> Invoice:
    """Тот же прогон, но часть узлов уехала на другую модель.

    Это НЕ предсказание: расход токенов берётся тот же самый. Реальный прогон
    на другой модели даст другое число токенов. Здесь считается только разница
    в тарифе при неизменном объёме — и так это и надо называть.
    """
    неизвестные = set(reassign) - {item.node for item in usage}
    if неизвестные:
        raise ValueError(
            f"в отчёте нет узлов: {', '.join(sorted(неизвестные))}"
        )

    перенесённые = [
        Usage(
            node=item.node,
            model=reassign.get(item.node, item.model),
            input_tokens=item.input_tokens,
            output_tokens=item.output_tokens,
        )
        for item in usage
    ]
    return invoice(перенесённые, prices)


def from_dicts(raw: list[dict]) -> list[Usage]:
    """Собирает отчёт из словарей — как их отдаёт JSON выгрузки."""
    usage: list[Usage] = []
    for index, item in enumerate(raw):
        try:
            usage.append(
                Usage(
                    node=str(item["node"]),
                    model=str(item["model"]),
                    input_tokens=int(item["input_tokens"]),
                    output_tokens=int(item["output_tokens"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"запись №{index + 1}: нужны поля node, model, "
                f"input_tokens, output_tokens — {exc}"
            ) from exc
    return usage
