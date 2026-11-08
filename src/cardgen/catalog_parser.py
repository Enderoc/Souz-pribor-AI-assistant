"""Парсер текстовой выгрузки каталога СОЮЗ-ПРИБОР (одна строка = один товар, поля через пробел).

Формат строки:
    name URL category_id brand [article] [image_url] price RUR [article_dup] [product_id]

Только стандартная библиотека. Запуск:
    python -m cardgen.catalog_parser catalog.txt -o out_catalog
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import re
import sys
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("catalog_parser")
log.addHandler(logging.NullHandler())  # как библиотека молчим; CLI парсера включает вывод через basicConfig

# --- Константы и регулярные выражения -----------------------------------------------------------

PRODUCT_URL_MARK = "https://www.souz-pribor.ru/product/"

# Известные бренды: подсказка для отделения (возможно многословного) бренда от артикула, не жёсткий фильтр.
KNOWN_BRANDS: tuple[str, ...] = (
    "ОВЕН", "Мега-К", "Testo", "Декаст", "Тепловодомер", "ПРОМА", "Информаналитика", "Аналитприбор",
    "Кропус", "АКТАКОМ", "ТКА", "Center", "НТМ-Защита", "Гидрометприбор",
    "Златоустовский часовой завод", "Россия",
)

# Признак строки-товара: ссылка на карточку товара + цена в RUR (заголовок их не содержит).
_PRODUCT_HINT_RE = re.compile(r"RUR\b")

# Вся строка целиком. Якоря: первый https://, затем category_id, затем «середина» (бренд + артикул),
# необязательный URL картинки, цена с RUR и «хвост» (article_dup и/или product_id).
# Ленивые квантификаторы подбирают самую короткую «середину», после которой дальше идёт [картинка] цена RUR.
LINE_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<url>https?://\S+)\s+"
    r"(?P<category_id>\d+)\s+"
    r"(?P<middle>.+?)\s+"
    r"(?:(?P<image_url>https?://\S+)\s+)?"
    r"(?P<price>\d+(?:\.\d+)?)\s+RUR"
    r"(?:\s+(?P<tail>.*?))?\s*$"
)


class LineError(ValueError):
    """Строка похожа на товар, но не разобрана или не прошла валидацию."""


@dataclass
class Product:
    name: str
    url: str
    category_id: int
    brand: str
    article: str
    image_url: str | None
    price: int | float
    article_dup: str
    product_id: int | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParseResult:
    products: list[Product] = field(default_factory=list)
    invalid: list[tuple[int, str, str]] = field(default_factory=list)  # (номер строки, причина, строка)
    skipped_non_product: int = 0
    skipped_empty: int = 0


# --- Разбор одной строки ------------------------------------------------------------------------

def is_product_line(line: str) -> bool:
    return PRODUCT_URL_MARK in line and bool(_PRODUCT_HINT_RE.search(line))


def _sorted_brands(brands) -> list[str]:
    return sorted(brands, key=len, reverse=True)  # сначала самые длинные: «Златоустовский часовой завод»


def split_brand_article(middle: str, brands: list[str]) -> tuple[str, str, bool]:
    """«ОВЕН 58953» → («ОВЕН», «58953», True). Артикул может содержать пробелы и быть пустым.
    Если бренд неизвестен: первый токен = бренд, остальное = артикул (known=False)."""
    low = middle.casefold()
    for b in brands:
        bl = b.casefold()
        if low == bl or low.startswith(bl + " "):
            return middle[: len(b)], middle[len(b):].strip(), True
    head, _, rest = middle.partition(" ")
    return head, rest.strip(), False


def split_tail(tail: str, article: str) -> tuple[str, int | None, str | None]:
    """Хвост после RUR → (article_dup, product_id, предупреждение).

    В реальных данных product_id часто отсутствует, а article_dup может содержать пробелы
    («0563 2051»), поэтому сравниваем с уже найденным артикулом."""
    tail = tail.strip()
    if not tail:
        return "", None, "после RUR нет ни повтора артикула, ни product_id"
    if tail == article:
        return tail, None, None
    if article and tail.startswith(article + " ") and tail[len(article) + 1:].strip().isdigit():
        return article, int(tail[len(article) + 1:]), None
    tokens = tail.split()
    if len(tokens) >= 2 and tokens[-1].isdigit():
        return " ".join(tokens[:-1]), int(tokens[-1]), None
    if len(tokens) == 1:
        if not article and tail.isdigit():
            return "", int(tail), "артикула нет, единственное число после RUR принято за product_id"
        return tail, None, ("повтор артикула отличается от артикула" if article else None)
    return tail, None, "не удалось отделить product_id от повтора артикула"


def parse_line(line: str, brands=KNOWN_BRANDS) -> Product | None:
    """None — строка не товар (заголовок, служебная). LineError — товар, но битый."""
    line = line.strip()
    if not line:
        return None
    has_url, has_price = PRODUCT_URL_MARK in line, bool(_PRODUCT_HINT_RE.search(line))
    if not (has_url or has_price):
        return None  # заголовок и служебные строки
    if has_url != has_price:  # есть только одно из двух: похоже на повреждённый товар
        raise LineError("нет цены RUR" if has_url else "нет ссылки на карточку товара")
    m = LINE_RE.match(line)
    if not m:
        raise LineError("строка не соответствует шаблону name URL category brand ... price RUR")

    warnings: list[str] = []
    brand, article, known = split_brand_article(m["middle"], _sorted_brands(brands))
    if not known:
        warnings.append(f"бренд «{brand}» нет в списке известных (взят первый токен; проверьте артикул)")
    if not article:
        warnings.append("артикул отсутствует")
    dup, product_id, w = split_tail(m["tail"] or "", article)
    if w:
        warnings.append(w)

    price_raw = m["price"]
    price: int | float = int(price_raw) if price_raw.isdigit() else float(price_raw)

    product = Product(
        name=html.unescape(m["name"]).strip(),  # только наименование; артикулы не нормализуем
        url=m["url"],
        category_id=int(m["category_id"]),
        brand=brand,
        article=article,
        image_url=m["image_url"],
        price=price,
        article_dup=dup,
        product_id=product_id,
        warnings=warnings,
    )
    validate(product)
    return product


def validate(p: Product) -> None:
    if not p.name:
        raise LineError("пустое наименование")
    if not p.url.startswith("https://"):
        raise LineError(f"url не начинается с https://: {p.url}")
    if p.image_url is not None and not p.image_url.startswith("https://"):
        raise LineError(f"image_url не начинается с https://: {p.image_url}")
    if not p.brand:
        raise LineError("пустой бренд")
    if p.price <= 0:
        raise LineError(f"цена не положительная: {p.price}")


# --- Файл целиком -------------------------------------------------------------------------------

def parse_text(text: str, brands=KNOWN_BRANDS) -> ParseResult:
    res = ParseResult()
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            res.skipped_empty += 1
            continue
        try:
            p = parse_line(line, brands)
        except LineError as e:
            log.warning("строка %d пропущена: %s", n, e)
            res.invalid.append((n, str(e), line))
            continue
        if p is None:
            res.skipped_non_product += 1
            log.info("строка %d: не товар (заголовок/служебная)", n)
            continue
        for w in p.warnings:
            log.warning("строка %d (%s): %s", n, p.name[:40], w)
        res.products.append(p)
    return res


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_file(path: Path, brands=KNOWN_BRANDS) -> list[Product]:
    return parse_text(read_text(Path(path)), brands).products


# --- Сохранение ---------------------------------------------------------------------------------

CSV_FIELDS = ["name", "url", "category_id", "brand", "article", "image_url", "price", "article_dup", "product_id"]


def save_json(products: list[Product], path: Path) -> None:
    Path(path).write_text(json.dumps([asdict(p) for p in products], ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def save_csv(products: list[Product], path: Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel корректно откроет кириллицу
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for p in products:
            w.writerow({k: ("" if v is None else v) for k, v in asdict(p).items()})


def save_invalid(invalid: list[tuple[int, str, str]], path: Path) -> None:
    Path(path).write_text("".join(f"строка {n}: {reason}\n    {raw}\n" for n, reason, raw in invalid),
                          encoding="utf-8")


def summary(res: ParseResult) -> str:
    ps = res.products
    lines = [f"Товаров разобрано: {len(ps)}",
             f"Пропущено как не-товары (заголовок и т.п.): {res.skipped_non_product}",
             f"Невалидных строк: {len(res.invalid)}",
             f"Товаров с предупреждениями: {sum(1 for p in ps if p.warnings)}"]
    if ps:
        prices = [p.price for p in ps]
        lines += [f"Уникальных брендов: {len({p.brand for p in ps})}",
                  f"Уникальных категорий: {len({p.category_id for p in ps})}",
                  f"Цена: min {min(prices)}, max {max(prices)} RUR",
                  f"Без изображения: {sum(1 for p in ps if p.image_url is None)}",
                  f"Топ брендов: " + ", ".join(f"{b} ({c})" for b, c in Counter(p.brand for p in ps).most_common(5))]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Парсер текстовой выгрузки каталога СОЮЗ-ПРИБОР")
    ap.add_argument("input", help="файл выгрузки или URL")
    ap.add_argument("-o", "--out", default="catalog_out", help="каталог для результатов")
    ap.add_argument("--brands-file", help="файл с дополнительными брендами (по одному в строке)")
    ap.add_argument("-v", "--verbose", action="store_true", help="выводить и информационные сообщения")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s: %(message)s")

    brands = list(KNOWN_BRANDS)
    if args.brands_file:
        brands += [b.strip() for b in read_text(Path(args.brands_file)).splitlines() if b.strip()]
    try:
        if args.input.startswith(("http://", "https://")):
            req = urllib.request.Request(args.input, headers={"User-Agent": "cardgen/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            text = data.decode("utf-8-sig", errors="replace")
        else:
            text = read_text(Path(args.input))
    except OSError as e:
        print(f"Не удалось прочитать {args.input}: {e}", file=sys.stderr)
        return 2

    res = parse_text(text, brands)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    save_json(res.products, out / "products.json")
    save_csv(res.products, out / "products.csv")
    save_invalid(res.invalid, out / "invalid_lines.txt")
    print(summary(res))
    print(f"Результаты: {out}/products.json, products.csv, invalid_lines.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
