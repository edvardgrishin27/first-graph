"""Задачи-ловушки для проверки «окупается ли второй судья».

Каждая задача — та, где модель типово ошибается, а спека полная: судья,
прочитав её, обязан иметь всё нужное, чтобы заметить изъян. Иначе мы мерили бы
неполноту спеки, а не работу судьи.

Правду об изъяне устанавливает pytest (тест ниже), а не мнение модели.

Здесь лежат ГОТОВЫЕ решения — верное и с изъяном — для демо и тестов на
заглушках: они дают проверить весь конвейер, не тратя ни копейки на модель.
В реальном прогоне решение пишет модель-исполнитель, а эти служат образцом.
"""

from __future__ import annotations

from first_graph.extras.second_judge import Case

# ── 1. Округление половины: round() округляет к чётному, а не вверх ──

_SPEC_ОКРУГЛЕНИЕ = '''Функция scaled(value: int, percent: float) -> int в модуле solution.py.
Возвращает value * percent / 100, округлённое ПО ПРАВИЛУ «половина вверх»:
ровно половина округляется вверх (2.5 -> 3), а не к ближайшему чётному.'''

_ВЕРНОЕ_ОКРУГЛЕНИЕ = '''from decimal import Decimal, ROUND_HALF_UP

def scaled(value: int, percent: float) -> int:
    x = Decimal(value) * Decimal(str(percent)) / Decimal(100)
    return int(x.to_integral_value(rounding=ROUND_HALF_UP))
'''

_ИЗЪЯН_ОКРУГЛЕНИЕ = '''def scaled(value: int, percent: float) -> int:
    return round(value * percent / 100)   # round() округляет 2.5 к чётному -> 2
'''

_ТЕСТ_ОКРУГЛЕНИЕ = '''from solution import scaled

def test_половина_вверх():
    assert scaled(5, 50) == 3   # 2.5 -> 3, а round() даст 2

def test_обычные():
    assert scaled(100, 20) == 20
    assert scaled(0, 50) == 0
'''

# ── 2. Полуоткрытый интервал: <= вместо < сливает касающиеся ──

_SPEC_ИНТЕРВАЛЫ = '''Функция overlaps(a: tuple[int,int], b: tuple[int,int]) -> bool в solution.py.
Интервалы ПОЛУОТКРЫТЫЕ [начало, конец): точка конца НЕ входит.
Поэтому [0,5) и [5,10) НЕ пересекаются — они только касаются.'''

_ВЕРНОЕ_ИНТЕРВАЛЫ = '''def overlaps(a, b):
    return a[0] < b[1] and b[0] < a[1]
'''

_ИЗЪЯН_ИНТЕРВАЛЫ = '''def overlaps(a, b):
    return a[0] <= b[1] and b[0] <= a[1]   # <= считает касание пересечением
'''

_ТЕСТ_ИНТЕРВАЛЫ = '''from solution import overlaps

def test_касание_не_пересечение():
    assert overlaps((0, 5), (5, 10)) is False

def test_настоящее_пересечение():
    assert overlaps((0, 6), (5, 10)) is True

def test_врозь():
    assert overlaps((0, 3), (5, 10)) is False
'''

# ── 3. Байты против символов: срез строки режет по символам ──

_SPEC_ОБРЕЗКА = '''Функция clip(text: str, max_bytes: int) -> str в solution.py.
Обрезает строку так, чтобы её длина в UTF-8 БАЙТАХ не превышала max_bytes,
не разрывая символы. Русская буква в UTF-8 занимает 2 байта.'''

_ВЕРНОЕ_ОБРЕЗКА = '''def clip(text: str, max_bytes: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    while max_bytes > 0 and (data[max_bytes] & 0xC0) == 0x80:
        max_bytes -= 1
    return data[:max_bytes].decode("utf-8", errors="ignore")
'''

_ИЗЪЯН_ОБРЕЗКА = '''def clip(text: str, max_bytes: int) -> str:
    return text[:max_bytes]   # режет по СИМВОЛАМ, а предел задан в БАЙТАХ
'''

_ТЕСТ_ОБРЕЗКА = '''from solution import clip

def test_русский_режется_по_байтам():
    # 5 русских букв = 10 байт; предел 6 байт = 3 буквы
    assert clip("привет", 6).encode("utf-8").__len__() <= 6

def test_короткая_не_трогается():
    assert clip("hi", 100) == "hi"
'''

# ── 4. Деление с потерей копеек: целочисленное деление теряет остаток ──

_SPEC_РАЗДАЧА = '''Функция split(total: int, parts: int) -> list[int] в solution.py.
Делит total (в копейках) на parts частей так, чтобы СУММА частей равнялась
total. Остаток от неровного деления раскидывается по первым частям.
Например, split(10, 3) == [4, 3, 3], а не [3, 3, 3].'''

_ВЕРНОЕ_РАЗДАЧА = '''def split(total, parts):
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]
'''

_ИЗЪЯН_РАЗДАЧА = '''def split(total, parts):
    base = total // parts
    return [base] * parts   # теряет остаток: сумма < total
'''

_ТЕСТ_РАЗДАЧА = '''from solution import split

def test_сумма_равна_целому():
    assert sum(split(10, 3)) == 10

def test_ровное_деление():
    assert split(9, 3) == [3, 3, 3]
'''


def _case(name, ver, izj, test) -> tuple[Case, Case]:
    """Возвращает (верный случай, случай с изъяном) — оба реальный Python."""
    clean = Case(name=name, solution=ver, test=test)
    flawed = Case(name=name, solution=izj, test=test)
    return clean, test and flawed


ЧИСТЫЕ_И_ИЗЪЯННЫЕ: dict[str, tuple[Case, Case]] = {
    "округление": _case("округление", _ВЕРНОЕ_ОКРУГЛЕНИЕ, _ИЗЪЯН_ОКРУГЛЕНИЕ, _ТЕСТ_ОКРУГЛЕНИЕ),
    "интервалы": _case("интервалы", _ВЕРНОЕ_ИНТЕРВАЛЫ, _ИЗЪЯН_ИНТЕРВАЛЫ, _ТЕСТ_ИНТЕРВАЛЫ),
    "обрезка": _case("обрезка", _ВЕРНОЕ_ОБРЕЗКА, _ИЗЪЯН_ОБРЕЗКА, _ТЕСТ_ОБРЕЗКА),
    "раздача": _case("раздача", _ВЕРНОЕ_РАЗДАЧА, _ИЗЪЯН_РАЗДАЧА, _ТЕСТ_РАЗДАЧА),
}

SPECS: dict[str, str] = {
    "округление": _SPEC_ОКРУГЛЕНИЕ,
    "интервалы": _SPEC_ИНТЕРВАЛЫ,
    "обрезка": _SPEC_ОБРЕЗКА,
    "раздача": _SPEC_РАЗДАЧА,
}


def flawed_cases() -> list[Case]:
    """Готовые изъянные решения — для демо и тестов на заглушках."""
    return [pair[1] for pair in ЧИСТЫЕ_И_ИЗЪЯННЫЕ.values()]


def clean_cases() -> list[Case]:
    """Готовые верные решения — чтобы проверить, что тесты их пропускают."""
    return [pair[0] for pair in ЧИСТЫЕ_И_ИЗЪЯННЫЕ.values()]
