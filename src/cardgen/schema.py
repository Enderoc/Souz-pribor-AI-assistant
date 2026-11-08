"""Разбор и нормализация входных данных. Здесь же определяется, каких данных не хватает."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

NO_DATA = "данных нет"

# Значения, которые считаем «пустыми».
_EMPTY_MARKERS = {"", "-", "—", "–", "n/a", "na", "null", "none", "нет", "нет данных", "н/д", "?"}

# Базовый набор характеристик из задания: (название, подстроки для поиска в ключах specs).
BASELINE_SPECS: list[tuple[str, tuple[str, ...]]] = [
    ("Диапазон измерений", ("диапазон",)),
    ("Класс точности", ("класс точности", "погрешност")),
    ("Питание", ("питани",)),
    ("Тип корпуса", ("корпус",)),
    ("Интерфейсы", ("интерфейс", "выход", "rs-485", "rs485", "hart", "modbus")),
]


class InputError(Exception):
    """Входные данные непригодны для генерации."""


@dataclass
class Product:
    name: str = ""
    manufacturer: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    description: str = ""
    images: list[str] = field(default_factory=list)  # не отправляются в модель, только попадают в результат
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name or None,
            "manufacturer": self.manufacturer or None,
            "specs": self.specs,
            "description": self.description or None,
        }

    def source_text(self) -> str:
        """Весь текст входных данных — «источник истины» для проверки ответа модели."""
        parts = [self.name, self.manufacturer, self.description]
        for k, v in self.specs.items():
            parts += [k, v]
        return "\n".join(parts)


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_MARKERS else text


def parse_json(text: str):
    if not text or not text.strip():
        raise InputError("Пустой ввод: ожидается JSON с данными о товаре.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise InputError(f"Некорректный JSON (строка {e.lineno}, столбец {e.colno}): {e.msg}") from e


def parse_product(raw) -> tuple[Product, list[str]]:
    """Возвращает (товар, список отсутствующих входных полей) или бросает InputError."""
    if not isinstance(raw, dict):
        raise InputError("Товар должен быть JSON-объектом, а не " + type(raw).__name__ + ".")

    name = _clean(raw.get("name"))  # название необязательно, но тогда карточка строится по specs/description

    specs_raw = raw.get("specs")
    if specs_raw is None:
        specs_raw = {}
    if not isinstance(specs_raw, dict):
        raise InputError("Поле «specs» должно быть объектом вида {\"характеристика\": \"значение\"}.")

    specs: dict[str, str] = {}
    empty_specs: list[str] = []
    for key, value in specs_raw.items():
        k, v = _clean(key), _clean(value)
        if not k:
            continue
        if v:
            specs[k] = v
        else:
            empty_specs.append(k)

    imgs = raw.get("images")
    if isinstance(imgs, str):
        imgs = [imgs]
    images = [i.strip() for i in imgs if isinstance(i, str) and i.strip().startswith(("http://", "https://"))] \
        if isinstance(imgs, list) else []
    url = _clean(raw.get("url"))
    product = Product(
        name=name,
        images=images,
        url=url if url.startswith(("http://", "https://")) else "",
        manufacturer=_clean(raw.get("manufacturer")),
        specs=specs,
        description=_clean(raw.get("description")),
    )

    if not (product.name or product.specs or product.description):
        raise InputError("Нет ни названия, ни характеристик («specs»), ни описания («description») — писать карточку не из чего.")

    missing: list[str] = []
    if not product.name:
        missing.append("name")
    if not product.manufacturer:
        missing.append("manufacturer")
    if not product.specs:
        missing.append("specs")
    if not product.description:
        missing.append("description")
    missing += [f"specs.{k} (пустое значение)" for k in empty_specs]
    return product, missing


def load_products(text: str) -> list:
    """Принимает один объект или массив объектов."""
    data = parse_json(text)
    if isinstance(data, list):
        if not data:
            raise InputError("Пустой массив товаров.")
        return data
    return [data]


def build_characteristics(product: Product) -> list[dict]:
    """Список характеристик собирается КОДОМ из входных данных — модель не может их исказить.
    Отсутствующие базовые характеристики помечаются «данных нет»."""
    rows = [{"name": k, "value": v} for k, v in product.specs.items()]
    keys_lower = [k.lower() for k in product.specs]
    for title, needles in BASELINE_SPECS:
        if not any(n in k for k in keys_lower for n in needles):
            rows.append({"name": title, "value": NO_DATA})
    return rows
