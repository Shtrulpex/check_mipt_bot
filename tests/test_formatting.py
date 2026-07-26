from parser.msu import MsuParser
from parser.parser import format_results

from tests.test_parsers import RATING_HTML


def test_report_explains_official_priorities():
    parser = MsuParser("https://cpk.msu.ru/rating/dep_02", expected_year=2026)
    parser.results = parser.parse(RATING_HTML)
    text = format_results("123456789012", parser.lookup("123456789012"), parser)
    assert "Основной высший приоритет: да" in text
    assert "Высший проходной приоритет: да" in text
    assert "соответствует высшему проходному приоритету" in text


def test_missing_id_is_explicit():
    parser = MsuParser("https://cpk.msu.ru/rating/dep_02", expected_year=2026)
    parser.results = parser.parse(RATING_HTML)
    assert "не найден" in parser("000")
