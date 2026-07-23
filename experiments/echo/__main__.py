"""Командная строка эксперимента.

    python3 -m experiments.echo --dry-run          весь конвейер на заглушках
    python3 -m experiments.echo --list-tasks       что за задачи внутри
    python3 -m experiments.echo --runs 8 \\
        --executor anthropic:МОДЕЛЬ --other openai:МОДЕЛЬ

Без ключей в окружении работает только сухой прогон — и это не ошибка, а
нормальный способ убедиться, что каркас цел, прежде чем платить за токены.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path

from first_graph.extras.invoice import PriceError, Usage, invoice, load_prices

from experiments.echo import tasks
from experiments.echo.providers import ProviderError, построить
from experiments.echo.report import отчёт
from experiments.echo.runner import Настройки, Результаты, прогнать
from experiments.echo.stubs import ДОЛЯ_ИЗЪЯНОВ, StubClient

ПАПКА_ПРОГОНОВ = Path(__file__).resolve().parent / "runs"

EXIT_OK = 0
EXIT_ОШИБКА_НАСТРОЙКИ = 2

# Идентификаторы моделей меняются чаще этого файла. Это только отправная точка:
# перед настоящим прогоном сверьтесь со списком моделей у провайдера.
ИСПОЛНИТЕЛЬ_ПО_УМОЛЧАНИЮ = "anthropic:claude-sonnet-4-5"
ДРУГАЯ_ПО_УМОЛЧАНИЮ = "openai:gpt-4.1"


def _разобрать(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m experiments.echo",
        description="Эхо-камера: соглашается ли модель-ревьюер со своим же кодом.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="прогнать конвейер на заглушках вместо вызовов API",
    )
    parser.add_argument(
        "--list-tasks", action="store_true", help="показать задачи и выйти"
    )
    parser.add_argument(
        "--runs", type=int, default=5, help="попыток на задачу (по умолчанию 5)"
    )
    parser.add_argument(
        "--tasks",
        default="",
        help="список id задач через запятую; по умолчанию все",
    )
    parser.add_argument(
        "--executor",
        default=ИСПОЛНИТЕЛЬ_ПО_УМОЛЧАНИЮ,
        help="модель-исполнитель, «провайдер:модель» (сверьтесь с провайдером)",
    )
    parser.add_argument(
        "--other",
        default=ДРУГАЯ_ПО_УМОЛЧАНИЮ,
        help="вторая модель для строк C и D",
    )
    parser.add_argument("--temp-exec", type=float, default=1.0,
                        help="температура исполнителя (нужен разброс решений)")
    parser.add_argument("--temp-judge", type=float, default=0.0,
                        help="температура судьи (нужна повторяемость)")
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument(
        "--only-flawed",
        action="store_true",
        help="не судить чистый код: дешевле, но пропадает контроль на снисходительность",
    )
    parser.add_argument("--pause", type=float, default=0.0,
                        help="пауза между вызовами, секунд")
    parser.add_argument("--seed", type=int, default=1, help="seed заглушек")
    parser.add_argument(
        "--stub-flaw-rate",
        type=float,
        default=ДОЛЯ_ИЗЪЯНОВ,
        help="какую долю ответов заглушка делает изъянной (только --dry-run)",
    )
    parser.add_argument("--out", type=Path, default=None,
                        help="куда сложить сырые данные прогона (JSON)")
    parser.add_argument("--no-save", action="store_true", help="ничего не сохранять")
    parser.add_argument(
        "--prices",
        type=Path,
        default=None,
        help="прайс в формате first_graph/extras/prices.example.json — "
             "тогда расход будет переведён в деньги по узлам графа",
    )
    return parser.parse_args(argv)


def _показать_задачи() -> int:
    for задача in tasks.ЗАДАЧИ:
        print(f"{задача.id} — {задача.функция}()")
        print(f"  ловушка: {задача.ловушка}")
    return EXIT_OK


def _куда_сохранить(args: argparse.Namespace) -> Path | None:
    if args.no_save:
        return None
    if args.out is not None:
        return args.out
    if args.dry_run:
        return None  # сухой прогон ничего не измеряет — незачем копить файлы
    отметка = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ПАПКА_ПРОГОНОВ / f"echo-{отметка}.json"


def _показать_счёт(результаты: Результаты, прайс: Path) -> None:
    """Переводит расход в деньги дополнением репозитория, а не своей формулой.

    Прайс — вход, а не константа: цены меняются, а счёт без даты тарифов
    ровно та невоспроизводимая цифра, за которую мы критикуем других.
    """
    расход = [
        Usage(
            node=запись.узел,
            model=запись.модель,
            input_tokens=запись.входных,
            output_tokens=запись.выходных,
        )
        for запись in результаты.расходы
    ]
    if not расход:
        return

    try:
        счёт = invoice(расход, load_prices(прайс))
    except (PriceError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"счёт не посчитан: {exc}", file=sys.stderr)
        return

    print()
    print(счёт.render("СКОЛЬКО ЭТО СТОИЛО, ПО УЗЛАМ ГРАФА"))


def _сохранить(результаты: Результаты, путь: Path) -> None:
    путь.parent.mkdir(parents=True, exist_ok=True)
    данные = dataclasses.asdict(результаты)
    данные["записано"] = datetime.now().isoformat(timespec="seconds")
    путь.write_text(
        json.dumps(данные, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = _разобрать(argv)

    if args.list_tasks:
        return _показать_задачи()

    if args.runs < 1:
        print("--runs должен быть не меньше 1", file=sys.stderr)
        return EXIT_ОШИБКА_НАСТРОЙКИ

    if not args.dry_run and args.executor == args.other:
        # Иначе строка «другая модель» перестаёт быть другой, и весь план
        # превращается в сравнение ячейки с самой собой.
        print(
            "--executor и --other обязаны быть разными моделями: "
            "на одинаковых строки плана «своя/чужая» становятся одной и той же",
            file=sys.stderr,
        )
        return EXIT_ОШИБКА_НАСТРОЙКИ

    выбранные = tuple(и.strip() for и in args.tasks.split(",") if и.strip())
    try:
        задачи = tasks.по_идентификаторам(выбранные) if выбранные else tasks.ЗАДАЧИ
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return EXIT_ОШИБКА_НАСТРОЙКИ

    настройки = Настройки(
        задачи=tuple(задача.id for задача in задачи),
        повторов=args.runs,
        исполнитель=args.executor,
        другая=args.other,
        температура_исполнителя=args.temp_exec,
        температура_судьи=args.temp_judge,
        предел_токенов=args.max_tokens,
        только_изъяны=args.only_flawed,
        пауза=args.pause,
        seed=args.seed,
        сухой_прогон=args.dry_run,
    )

    try:
        if args.dry_run:
            исполнитель = StubClient(
                "stub:та-же-модель", задачи, args.seed, args.stub_flaw_rate
            )
            другая = StubClient(
                "stub:другая-модель", задачи, args.seed + 1, args.stub_flaw_rate
            )
        else:
            исполнитель = построить(args.executor)
            другая = построить(args.other)
    except ProviderError as exc:
        print(f"не собрать клиента: {exc}", file=sys.stderr)
        return EXIT_ОШИБКА_НАСТРОЙКИ

    try:
        результаты = прогнать(настройки, задачи, исполнитель, другая)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ОШИБКА_НАСТРОЙКИ

    print()
    print(отчёт(результаты))

    if args.prices is not None:
        _показать_счёт(результаты, args.prices)

    путь = _куда_сохранить(args)
    if путь is not None:
        _сохранить(результаты, путь)
        print()
        print(f"Сырые данные прогона: {путь}")

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
