"""Автоматическая проверка ответа модели: структура, длины, «выдуманные» числа и факты."""
from __future__ import annotations

import re

from .schema import Product

TITLE_MAX = 70
DESC_MIN, DESC_MAX = 800, 1200

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")

# Темы, которые модель любит додумывать. Если слово есть в ответе, но нет во входных данных — замечание.
_RISKY_FACTS = {
    "ГОСТ": r"гост",
    "сертификат": r"сертифик",
    "ISO": r"\biso\b",
    "степень защиты IP": r"\bip\s?\d",
    "поверка": r"поверк",
    "гарантия": r"гаранти",
    "взрывозащита": r"взрывозащ|\bex\b",
    "ТУ": r"\bту\s?\d",
}


def _norm_num(s: str) -> str:
    s = s.replace(",", ".")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def numbers_in(text: str) -> set[str]:
    return {_norm_num(m) for m in _NUM_RE.findall(text)}


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings(v)]
    return []


def check_structure(card) -> list[str]:
    """Ошибки формы — после них остальные проверки бессмысленны."""
    if not isinstance(card, dict):
        return ["Ответ не является объектом."]
    issues = []
    for key in ("seo_title", "seo_description"):
        if not isinstance(card.get(key), str) or not card[key].strip():
            issues.append(f"Поле {key} пустое или отсутствует.")
    q = card.get("search_queries")
    if not isinstance(q, list) or not all(isinstance(x, str) and x.strip() for x in q):
        issues.append("search_queries должен быть списком непустых строк.")
    elif not 3 <= len(q) <= 5:
        issues.append(f"search_queries: нужно 3–5 запросов, получено {len(q)}.")
    c = card.get("commercial")
    if not (isinstance(c, dict) and isinstance(c.get("suitable_for"), list) and isinstance(c.get("tasks"), list)
            and c["suitable_for"] and c["tasks"]):
        issues.append("commercial должен содержать непустые suitable_for и tasks.")
    md = card.get("missing_data")
    if not (isinstance(md, list) and all(isinstance(x, dict) and "field" in x for x in md)):
        issues.append("missing_data должен быть списком объектов {field, why}.")
    return issues


def check_content(card: dict, product: Product) -> list[str]:
    issues: list[str] = []

    title = card["seo_title"].strip()
    if len(title) > TITLE_MAX:
        issues.append(f"seo_title длиной {len(title)} символов, максимум {TITLE_MAX}. Сократи.")

    desc = card["seo_description"].strip()
    n = len(desc)
    reason = (card.get("description_too_short_reason") or "").strip()
    if n > DESC_MAX:
        issues.append(f"seo_description длиной {n} символов, максимум {DESC_MAX}. Сократи без потери фактов.")
    elif n < DESC_MIN and not reason:
        issues.append(
            f"seo_description длиной {n} символов, нужно {DESC_MIN}–{DESC_MAX}. Расширь за счёт ТОЛЬКО "
            "имеющихся данных либо заполни description_too_short_reason."
        )
    if re.search(r"^\s*([-*•]|\d+\.)\s", desc, re.M) or "**" in desc or "#" in desc:
        issues.append("seo_description должен быть обычным текстом без списков и markdown.")

    source = product.source_text()
    allowed = numbers_in(source)
    out_text = "\n".join(_strings({k: v for k, v in card.items() if k != "description_too_short_reason"}))
    bad = sorted(numbers_in(out_text) - allowed)
    if bad:
        issues.append(
            "В тексте есть числа, которых нет во входных данных: " + ", ".join(bad) +
            ". Удали их или замени формулировкой без чисел."
        )

    # Вопросы к поставщику (missing_data, manager_notes) могут законно упоминать «поверку», «ГОСТ» и т. п.
    public = {k: v for k, v in card.items() if k not in ("description_too_short_reason", "missing_data", "manager_notes")}
    src_low, out_low = source.lower(), "\n".join(_strings(public)).lower()
    for label, pattern in _RISKY_FACTS.items():
        if re.search(pattern, out_low) and not re.search(pattern, src_low):
            issues.append(f"Упомянуто «{label}», но во входных данных этого нет. Удали упоминание.")
    return issues
