import pytest

from cardgen.feed import select_offers
from cardgen.schema import InputError, parse_product

XML = """<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog><shop><offers>
<offer id="11"><name>Манометр ДМ 02</name><vendor>Манотомь</vendor><price>500</price>
<description><![CDATA[<p>Для измерения давления.</p><ul><li>Класс 1,5</li></ul>]]></description>
<url>https://example.com/p/11</url><picture>https://example.com/1.jpg</picture><picture>https://example.com/2.jpg</picture>
<param name="Диапазон" unit="МПа">0-1,6</param><param name="Пустой"></param></offer>
<offer id="12"><typePrefix>Термометр</typePrefix><vendor>X</vendor><model>T-1</model></offer>
</offers></shop></yml_catalog>"""


@pytest.fixture

def feed(tmp_path):
    f = tmp_path / "feed.xml"
    f.write_text(XML, encoding="utf-8")
    return str(f)


def test_offer_parsed_without_price(feed):
    raw = select_offers(feed, search="манометр")[0]
    assert raw["specs"]["Диапазон"] == "0-1,6 МПа"
    assert "Для измерения давления." in raw["description"] and "<" not in raw["description"]
    assert "500" not in str(raw)
    p, missing = parse_product(raw)
    assert any("Пустой" in m for m in missing)


def test_typeprefix_name_fallback(feed):
    assert select_offers(feed, offer_ids=["12"])[0]["name"] == "Термометр X T-1"


def test_no_match(feed):
    with pytest.raises(InputError):
        select_offers(feed, search="расходомер")


def test_images_collected_and_not_sent_to_model(feed):
    raw = select_offers(feed, search="манометр")[0]
    p, _ = parse_product(raw)
    assert p.images == ["https://example.com/1.jpg", "https://example.com/2.jpg"]
    assert p.url == "https://example.com/p/11"
    assert "jpg" not in str(p.to_dict())
