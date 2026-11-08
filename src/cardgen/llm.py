"""Тонкая обёртка над Anthropic API. Ключ берётся только из окружения."""
from __future__ import annotations

import os
from typing import Protocol

from .prompts import CARD_TOOL, SYSTEM_PROMPT

DEFAULT_MODEL = "claude-sonnet-5-5"


class LLMError(Exception):
    """Ошибка обращения к LLM (понятное сообщение для пользователя)."""


class LLMClient(Protocol):
    def generate(self, user_message: str) -> dict: ...


class AnthropicClient:
    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: float = 60.0):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError(
                "Не найден ANTHROPIC_API_KEY. Создайте файл .env по образцу .env.example "
                "или задайте переменную окружения."
            )
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise LLMError("Не установлен пакет anthropic: pip install -r requirements.txt") from e
        self._anthropic = anthropic
        # max_retries — встроенные повторы SDK на 429/5xx/сетевые сбои с экспоненциальной паузой.
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=3)
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    def generate(self, user_message: str) -> dict:
        a = self._anthropic
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=2500,
                system=SYSTEM_PROMPT,
                tools=[CARD_TOOL],
                tool_choice={"type": "tool", "name": CARD_TOOL["name"]},
                messages=[{"role": "user", "content": user_message}],
            )
        except a.AuthenticationError as e:
            raise LLMError("API отклонил ключ (401). Проверьте ANTHROPIC_API_KEY.") from e
        except a.PermissionDeniedError as e:
            raise LLMError("Нет доступа к модели или API (403).") from e
        except a.NotFoundError as e:
            raise LLMError(f"Модель «{self.model}» не найдена. Задайте ANTHROPIC_MODEL.") from e
        except a.RateLimitError as e:
            raise LLMError("Превышен лимит запросов (429) даже после повторов. Попробуйте позже.") from e
        except a.APITimeoutError as e:
            raise LLMError("Таймаут запроса к API.") from e
        except a.APIConnectionError as e:
            raise LLMError("Нет соединения с API. Проверьте интернет/прокси.") from e
        except a.BadRequestError as e:
            raise LLMError(f"API отклонил запрос (400): {e}") from e
        except a.APIStatusError as e:
            raise LLMError(f"Ошибка API ({e.status_code}): {e}") from e

        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == CARD_TOOL["name"]:
                if isinstance(block.input, dict):
                    return block.input
        raise LLMError("Модель не вернула структурированный ответ (нет вызова save_card).")


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAIClient:
    """OpenAI и совместимые API (задайте OPENAI_BASE_URL для других провайдеров)."""

    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: float = 60.0):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise LLMError(
                "Не найден OPENAI_API_KEY. Впишите его в .env (см. .env.example) или задайте переменную окружения."
            )
        try:
            import openai
        except ImportError as e:  # pragma: no cover
            raise LLMError("Не установлен пакет openai: pip install openai") from e
        self._openai = openai
        self._client = openai.OpenAI(
            api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or None, timeout=timeout, max_retries=3
        )
        self.model = model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL

    def generate(self, user_message: str) -> dict:
        import json

        o = self._openai
        tool = {"type": "function", "function": {
            "name": CARD_TOOL["name"], "description": CARD_TOOL["description"],
            "parameters": CARD_TOOL["input_schema"]}}
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": user_message}],
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": CARD_TOOL["name"]}},
                # Без лимита OpenRouter резервирует максимум модели (~131 тыс. токенов) и требует баланс под него.
                max_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS") or 2500),
            )
        except o.AuthenticationError as e:
            raise LLMError("API отклонил ключ (401). Проверьте OPENAI_API_KEY.") from e
        except o.PermissionDeniedError as e:
            raise LLMError("Нет доступа к модели или API (403).") from e
        except o.NotFoundError as e:
            raise LLMError(f"Модель «{self.model}» не найдена. Задайте OPENAI_MODEL.") from e
        except o.RateLimitError as e:
            raise LLMError("Превышен лимит запросов или квота (429). Проверьте баланс/лимиты.") from e
        except o.APITimeoutError as e:
            raise LLMError("Таймаут запроса к API.") from e
        except o.APIConnectionError as e:
            raise LLMError("Нет соединения с API. Проверьте интернет/прокси/OPENAI_BASE_URL.") from e
        except o.BadRequestError as e:
            raise LLMError(f"API отклонил запрос (400): {e}") from e
        except o.APIStatusError as e:
            if e.status_code == 402:
                raise LLMError("Недостаточно кредитов на счёте (402). Пополните баланс провайдера "
                               "или уменьшите MAX_OUTPUT_TOKENS в .env.") from e
            raise LLMError(f"Ошибка API ({e.status_code}): {e}") from e

        calls = resp.choices[0].message.tool_calls if resp.choices else None
        if not calls:
            raise LLMError("Модель не вернула структурированный ответ (нет вызова save_card).")
        try:
            data = json.loads(calls[0].function.arguments)
        except (json.JSONDecodeError, TypeError) as e:
            raise LLMError("Модель вернула некорректный JSON.") from e
        if not isinstance(data, dict):
            raise LLMError("Модель вернула ответ неверной формы.")
        return data


def create_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    """provider: anthropic | openai. Если не задан: LLM_PROVIDER, иначе по тому, какой ключ есть в окружении."""
    provider = (provider or os.environ.get("LLM_PROVIDER") or "").lower()
    if not provider:
        if os.environ.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            raise LLMError("Не найден ни ANTHROPIC_API_KEY, ни OPENAI_API_KEY. Впишите ключ в .env.")
    if provider == "anthropic":
        return AnthropicClient(model=model)
    if provider == "openai":
        return OpenAIClient(model=model)
    raise LLMError(f"Неизвестный провайдер «{provider}». Допустимо: anthropic, openai.")
