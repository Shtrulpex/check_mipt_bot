from parser.mipt import MiptParser
from parser.msu import MsuParser
from parser.parser import AdmissionStage, UnsupportedSourceError, default_registry


SUBMITTED_HTML = """
<html><head><title>Приёмная кампания МГУ 2026</title></head><body>
<h1>Факультет вычислительной математики и кибернетики</h1>
<div class="submitted-concourse">
  <h3>Прикладная математика и информатика</h3>
  <div class="submitted-concourse-title">Основные места в рамках КЦП</div>
  <table><thead><tr>
    <th>№</th><th>ID абитуриента*</th><th>Приоритет</th>
    <th>Сумма конкурсных баллов</th>
    <th>Наличие согласия на зачисление в МГУ</th><th>Статус заявления</th>
  </tr></thead><tbody>
    <tr><td>1</td><td> 123 456 </td><td>2</td><td>397</td><td>Да</td><td>На рассмотрении</td></tr>
  </tbody></table>
</div>
<div class="submitted-concourse">
  <h3>Фундаментальная информатика</h3>
  <div class="submitted-concourse-title">Основные места в рамках КЦП</div>
  <table><thead><tr>
    <th>№</th><th>ID абитуриента*</th><th>Приоритет</th>
    <th>Сумма баллов</th><th>Наличие согласия</th><th>Статус</th>
  </tr></thead><tbody>
    <tr><td>2</td><td>123456</td><td>1</td><td>397</td><td>Нет</td><td>На рассмотрении</td></tr>
  </tbody></table>
</div>
<div class="submitted-concourse">
  <h3>Прикладная математика и информатика</h3>
  <div class="submitted-concourse-title">Особая квота в рамках КЦП</div>
  <table><thead><tr><th>№</th><th>ID абитуриента*</th></tr></thead>
  <tbody><tr><td>1</td><td>999999</td></tr></tbody></table>
</div>
</body></html>
"""


RATING_HTML = """
<html><head><title>Конкурсные списки МГУ 2026</title></head><body>
<div class="rating-concourse">
  <h3>Прикладная математика и информатика</h3>
  <div class="rating-concourse-title">Основные места в рамках КЦП</div>
  <table><thead><tr>
    <th>№</th><th>ID конкурсного заявления</th>
    <th colspan="2">1: Наличие согласия на зачисление в МГУ 2: Приоритет зачисления</th>
    <th colspan="3">1: Основной высший приоритет 2: Высший проходной приоритет 3: Порядковый номер по высшим проходным приоритетам</th>
    <th>Сумма баллов</th><th>Статус</th>
  </tr></thead><tbody>
    <tr><td>17</td><td>123456789012</td><td>Да</td><td>2</td><td>Да</td><td>Да</td><td>8</td><td>409</td><td>Участвует в конкурсе</td></tr>
    <tr><td>18</td><td>111111111111</td><td>Нет</td><td>3</td><td>Да</td><td>Нет</td><td>—</td><td>408</td><td>Конкурсная группа исключена</td></tr>
  </tbody></table>
</div>
</body></html>
"""


LEGACY_RATING_HTML = RATING_HTML.replace(
    '<div class="rating-concourse">\n  <h3>Прикладная математика и информатика</h3>\n  <div class="rating-concourse-title">Основные места в рамках КЦП</div>',
    '<h4>ПРИКЛАДНАЯ МАТЕМАТИКА И ИНФОРМАТИКА</h4>\n<h4>Лица, поступающие по общему конкурсу</h4>',
).replace("</div>\n</body>", "</body>")


MIPT_HTML = """
<html><body><h6>ПМИ</h6><table><tbody>
<tr><td>1</td><td>1</td><td>101</td><td></td><td></td><td>300</td><td></td><td></td><td></td><td></td><td>✓</td></tr>
<tr><td>2</td><td>3</td><td>202</td><td></td><td></td><td>290</td><td></td><td></td><td></td><td></td><td></td></tr>
</tbody></table></body></html>
"""


def test_msu_submitted_returns_all_main_budget_matches_and_excludes_quota():
    parser = MsuParser("https://cpk.msu.ru/submitted/bachelor/dep_02", expected_year=2026)
    parser.results = parser.parse(SUBMITTED_HTML)

    matches = parser.lookup("123 456")
    assert len(matches) == 2
    assert {item.competition_group for item in matches} == {
        "Прикладная математика и информатика",
        "Фундаментальная информатика",
    }
    assert all(item.stage == AdmissionStage.PRELIMINARY for item in matches)
    assert parser.lookup("999999") == []


def test_msu_rating_reads_official_priority_fields():
    parser = MsuParser("https://cpk.msu.ru/rating/dep_02", expected_year=2026)
    parser.results = parser.parse(RATING_HTML)

    result = parser.lookup("123456789012")[0]
    assert result.rank == 17
    assert result.score == 409
    assert result.consent is True
    assert result.priority == 2
    assert result.main_highest_priority is True
    assert result.passing_highest_priority is True
    assert result.passing_priority_rank == 8


def test_msu_rating_supports_legacy_general_competition_heading():
    parser = MsuParser("https://cpk.msu.ru/rating/dep_02", expected_year=2026)
    parser.results = parser.parse(LEGACY_RATING_HTML)
    result = parser.lookup("123456789012")[0]
    assert result.competition_group == "ПРИКЛАДНАЯ МАТЕМАТИКА И ИНФОРМАТИКА"
    assert result.passing_highest_priority is True


def test_msu_rejects_wrong_campaign_year():
    parser = MsuParser("https://cpk.msu.ru/rating/dep_02", expected_year=2027)
    try:
        parser.parse(RATING_HTML)
    except Exception as exc:
        assert "2026" in str(exc)
    else:
        raise AssertionError("old campaign must be rejected")


def test_mipt_parser_keeps_priority_counts_without_key_errors():
    parser = MiptParser("https://pk.mipt.ru/list")
    parser.results = parser.parse(MIPT_HTML)
    result = parser.lookup("202")[0]
    assert result.rank == 2
    assert result.priority == 3
    assert result.extra["Место среди кандидатов с не меньшим приоритетом"] == 2


def test_registry_selects_provider_and_rejects_unknown_urls():
    registry = default_registry()
    assert registry.provider_for("https://cpk.msu.ru/rating/dep_01") == "msu"
    assert registry.provider_for("https://pk.mipt.ru/list") == "mipt"
    try:
        registry.provider_for("https://example.com/list")
    except UnsupportedSourceError:
        pass
    else:
        raise AssertionError("unknown host must be rejected")
