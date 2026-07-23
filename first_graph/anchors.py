"""Якорь реальности — ворота, которые нельзя обмануть словами.

Агенты в графе подтверждают друг друга текстом: первый пишет «тесты прошли»,
второй читает и отвечает «подтверждаю». Тесты при этом не запускал никто.

Якорь не спрашивает мнения. Он сам запускает команду, сам смотрит на файл,
сам стучится по адресу — и решает по коду возврата, а не по формулировке.

Главное в этом модуле — не что он умеет, а что он ОТКАЗЫВАЕТСЯ принимать:
функцию сюда передать нельзя. Ни лямбду, ни «спроси у модели». TypeError.
Ограничение живёт в коде, а не в документации.

Честная граница: якорь не спасает от глупости. `command=["true"]` — тоже
внешний процесс, и он всегда пройдёт. Модуль гарантирует одно: вы не сможете
СЛУЧАЙНО подсунуть мнение вместо проверки, приняв одно за другое.
"""

from __future__ import annotations

import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from first_graph.graph import State, Trace

DEFAULT_COMMAND_TIMEOUT = 300.0
DEFAULT_URL_TIMEOUT = 10.0
PASSING_EXIT_CODE = 0


@dataclass(frozen=True)
class Evidence:
    """Что именно проверили и что получили. Записывается в состояние."""

    kind: str
    target: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        mark = "✓" if self.passed else "✗"
        return f"{mark} якорь [{self.kind}] {self.target}: {self.detail}"


def _reject_opinions(**candidates: object) -> None:
    """Не даёт передать в якорь функцию — в этом весь смысл модуля."""
    for name, value in candidates.items():
        if callable(value):
            raise TypeError(
                f"якорь не принимает функцию в «{name}»: якорь — это внешнее "
                "доказательство (команда, файл, адрес), а не чьё-то суждение. "
                "Если нужна проверка своей логикой — это gate(), не anchor()."
            )


def _check_command(
    command: list[str], timeout: float, cwd: str | Path | None
) -> Evidence:
    target = " ".join(command)
    try:
        done = subprocess.run(  # noqa: S603 — список аргументов, без shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except FileNotFoundError:
        return Evidence("command", target, False, "команда не найдена")
    except subprocess.TimeoutExpired:
        return Evidence("command", target, False, f"таймаут {timeout:g}с")
    except OSError as exc:
        return Evidence("command", target, False, f"не запустилась: {exc}")

    passed = done.returncode == PASSING_EXIT_CODE
    if passed:
        return Evidence("command", target, True, "код возврата 0")

    tail = (done.stderr or done.stdout or "").strip().splitlines()
    reason = tail[-1][:200] if tail else "вывода нет"
    return Evidence("command", target, False, f"код {done.returncode}: {reason}")


def _mtime(path: Path) -> float:
    """Время правки. Для папки — самый свежий файл внутри."""
    if path.is_dir():
        times = [p.stat().st_mtime for p in path.rglob("*") if p.is_file()]
        return max(times, default=0.0)
    return path.stat().st_mtime


def _check_file(path: Path, newer_than: str | Path | None) -> Evidence:
    target = str(path)
    if not path.exists():
        return Evidence("file", target, False, "не существует")
    if newer_than is None:
        return Evidence("file", target, True, "существует")

    source = Path(newer_than)
    if not source.exists():
        return Evidence("file", target, False, f"не с чем сравнить: нет {source}")

    if _mtime(path) >= _mtime(source):
        return Evidence("file", target, True, f"свежее, чем {source}")
    return Evidence("file", target, False, f"старее, чем {source} — не пересобран")


def _normalize_url(url: str) -> str:
    """Приводит адрес к тому, что понимает http.client: ASCII-хост и путь.

    Кириллица в домене и пути — обычное дело для рунета, а http.client требует
    чистый ASCII. Без этого якорь ронял бы UnicodeEncodeError вместо честного
    «не прошло».
    """
    parts = urllib.parse.urlsplit(url)

    netloc = parts.netloc
    if parts.hostname:
        try:
            host = parts.hostname.encode("idna").decode("ascii")
        except (UnicodeError, ValueError):
            host = parts.hostname
        netloc = f"{host}:{parts.port}" if parts.port else host

    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            netloc,
            urllib.parse.quote(parts.path, safe="/%"),
            urllib.parse.quote(parts.query, safe="=&%?"),
            "",
        )
    )


def _check_url(url: str, expect: int | set[int], timeout: float) -> Evidence:
    expected = {expect} if isinstance(expect, int) else set(expect)
    want = ", ".join(str(code) for code in sorted(expected))
    try:
        with urllib.request.urlopen(  # noqa: S310
            _normalize_url(url), timeout=timeout
        ) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        return Evidence("url", url, False, f"недоступен: {exc}")
    except (ValueError, UnicodeError) as exc:
        # Кривой адрес — это «не доказано», а не падение всего графа.
        return Evidence("url", url, False, f"некорректный адрес: {exc}")

    if status in expected:
        return Evidence("url", url, True, f"статус {status}")
    return Evidence("url", url, False, f"статус {status}, ожидался {want}")


def anchor(
    state: State,
    *,
    command: list[str] | None = None,
    file: str | Path | None = None,
    newer_than: str | Path | None = None,
    url: str | None = None,
    expect: int | set[int] = 200,
    timeout: float | None = None,
    cwd: str | Path | None = None,
    trace: Trace | None = None,
) -> tuple[State, bool]:
    """Проверяет реальность и возвращает (состояние, прошло ли).

    Ровно один вид доказательства за вызов:
      anchor(state, command=["pytest", "-q"])
      anchor(state, file="dist/app.apk", newer_than="src/")
      anchor(state, url="https://example.com/health", expect=200)

    Правило: якорь, который не смог проверить, считается НЕПРОЙДЕННЫМ.
    Команда не нашлась, сеть отвалилась, таймаут — всё это «нет», а не «ну ладно».
    Отказ в сторону безопасности: недоказанное не считается доказанным.
    """
    _reject_opinions(command=command, file=file, url=url, newer_than=newer_than)

    given = [name for name, value in
             (("command", command), ("file", file), ("url", url))
             if value is not None]
    if len(given) != 1:
        raise ValueError(
            "нужен ровно один вид доказательства — command, file или url; "
            f"передано: {', '.join(given) if given else 'ничего'}"
        )

    if command is not None:
        if isinstance(command, str):
            raise TypeError(
                "command — это список аргументов, а не строка: "
                '["pytest", "-q"] вместо "pytest -q". Так нет ни shell, ни инъекций.'
            )
        evidence = _check_command(
            command, timeout if timeout is not None else DEFAULT_COMMAND_TIMEOUT, cwd
        )
    elif file is not None:
        evidence = _check_file(Path(file), newer_than)
    else:
        evidence = _check_url(
            str(url), expect, timeout if timeout is not None else DEFAULT_URL_TIMEOUT
        )

    if trace is not None:
        trace.record(f"anchor:{evidence.kind}", ok=evidence.passed, error=None
                     if evidence.passed else evidence.detail)

    state = dict(state)
    state["anchors"] = [*state.get("anchors", []), evidence]
    return state, evidence.passed
