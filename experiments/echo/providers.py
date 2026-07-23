"""Тонкий слой над HTTP-API моделей.

Никаких SDK: urllib из стандартной библиотеки. Эксперименту нужен ровно один
вызов — «вот сообщения, дай ответ», — и подменяемая заглушка вместо него.

ЧЕСТНАЯ ГРАНИЦА. Живьём этот слой не проверялся: там, где он писался, не было
ни ключей, ни сети. Проверен только путь через заглушку (--dry-run). Форматы
запросов взяты из документации провайдеров и могли устареть — всё, что может
разойтись с реальностью, вынесено в константы наверху файла. Если первый
настоящий прогон упадёт на разборе ответа, чинить нужно здесь, в одном месте.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

СЕТЕВОЙ_ТАЙМАУТ = 180.0
ПОПЫТОК = 3
ПАУЗА_МЕЖДУ_ПОПЫТКАМИ = 2.0
ВРЕМЕННЫЕ_КОДЫ = frozenset({408, 409, 429, 500, 502, 503, 504})

# Ключи окружения. Нет ключа — доступен только сухой прогон.
КЛЮЧ_ANTHROPIC = "ANTHROPIC_API_KEY"
КЛЮЧ_OPENAI = "OPENAI_API_KEY"


class ProviderError(RuntimeError):
    """Провайдер не ответил или ответил не так, как мы умеем читать."""


@dataclass(frozen=True)
class Message:
    """Одна реплика диалога. role: «user» или «assistant»."""

    role: str
    content: str


@dataclass(frozen=True)
class Reply:
    """Ответ модели вместе с расходом токенов — прогон стоит денег."""

    text: str
    входных_токенов: int = 0
    выходных_токенов: int = 0


class ModelClient(Protocol):
    """Всё, что эксперимент требует от модели.

    Одна операция: дать ответ на последовательность сообщений. Ни потоков,
    ни инструментов, ни состояния между вызовами — иначе «чистый контекст»
    перестал бы быть чистым.
    """

    name: str

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> Reply:
        ...


def _запрос(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    timeout: float = СЕТЕВОЙ_ТАЙМАУТ,
) -> dict:
    """POST с повторами на временных отказах. Постоянная ошибка — сразу наверх."""
    тело = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    последняя = "причина неизвестна"

    for попытка in range(1, ПОПЫТОК + 1):
        запрос = urllib.request.Request(url, data=тело, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(запрос, timeout=timeout) as ответ:  # noqa: S310
                return json.loads(ответ.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            подробности = exc.read().decode("utf-8", errors="replace")[:500]
            последняя = f"HTTP {exc.code}: {подробности}"
            if exc.code not in ВРЕМЕННЫЕ_КОДЫ:
                raise ProviderError(последняя) from exc
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            последняя = f"{type(exc).__name__}: {exc}"

        if попытка < ПОПЫТОК:
            time.sleep(ПАУЗА_МЕЖДУ_ПОПЫТКАМИ * попытка)

    raise ProviderError(f"не удалось получить ответ за {ПОПЫТОК} попытки — {последняя}")


class AnthropicClient:
    """Messages API. Системный промпт — отдельным полем, не сообщением."""

    def __init__(self, model: str, api_key: str) -> None:
        self.name = f"anthropic:{model}"
        self._model = model
        self._key = api_key

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> Reply:
        данные = _запрос(
            ANTHROPIC_URL,
            {
                "x-api-key": self._key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            {
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            },
        )

        куски = [
            часть.get("text", "")
            for часть in данные.get("content", [])
            if isinstance(часть, dict) and часть.get("type") == "text"
        ]
        if not куски:
            raise ProviderError(f"в ответе нет текста: {str(данные)[:300]}")

        расход = данные.get("usage", {})
        return Reply(
            "".join(куски),
            int(расход.get("input_tokens", 0)),
            int(расход.get("output_tokens", 0)),
        )


class OpenAIClient:
    """Chat Completions. Системный промпт — первым сообщением."""

    def __init__(self, model: str, api_key: str) -> None:
        self.name = f"openai:{model}"
        self._model = model
        self._key = api_key
        # Часть новых моделей не принимает max_tokens и temperature. Переключаемся
        # на ходу, один раз за жизнь клиента. Путь НЕ проверен живьём.
        self._новый_формат = False

    def _тело(
        self,
        messages: Sequence[Message],
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, object]:
        реплики = [{"role": "system", "content": system}]
        реплики += [{"role": m.role, "content": m.content} for m in messages]
        тело: dict[str, object] = {"model": self._model, "messages": реплики}
        if self._новый_формат:
            тело["max_completion_tokens"] = max_tokens
        else:
            тело["max_tokens"] = max_tokens
            тело["temperature"] = temperature
        return тело

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> Reply:
        заголовки = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        try:
            данные = _запрос(
                OPENAI_URL, заголовки, self._тело(messages, system, temperature, max_tokens)
            )
        except ProviderError as exc:
            if self._новый_формат or "max_completion_tokens" not in str(exc):
                raise
            self._новый_формат = True
            данные = _запрос(
                OPENAI_URL, заголовки, self._тело(messages, system, temperature, max_tokens)
            )

        выборы = данные.get("choices") or []
        if not выборы:
            raise ProviderError(f"в ответе нет choices: {str(данные)[:300]}")
        текст = (выборы[0].get("message") or {}).get("content") or ""
        if not текст.strip():
            raise ProviderError(f"пустой текст ответа: {str(данные)[:300]}")

        расход = данные.get("usage", {})
        return Reply(
            текст,
            int(расход.get("prompt_tokens", 0)),
            int(расход.get("completion_tokens", 0)),
        )


def построить(spec: str) -> ModelClient:
    """Собирает клиента по строке «провайдер:модель».

    Идентификаторы моделей задаёт вызывающий: они меняются чаще, чем код,
    и вшивать их сюда — способ однажды тихо промахнуться.
    """
    провайдер, _, модель = spec.partition(":")
    провайдер = провайдер.strip().lower()
    модель = модель.strip()

    if not модель:
        raise ProviderError(
            f"нужен формат «провайдер:модель», а пришло «{spec}» "
            "(например anthropic:claude-sonnet-4-5)"
        )

    if провайдер == "anthropic":
        return AnthropicClient(модель, _ключ(КЛЮЧ_ANTHROPIC))
    if провайдер == "openai":
        return OpenAIClient(модель, _ключ(КЛЮЧ_OPENAI))

    raise ProviderError(
        f"неизвестный провайдер «{провайдер}»: знаем anthropic и openai"
    )


def _ключ(имя: str) -> str:
    значение = os.environ.get(имя, "").strip()
    if not значение:
        raise ProviderError(
            f"нет переменной окружения {имя}. Без ключа доступен только "
            "сухой прогон: python3 -m experiments.echo --dry-run"
        )
    return значение
