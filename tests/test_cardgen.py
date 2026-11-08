import copy
import json
from pathlib import Path

import pytest

from cardgen.llm import LLMError
from cardgen.pipeline import generate_card
from cardgen.render import to_markdown
from cardgen.schema import NO_DATA, InputError, build_characteristics, load_products, parse_product
from cardgen.validate import check_content, check_structure, numbers_in

from fake_cards import MANO, TERMO

ROOT = Path(__file__).resolve().parent.parent


def product(name):
    raw = json.loads((ROOT / "examples" / "input" / name).read_text(encoding="utf-8"))
    return parse_product(raw)


class FakeClient:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def generate(self, msg):
        self.calls.append(msg)
        return copy.deepcopy(self.answers.pop(0))


# ---------- вход ----------
def test_invalid_json():
    with pytest.raises(InputError, match="Некорректный JSON"):
        load_products("{oops")


def test_empty_input():
    with pytest.raises(InputError):
        load_products("   ")


@pytest.mark.parametrize("raw", [[], "str", {"name": ""}, {"name": "X", "specs": "bad"}, {"specs": {"a": "-"}}])
def test_unusable_products(raw):
    with pytest.raises(InputError):
        parse_product(raw)


def test_missing_fields_reported():
    p, missing = product("thermometer_tc20.json")
    assert "manufacturer" in missing
    assert any("длина зонда" in m for m in missing)
    assert "длина зонда" not in p.specs


def test_characteristics_marked_no_data():
    p, _ = product("thermometer_tc20.json")
    rows = {r["name"]: r["value"] for r in build_characteristics(p)}
    assert rows["Класс точности"] == NO_DATA
    assert rows["Интерфейсы"] == NO_DATA
    assert rows["питание"] == "2 элемента типа AAA, 3 В"
    assert "Питание" not in rows  # есть во входных данных — дубль «данных нет» не добавляется


# ---------- проверка ответа ----------
def test_examples_pass_validation():
    for f, card in (("manometer_dm02.json", MANO), ("thermometer_tc20.json", TERMO)):
        p, _ = product(f)
        assert check_structure(card) == []
        assert check_content(card, p) == []


def test_number_normalisation():
    assert numbers_in("1,60 МПа и 1.6") == {"1.6"}


def test_invented_number_detected():
    p, _ = product("manometer_dm02.json")
    bad = copy.deepcopy(MANO)
    bad["seo_description"] += " Рабочая температура до 150 градусов."
    assert any("150" in i for i in check_content(bad, p))


def test_invented_standard_detected():
    p, _ = product("manometer_dm02.json")
    bad = copy.deepcopy(MANO)
    bad["seo_description"] += " Соответствует ГОСТ."
    assert any("ГОСТ" in i for i in check_content(bad, p))


def test_questions_may_mention_gost():
    p, _ = product("manometer_dm02.json")
    assert check_content(MANO, p) == []  # в MANO.missing_data упоминаются ТУ/ГОСТ


def test_title_length():
    p, _ = product("manometer_dm02.json")
    bad = copy.deepcopy(MANO)
    bad["seo_title"] = "Т" * 71
    assert any("seo_title" in i for i in check_content(bad, p))


# ---------- пайплайн ----------
def test_pipeline_ok_first_try():
    p, m = product("manometer_dm02.json")
    r = generate_card(p, m, FakeClient(MANO))
    assert r["status"] == "ok" and r["attempts"] == 1
    assert "Тип корпуса" not in {x["name"] for x in r["card"]["key_characteristics"]}


def test_pipeline_retries_with_feedback():
    p, m = product("manometer_dm02.json")
    bad = copy.deepcopy(MANO)
    bad["seo_description"] += " Температура до 150."
    client = FakeClient(bad, MANO)
    r = generate_card(p, m, client)
    assert r["status"] == "ok" and r["attempts"] == 2
    assert "150" in client.calls[1]  # замечание передано модели


def test_pipeline_needs_review_after_failed_retries():
    p, m = product("manometer_dm02.json")
    bad = copy.deepcopy(MANO)
    bad["seo_description"] += " Температура до 150."
    r = generate_card(p, m, FakeClient(bad, bad, bad))
    assert r["status"] == "needs_review" and r["warnings"]
    assert "Требует ручной проверки" in to_markdown(r)


def test_pipeline_broken_structure_raises():
    p, m = product("manometer_dm02.json")
    with pytest.raises(LLMError):
        generate_card(p, m, FakeClient({}, {}, {}))


def test_markdown_has_all_sections():
    p, m = product("thermometer_tc20.json")
    md = to_markdown(generate_card(p, m, FakeClient(TERMO)))
    for part in ("## SEO-описание", "## Ключевые характеристики", "## Поисковые запросы",
                 "## Для менеджера", "## Что нужно уточнить", NO_DATA):
        assert part in md


def test_create_client_requires_key(monkeypatch):
    from cardgen.llm import create_client
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(LLMError):
        create_client()
    with pytest.raises(LLMError, match="Неизвестный"):
        create_client("foo")


def test_name_is_optional():
    p, missing = parse_product({"specs": {"диапазон": "0–10 бар"}})
    assert p.name == "" and "name" in missing
    assert p.to_dict()["name"] is None


def test_name_only_product_is_allowed_but_flagged():
    p, missing = parse_product({"name": "Манометр ДМ 02"})
    assert "specs" in missing and "description" in missing
