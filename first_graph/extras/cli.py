"""Командная строка.

    first-graph arrows пайплайн.json     — найти фальшивые ожидания
    first-graph demo                     — показать пример на готовом пайплайне
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from first_graph.arrows import PipelineError, audit, from_dicts

EXIT_OK = 0
EXIT_FAKE_ARROWS_FOUND = 1
EXIT_BAD_INPUT = 2

DEMO_PIPELINE = [
    {"id": "клонировать", "writes": ["репо"], "duration": 1},
    {"id": "линтер", "reads": ["репо"], "writes": ["линтер_итог"], "duration": 4},
    {"id": "типы", "reads": ["репо"], "writes": ["типы_итог"], "duration": 5},
    {"id": "тесты", "reads": ["репо"], "writes": ["тесты_итог"], "duration": 12},
    {"id": "уязвимости", "reads": ["репо"], "writes": ["уязв_итог"], "duration": 6},
    {"id": "лицензии", "reads": ["репо"], "writes": ["лиц_итог"], "duration": 3},
    {
        "id": "отчёт",
        "reads": ["линтер_итог", "типы_итог", "тесты_итог", "уязв_итог", "лиц_итог"],
        "duration": 1,
    },
]


def _load(path: Path) -> list[dict]:
    """Читает описание пайплайна. Только JSON — ядро без зависимостей.

    YAML сознательно не поддержан: он потянул бы PyYAML в ядро и сломал
    обещание «ставится одной командой». Нужен YAML — переведите его в JSON
    тремя строками в своём скрипте.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict) and "steps" in data:
        data = data["steps"]
    if not isinstance(data, list):
        raise PipelineError(
            "ожидался список шагов или объект с полем steps, "
            f"а пришло: {type(data).__name__}"
        )
    return data


def _run_audit(raw: list[dict], workers: int | None = None) -> int:
    report = audit(from_dicts(raw))
    print(report.render())
    if workers is not None:
        print()
        print(f"А ЧЕСТНО, при {workers} работниках одновременно:")
        print(f"  время:     {report.capped_time(workers):g}")
        print(f"  ускорение: {report.capped_speedup(workers):.1f}×  "
              f"(идеальное {report.speedup:.1f}× — приятное враньё)")
    return EXIT_FAKE_ARROWS_FOUND if report.fake_arrows else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="first-graph",
        description="Ваш первый граф агентов. И проверка, где пайплайн ждёт зря.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    arrows = sub.add_parser(
        "arrows", help="найти в пайплайне ожидания, за которыми нет данных"
    )
    arrows.add_argument("file", type=Path, help="описание пайплайна в JSON")
    arrows.add_argument("--workers", type=int, default=None,
                        help="честный расчёт при лимите одновременных работников")

    demo = sub.add_parser("demo", help="показать пример на готовом пайплайне")
    demo.add_argument("--workers", type=int, default=None,
                      help="честный расчёт при лимите одновременных работников")

    args = parser.parse_args(argv)

    try:
        if args.command == "demo":
            return _run_audit(DEMO_PIPELINE, args.workers)

        if not args.file.exists():
            print(f"файл не найден: {args.file}", file=sys.stderr)
            return EXIT_BAD_INPUT
        return _run_audit(_load(args.file), args.workers)

    except PipelineError as exc:
        print(f"ошибка в описании пайплайна: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except json.JSONDecodeError as exc:
        print(f"не разобрать JSON: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
