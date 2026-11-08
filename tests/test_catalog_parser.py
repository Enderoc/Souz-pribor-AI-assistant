from pathlib import Path

from cardgen.catalog_parser import LineError, parse_file, parse_line, parse_text
from cardgen.feed import select_offers
from cardgen.schema import parse_product

ROOT = Path(__file__).resolve().parent.parent
LINES = {
    "mk110": "МК110-224.8Д.4Р [М01] комбинированный модуль ввода/вывода дискретных сигналов https://www.souz-pribor.ru/product/mk110-8d-4r/ 345 ОВЕН 58953 https://www.souz-pribor.ru/upload/iblock/4e8/e2zaz363p275vnb1rrqilm9u0j9sbzez/IMG_7719.jpg 12993 RUR 58953 63483",
    "osvu": "ОСВУ-40 &quot;Нептун&quot; счетчик воды универсальный https://www.souz-pribor.ru/product/osvu/ 393 Декаст 75-40-01 https://www.souz-pribor.ru/upload/iblock/966/1.jpg 22358 RUR 75-40-01",
    "testo": "testo 205 рН-метр с проникающим зондом https://www.souz-pribor.ru/product/testo-205/ 386 Testo 0563 2051 https://www.souz-pribor.ru/upload/iblock/6fe/6fe93d71132f82bb8a7d7e4cedf5f0e2.jpg 25867 RUR 0563 2051",
    "ez": "ЭЗ-02 L-1400 электрозапальник газовый https://www.souz-pribor.ru/product/ez/ 352 ПРОМА Б12706 https://www.souz-pribor.ru/upload/iblock/5e7/5e75b8485d86cbd4a04f35aef8efe812.jpg 14152 RUR Б12706",
    "vskh": "ВСХн-25 счетчик холодной воды https://www.souz-pribor.ru/product/vskh/ 393 Тепловодомер R110-025-320-B54 https://www.souz-pribor.ru/upload/iblock/19e/VSKH_25.jpg 16894 RUR R110-025-320-B54",
    "mkesh": "МКЭШ 5х0,75 кабель к термопреобразователям сопротивления https://www.souz-pribor.ru/product/mkesh/ 336 Россия https://www.souz-pribor.ru/upload/iblock/efb/n2qt2fdsx4fkkbxlml0uidk2vdlzdtaf/MKESH.png 276 RUR 60413",
    "nophoto": "Декаст 76-25-01 счётчик https://www.souz-pribor.ru/product/np/ 393 Декаст 76-25-01 13293 RUR 76-25-01 70001",
}


def test_with_image_all_fields():
    p = parse_line(LINES["mk110"])
    assert (p.category_id, p.brand, p.article, p.price, p.article_dup, p.product_id) == (345, "ОВЕН", "58953", 12993, "58953", 63483)
    assert p.image_url.endswith("IMG_7719.jpg") and p.name.startswith("МК110-224.8Д.4Р [М01]")


def test_without_image():
    p = parse_line(LINES["nophoto"])
    assert p.image_url is None and p.article == "76-25-01" and p.price == 13293 and p.product_id == 70001


def test_html_entities_in_name():
    assert parse_line(LINES["osvu"]).name == 'ОСВУ-40 "Нептун" счетчик воды универсальный'


def test_article_with_space_is_kept():
    p = parse_line(LINES["testo"])
    assert (p.brand, p.article, p.article_dup) == ("Testo", "0563 2051", "0563 2051") and p.product_id is None


def test_cyrillic_article():
    p = parse_line(LINES["ez"])
    assert (p.brand, p.article, p.article_dup) == ("ПРОМА", "Б12706", "Б12706")


def test_latin_dash_article():
    p = parse_line(LINES["vskh"])
    assert (p.brand, p.article) == ("Тепловодомер", "R110-025-320-B54") and p.price == 16894


def test_cable_brand_russia_without_article():
    p = parse_line(LINES["mkesh"])
    assert p.brand == "Россия" and p.article == "" and p.price == 276 and p.product_id == 60413
    assert p.warnings  # неоднозначность помечена


def test_multiword_brand():
    line = "Часы https://www.souz-pribor.ru/product/c/ 5 Златоустовский часовой завод ZCH-1 100 RUR ZCH-1 9"
    p = parse_line(line)
    assert (p.brand, p.article, p.product_id) == ("Златоустовский часовой завод", "ZCH-1", 9)


def test_header_and_empty_are_skipped():
    header = "СОЮЗ-ПРИБОР https://www.souz-pribor.ru Оборудование для промышленной автоматизации Измерители-регуляторы"
    assert parse_line(header) is None and parse_line("   ") is None


def test_broken_product_line_is_invalid():
    try:
        parse_line("Битая https://www.souz-pribor.ru/product/x/ 100 ОВЕН 111")
    except LineError as e:
        assert "RUR" in str(e)
    else:
        raise AssertionError("ожидалась LineError")


def test_file_stats():
    res = parse_text("\n".join(LINES.values()) + "\n\nБитая https://www.souz-pribor.ru/product/x/ 1 ОВЕН\n")
    assert len(res.products) == 7 and len(res.invalid) == 1 and res.skipped_empty == 1


def test_sample_file_and_feed_integration():
    path = ROOT / "examples" / "catalog_sample.txt"
    assert len(parse_file(path)) == 7
    raw = select_offers(str(path), search="testo", limit=1)[0]
    p, missing = parse_product(raw)
    assert p.manufacturer == "Testo" and p.specs == {"артикул": "0563 2051"}
    assert p.images and p.url.endswith("/testo-205/") and "description" in missing
