"""Тесты счёта по узлам.

Главные здесь — про честность, а не про арифметику: счёт не должен угадывать
цену неизвестной модели, не должен принимать прайс без даты и не должен
выдавать пересчёт по тарифу за предсказание реального прогона.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from first_graph.extras.invoice import (
    PriceError,
    Prices,
    Usage,
    from_dicts,
    invoice,
    load_prices,
    what_if,
)

ПРАЙС = Prices(
    checked_on="2026-07-22",
    currency="$",
    per_million={
        "флагман": (Decimal("15"), Decimal("75")),
        "быстрая": (Decimal("1"), Decimal("5")),
    },
)


def _прогон() -> list[Usage]:
    return [
        Usage(node="роутер", model="флагман", input_tokens=2_000, output_tokens=100),
        Usage(node="сборщик", model="флагман", input_tokens=50_000, output_tokens=8_000),
        Usage(node="судья", model="флагман", input_tokens=20_000, output_tokens=1_000),
    ]


# ─────────────────────────────────────────────────────────────
# Арифметика — деньги считаем Decimal, без плавающей точки
# ─────────────────────────────────────────────────────────────


def test_стоимость_считается_по_тарифу_за_миллион():
    сч = invoice([Usage("узел", "флагман", 1_000_000, 1_000_000)], ПРАЙС)

    assert сч.total == Decimal("90")  # 15 за вход + 75 за выход


def test_деньги_это_decimal_а_не_float():
    сч = invoice([Usage("узел", "быстрая", 333, 777)], ПРАЙС)

    assert isinstance(сч.total, Decimal)


def test_итог_равен_сумме_строк():
    сч = invoice(_прогон(), ПРАЙС)

    assert сч.total == sum((line.cost for line in сч.lines), Decimal(0))


def test_считаются_все_токены():
    сч = invoice(_прогон(), ПРАЙС)

    assert сч.total_tokens == 2_000 + 100 + 50_000 + 8_000 + 20_000 + 1_000


# ─────────────────────────────────────────────────────────────
# Честность: не угадываем и не молчим
# ─────────────────────────────────────────────────────────────


def test_неизвестная_модель_это_ошибка_а_не_догадка():
    with pytest.raises(PriceError, match="нет модели"):
        invoice([Usage("узел", "неведомая", 100, 100)], ПРАЙС)


def test_ошибка_подсказывает_известные_модели():
    with pytest.raises(PriceError, match="флагман"):
        invoice([Usage("узел", "неведомая", 100, 100)], ПРАЙС)


def test_прайс_без_даты_проверки_отвергается(tmp_path):
    файл = tmp_path / "prices.json"
    файл.write_text(
        json.dumps({"per_million": {"м": {"input": 1, "output": 2}}}),
        encoding="utf-8",
    )

    with pytest.raises(PriceError, match="checked_on"):
        load_prices(файл)


def test_прайс_без_ставок_отвергается(tmp_path):
    файл = tmp_path / "prices.json"
    файл.write_text(json.dumps({"checked_on": "2026-07-22"}), encoding="utf-8")

    with pytest.raises(PriceError, match="per_million"):
        load_prices(файл)


def test_кривая_ставка_отвергается(tmp_path):
    файл = tmp_path / "prices.json"
    файл.write_text(
        json.dumps({"checked_on": "2026-07-22", "per_million": {"м": {"input": 1}}}),
        encoding="utf-8",
    )

    with pytest.raises(PriceError, match="input и output"):
        load_prices(файл)


def test_прайс_читается_целиком(tmp_path):
    файл = tmp_path / "prices.json"
    файл.write_text(
        json.dumps(
            {
                "checked_on": "2026-07-22",
                "currency": "₽",
                "per_million": {"м": {"input": "1.5", "output": "7.5"}},
            }
        ),
        encoding="utf-8",
    )

    прайс = load_prices(файл)

    assert прайс.checked_on == "2026-07-22"
    assert прайс.currency == "₽"
    assert прайс.per_million["м"] == (Decimal("1.5"), Decimal("7.5"))


def test_в_счёте_видна_дата_тарифов():
    текст = invoice(_прогон(), ПРАЙС).render()

    assert "2026-07-22" in текст
    assert "сверьте" in текст.lower()


# ─────────────────────────────────────────────────────────────
# Тиринг: пересчёт по тарифу — это НЕ предсказание прогона
# ─────────────────────────────────────────────────────────────


def test_перенос_узлов_на_дешёвую_модель_снижает_счёт():
    было = invoice(_прогон(), ПРАЙС)
    стало = what_if(_прогон(), ПРАЙС, {"роутер": "быстрая", "сборщик": "быстрая"})

    assert стало.total < было.total


def test_перенос_не_меняет_расход_токенов():
    # Ключевая честность: мы считаем разницу в ТАРИФЕ при том же объёме,
    # а не предсказываем, сколько токенов съест другая модель.
    было = invoice(_прогон(), ПРАЙС)
    стало = what_if(_прогон(), ПРАЙС, {"роутер": "быстрая"})

    assert стало.total_tokens == было.total_tokens


def test_судья_остался_на_флагмане_если_его_не_переносили():
    стало = what_if(_прогон(), ПРАЙС, {"роутер": "быстрая"})

    судья = next(line for line in стало.lines if line.node == "судья")
    assert судья.model == "флагман"


def test_перенос_несуществующего_узла_это_ошибка():
    with pytest.raises(ValueError, match="нет узлов"):
        what_if(_прогон(), ПРАЙС, {"такого-узла-нет": "быстрая"})


# ─────────────────────────────────────────────────────────────
# Входные данные
# ─────────────────────────────────────────────────────────────


def test_пустой_отчёт_это_ошибка():
    with pytest.raises(ValueError, match="пуст"):
        invoice([], ПРАЙС)


def test_отрицательные_токены_это_ошибка():
    with pytest.raises(ValueError, match="отрицательные"):
        Usage(node="узел", model="флагман", input_tokens=-1, output_tokens=0)


def test_сборка_из_словарей():
    usage = from_dicts(
        [{"node": "a", "model": "быстрая", "input_tokens": 10, "output_tokens": 20}]
    )

    assert usage[0].node == "a"
    assert usage[0].output_tokens == 20


def test_словарь_без_обязательного_поля_это_ошибка():
    with pytest.raises(ValueError, match="нужны поля"):
        from_dicts([{"node": "a", "model": "быстрая"}])
