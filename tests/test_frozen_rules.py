"""Замороженные правила репозитория.

Главный актив first-graph — то, что его ядро читается за вечер. Это свойство
защищено не намерением, а тестом: он падает, если ядро распухло или потянуло
зависимость.

Ровно тот приём, который мы советуем в графах: правило, которое оптимизатору
не разрешено подкручивать. Здесь оптимизатор — это мы сами.
"""

from __future__ import annotations

import ast
from pathlib import Path

ЯДРО = Path(__file__).resolve().parent.parent / "first_graph"
ЛИМИТ_СТРОК = 800
СТАНДАРТНАЯ_БИБЛИОТЕКА_РАЗРЕШЕНА = True  # всё остальное — нет


def _модули() -> list[Path]:
    return sorted(ЯДРО.glob("*.py"))


def test_ядро_читается_за_вечер():
    строк = {f.name: len(f.read_text(encoding="utf-8").splitlines()) for f in _модули()}
    всего = sum(строк.values())

    assert всего <= ЛИМИТ_СТРОК, (
        f"ядро распухло до {всего} строк при лимите {ЛИМИТ_СТРОК}: {строк}. "
        "Новое место — examples/ или отдельный опциональный модуль, не ядро."
    )


def test_ядро_не_тянет_внешних_зависимостей():
    свои = {f.stem for f in _модули()} | {"first_graph"}
    внешние: dict[str, set[str]] = {}

    for файл in _модули():
        дерево = ast.parse(файл.read_text(encoding="utf-8"))
        for узел in ast.walk(дерево):
            if isinstance(узел, ast.Import):
                имена = [a.name.split(".")[0] for a in узел.names]
            elif isinstance(узел, ast.ImportFrom):
                имена = [(узел.module or "").split(".")[0]]
            else:
                continue
            чужие = {
                и for и in имена
                if и and и not in свои and и not in _СТАНДАРТНЫЕ
            }
            if чужие:
                внешние.setdefault(файл.name, set()).update(чужие)

    assert not внешние, (
        f"ядро потянуло внешние зависимости: {внешние}. "
        "Установка в одну команду — часть обещания репозитория."
    )


# __main__.py — точка входа `python -m first_graph`, а не теория графов.
# По определению склеивает: CLI живёт в extras (это интерфейс), и точка входа
# обязана на него указывать. В бюджет строк она входит, а из правила «не тянуть
# extras» исключена — потому что реальную самодостаточность библиотеки
# проверяет тест ниже импортом, а не текстом файла.
_ТОЧКА_ВХОДА = "__main__.py"


def test_ядро_не_импортирует_дополнения():
    """extras/ не должны стать лазейкой для обхода бюджета ядра.

    Проверяем текст: логика ядра не ссылается на extras. Точка входа —
    исключение с обоснованием выше; её самодостаточность не спасает и не должна.
    """
    нарушители: dict[str, list[str]] = {}

    for файл in _модули():
        if файл.name == _ТОЧКА_ВХОДА:
            continue
        дерево = ast.parse(файл.read_text(encoding="utf-8"))
        for узел in ast.walk(дерево):
            if isinstance(узел, ast.ImportFrom) and "extras" in (узел.module or ""):
                нарушители.setdefault(файл.name, []).append(узел.module or "")
            elif isinstance(узел, ast.Import):
                for имя in узел.names:
                    if "extras" in имя.name:
                        нарушители.setdefault(файл.name, []).append(имя.name)

    assert not нарушители, (
        f"ядро импортирует дополнения: {нарушители}. "
        "extras/ существует, чтобы не раздувать ядро, а не чтобы обойти его бюджет. "
        "Ядро должно работать, даже если extras/ удалить целиком."
    )


def test_импорт_библиотеки_не_тянет_дополнения():
    """Сильнее текстовой проверки: реальная самодостаточность ядра.

    `import first_graph` и его публичный API не должны загружать ни одного
    модуля из extras. Если это правда — extras/ можно удалить, и `from
    first_graph import audit, anchor, gate` продолжит работать. Точка входа
    сюда не попадает: она выполняется только при `python -m`, а не при import.
    """
    import importlib
    import sys

    for имя in [m for m in sys.modules if m.startswith("first_graph")]:
        del sys.modules[имя]

    importlib.import_module("first_graph")
    from first_graph import anchor, audit, gate  # noqa: F401 — публичный API

    протекло = [m for m in sys.modules if m.startswith("first_graph.extras")]
    assert not протекло, (
        f"import first_graph подтянул дополнения: {протекло}. "
        "Ядро обязано работать без extras/ — иначе граница фиктивна."
    )


_СТАНДАРТНЫЕ = {
    "__future__", "abc", "argparse", "ast", "collections", "concurrent",
    "contextlib", "dataclasses", "datetime", "enum", "functools", "http",
    "itertools", "json", "logging", "math", "os", "pathlib", "re", "shutil",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time", "typing",
    "urllib", "uuid",
}
