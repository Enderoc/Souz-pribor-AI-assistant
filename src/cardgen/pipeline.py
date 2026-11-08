from __future__ import annotations

from .llm import LLMClient, LLMError
from .prompts import build_user_message
from .schema import Product, build_characteristics
from .validate import check_content, check_structure

MAX_ATTEMPTS = 3


def generate_card(product: Product, missing_input: list[str], client: LLMClient) -> dict:
    """Генерация с автоматической проверкой и перегенерацией с обратной связью.

    status: "ok" — все проверки пройдены; "needs_review" — после всех попыток остались замечания,
    они перечислены в warnings, и менеджер должен проверить текст вручную.
    """
    feedback: list[str] | None = None
    previous: dict | None = None
    card = None
    issues: list[str] = []
    attempt = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        card = client.generate(build_user_message(product, missing_input, feedback, previous))
        issues = check_structure(card)
        if not issues:
            issues = check_content(card, product)
        if not issues:
            break
        feedback, previous = issues, (card if isinstance(card, dict) else None)

    if check_structure(card):
        raise LLMError("Модель не смогла вернуть корректную структуру: " + "; ".join(issues))

    return {
        "status": "ok" if not issues else "needs_review",
        "attempts": attempt,
        "product": product.to_dict(),
        "images": product.images,
        "source_url": product.url,
        "missing_input_fields": missing_input,
        "card": {
            "seo_title": card["seo_title"].strip(),
            "seo_description": card["seo_description"].strip(),
            "seo_title_length": len(card["seo_title"].strip()),
            "seo_description_length": len(card["seo_description"].strip()),
            "description_too_short_reason": (card.get("description_too_short_reason") or "").strip(),
            "key_characteristics": build_characteristics(product),  # из входных данных, не от модели
            "search_queries": [q.strip() for q in card["search_queries"]],
            "commercial": card["commercial"],
            "missing_data": card["missing_data"],
            "manager_notes": (card.get("manager_notes") or "").strip(),
        },
        "warnings": issues,
    }
