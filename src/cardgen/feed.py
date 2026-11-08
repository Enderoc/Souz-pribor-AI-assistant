"""Загрузка товаров из фида: YML (XML) или текстовая выгрузка СОЮЗ-ПРИБОР. Формат определяется автоматически."""
from __future__ import annotations

import html
import io
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Iterator

from . import catalog_parser
from .schema import InputError

DEFAULT_FEED_URL = "https://www.souz-pribor.ru/yml/any/feed.xml"

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*(br|/p|/li|/tr)\s*/?>", re.I)


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _strip_html(s: str) -> str:
    s = _BR_RE.sub("\n", html.unescape(s))
    s = _TAG_RE.sub("", s)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", s)).strip()


# ---------- YML ----------
def offer_to_raw(offer: ET.Element) -> dict:
    """<offer> → вход сервиса {name, manufacturer, specs, description, images, url}. Цена и наличие не берутся."""
    name = _text(offer.find("name"))
    if not name:  # «произвольный» тип YML: typePrefix + vendor + model
        name = " ".join(x for x in (_text(offer.find("typePrefix")), _text(offer.find("vendor")),
                                    _text(offer.find("model"))) if x)
    specs: dict[str, str] = {}
    for p in offer.findall("param"):
        key = (p.get("name") or "").strip()
        unit = (p.get("unit") or "").strip()
        val = _text(p)
        if key:
            specs[key] = f"{val} {unit}".strip() if val else ""
    return {
        "name": name,
        "manufacturer": _text(offer.find("vendor")),
        "specs": specs,
        "description": _strip_html(_text(offer.find("description"))),
        "images": [t for t in (_text(p) for p in offer.findall("picture")) if t],
        "url": _text(offer.find("url")),
        "_offer_id": offer.get("id", ""),
    }


# ---------- текстовая выгрузка ----------
def item_to_raw(p: catalog_parser.Product) -> dict:
    """Строка каталога → вход сервиса. Цена, ID категории и product_id модели не нужны и не передаются."""
    specs = {"артикул": p.article} if p.article else {}
    return {
        "name": p.name,
        "manufacturer": p.brand,
        "specs": specs,
        "description": "",
        "images": [p.image_url] if p.image_url else [],
        "url": p.url,
        "_offer_id": str(p.product_id) if p.product_id else p.url.rstrip("/").rsplit("/", 1)[-1],
    }


# ---------- общее ----------
def read_source(source: str, timeout: float = 60.0) -> bytes:
    try:
        if source.startswith(("http://", "https://")):
            req = urllib.request.Request(source, headers={"User-Agent": "cardgen/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        with open(source, "rb") as f:
            return f.read()
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise InputError(f"Не удалось открыть фид {source}: {e}") from e


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def is_xml(data: bytes) -> bool:
    return data.lstrip(b"\xef\xbb\xbf \r\n\t")[:1] == b"<"


def iter_offers(source: str, timeout: float = 60.0) -> Iterator[dict]:
    data = read_source(source, timeout)
    if is_xml(data):
        try:
            for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
                if el.tag.split("}")[-1] == "offer":
                    yield offer_to_raw(el)
                    el.clear()
        except ET.ParseError as e:
            raise InputError(f"Фид не является корректным XML: {e}") from e
    else:
        for p in catalog_parser.parse_text(_decode(data)).products:
            yield item_to_raw(p)


def select_offers(source: str, search: str | None = None, offer_ids: list[str] | None = None,
                  limit: int = 2, min_specs: int = 0) -> list[dict]:
    """Первые `limit` товаров, подходящих под фильтр (подстрока в названии без учёта регистра / id)."""
    found: list[dict] = []
    needle = search.lower() if search else None
    seen = by_id = by_search = by_specs = 0
    max_specs = 0
    for raw in iter_offers(source):
        seen += 1
        n_specs = sum(1 for v in raw["specs"].values() if v)
        max_specs = max(max_specs, n_specs)
        if offer_ids and raw["_offer_id"] not in offer_ids:
            by_id += 1
            continue
        if needle and needle not in raw["name"].lower():
            by_search += 1
            continue
        if n_specs < min_specs:
            by_specs += 1
            continue
        found.append(raw)
        if len(found) >= limit:
            break
    if not found:
        if seen == 0:
            raise InputError(
                "В фиде не найдено ни одного товара (ни тегов <offer>, ни строк текстовой выгрузки). "
                "Запустите с --inspect и пришлите вывод.")
        raise InputError(
            f"В фиде просмотрено товаров: {seen}, подходящих нет. Отсеяно: по --offer-id {by_id}, "
            f"по --search {by_search}, по --min-specs {by_specs} (максимум заполненных параметров "
            f"у одного товара: {max_specs}). Попробуйте убрать --min-specs или --search.")
    return found


def inspect_feed(source: str, max_chars: int = 3000) -> str:
    """Формат фида и первые товары: помогает понять структуру, если разбор ничего не находит."""
    data = read_source(source)
    if not is_xml(data):
        res = catalog_parser.parse_text(_decode(data))
        head = (f"Формат: текстовая выгрузка. Товаров: {len(res.products)}, "
                f"невалидных строк: {len(res.invalid)}, пропущено не-товаров: {res.skipped_non_product}.\n")
        sample = [{k: v for k, v in item_to_raw(p).items()} for p in res.products[:2]]
        return head + json.dumps(sample, ensure_ascii=False, indent=2)[:max_chars]
    tags: list[str] = []
    try:
        for _, el in ET.iterparse(io.BytesIO(data), events=("end",)):
            tag = el.tag.split("}")[-1]
            if len(tags) < 15 and tag not in tags:
                tags.append(tag)
            if tag == "offer":
                return f"Формат: XML. Первые теги: {', '.join(tags)}\n\n{ET.tostring(el, encoding='unicode')[:max_chars]}"
    except ET.ParseError as e:
        raise InputError(f"Фид не является корректным XML: {e}") from e
    return f"Формат: XML, но тег <offer> не найден. Встреченные теги: {', '.join(tags) or 'нет'}"
