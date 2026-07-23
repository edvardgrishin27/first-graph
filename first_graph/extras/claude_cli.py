"""Тонкий адаптер к Claude Code в headless-режиме.

Зачем через CLI, а не через API: у зрителя, который смотрит ролик про
graph engineering, Claude Code уже стоит. API-ключ есть далеко не у всех,
а `claude -p` — есть у каждого. Ноль новых зависимостей для запуска.

Что важно для честности инструмента: судья здесь — не голая модель, а агент
с обвязкой. Для научного утверждения это был бы недостаток. Для нашего
вопроса («ловит ли второй проверяющий больше НА МОИХ данных») — наоборот
плюс: зритель работает именно с агентами, а не с чистым API.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_TIMEOUT = 180.0


class ClaudeUnavailable(RuntimeError):
    """Claude Code не найден или не отвечает — работаем только на заглушках."""


@dataclass(frozen=True)
class Reply:
    """Ответ модели вместе с тем, во что он обошёлся."""

    text: str
    model: str
    cost_usd: float
    duration_ms: int

    @property
    def ok(self) -> bool:
        return bool(self.text)


def available() -> bool:
    """Есть ли claude в PATH. Без него доступен только режим заглушек."""
    return shutil.which("claude") is not None


def ask(
    prompt: str,
    model: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_budget_usd: float | None = None,
    system: str | None = None,
) -> Reply:
    """Один headless-вызов Claude Code.

    model — алиас (haiku/sonnet/opus/fable) или полное имя.
    max_budget_usd — жёсткий потолок расходов на этот вызов; тот же принцип,
    что и якорь реальности, только для денег: не «постараюсь», а «не выше».

    Не смог вызвать — поднимает ClaudeUnavailable, а не возвращает пустоту:
    молчаливый провал измерения хуже честного отказа.
    """
    if not available():
        raise ClaudeUnavailable("claude не найден в PATH")

    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "json",
        "--no-session-persistence",
    ]
    if system is not None:
        cmd += ["--append-system-prompt", system]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]

    try:
        done = subprocess.run(  # noqa: S603 — список аргументов, без shell
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeUnavailable(f"claude не ответил за {timeout:g}с") from exc
    except OSError as exc:
        raise ClaudeUnavailable(f"claude не запустился: {exc}") from exc

    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        reason = tail[-1][:200] if tail else "без вывода"
        raise ClaudeUnavailable(f"claude вернул код {done.returncode}: {reason}")

    return _parse(done.stdout)


def _parse(raw: str) -> Reply:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaudeUnavailable(f"claude отдал не JSON: {exc}") from exc

    if data.get("is_error"):
        raise ClaudeUnavailable(f"claude сообщил об ошибке: {data.get('result', '')[:200]}")

    usage = data.get("modelUsage", {})
    model = next(iter(usage), data.get("model", "неизвестно"))

    return Reply(
        text=str(data.get("result", "")),
        model=model,
        cost_usd=float(data.get("total_cost_usd", 0.0)),
        duration_ms=int(data.get("duration_ms", 0)),
    )
