from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from parser.parser import (
    AdmissionStage,
    AdmissionsParser,
    ApplicationResult,
    ParserError,
    normalize_applicant_id,
)


_SPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"\b20\d{2}\b")


def _text(node: Tag | None) -> str:
    return _SPACE_RE.sub(" ", node.get_text(" ", strip=True)).strip() if node else ""


def _normalized(value: str) -> str:
    return _SPACE_RE.sub(" ", value.replace("ё", "е").lower()).strip()


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", value.replace(" ", ""))
    return int(match.group()) if match else None


def _optional_bool(value: str | None) -> bool | None:
    if value is None or not value.strip() or value.strip() in {"—", "-"}:
        return None
    normalized = _normalized(value)
    if normalized in {"да", "есть", "+", "✓"}:
        return True
    if normalized in {"нет", "-"}:
        return False
    return None


class MsuParser(AdmissionsParser):
    provider = "msu"

    @classmethod
    def supports(cls, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        return host == "cpk.msu.ru" and bool(
            re.fullmatch(r"/(?:submitted/bachelor|rating)/dep_\d+", path)
        )

    @property
    def stage(self) -> AdmissionStage:
        return (
            AdmissionStage.PRELIMINARY
            if "/submitted/" in urlparse(self.url).path
            else AdmissionStage.COMPETITION
        )

    def parse(self, html: str) -> tuple[ApplicationResult, ...]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = _text(soup)
        self.campaign_year = self._detect_campaign_year(soup, page_text)
        expected = self.expected_year or datetime.now(ZoneInfo("Europe/Moscow")).year
        if self.campaign_year is None:
            raise ParserError("Не удалось определить год приёмной кампании на странице МГУ")
        if self.campaign_year is not None and self.campaign_year != expected:
            raise ParserError(
                f"Страница относится к кампании {self.campaign_year}, ожидалась кампания {expected}"
            )

        faculty = self._faculty_name(soup)
        self.title = f"МГУ — {faculty}"
        results: list[ApplicationResult] = []
        candidate_tables = 0

        for table in soup.select("table"):
            context, group_title = self._table_context(table)
            if not self._is_main_budget(context):
                continue
            schema = self._schema_for_table(table)
            if "applicant_id" not in schema:
                continue
            # The main-KCP section contains a separate BVI table without scores.
            # The general-competition table always contains the competition sum.
            if self.stage == AdmissionStage.PRELIMINARY and "score" not in schema:
                continue
            candidate_tables += 1

            for tr in table.select("tbody tr") or table.select("tr"):
                cells = [_text(td) for td in tr.find_all("td", recursive=False)]
                if not cells:
                    continue
                values = {key: cells[index] for index, key in enumerate(schema) if key and index < len(cells)}
                applicant_id = normalize_applicant_id(values.get("applicant_id", ""))
                if not applicant_id:
                    continue
                results.append(
                    ApplicationResult(
                        university="МГУ",
                        faculty=faculty,
                        competition_group=group_title,
                        applicant_id=applicant_id,
                        stage=self.stage,
                        score=_optional_int(values.get("score")),
                        rank=_optional_int(values.get("rank")),
                        priority=_optional_int(values.get("priority")),
                        consent=_optional_bool(values.get("consent")),
                        main_highest_priority=_optional_bool(values.get("main_highest_priority")),
                        passing_highest_priority=_optional_bool(values.get("passing_highest_priority")),
                        passing_priority_rank=_optional_int(values.get("passing_priority_rank")),
                        status=values.get("status") or None,
                    )
                )

        if candidate_tables == 0:
            raise ParserError("На странице МГУ не найдены основные бюджетные места в рамках КЦП")
        if not results:
            raise ParserError("Основные конкурсные таблицы МГУ пусты или их формат изменился")
        return tuple(results)

    def _detect_campaign_year(self, soup: BeautifulSoup, page_text: str) -> int | None:
        preferred = " ".join(
            _text(node) for node in soup.select("title, h1, h2, .page-title, .header-title")
        )
        matches = _YEAR_RE.findall(preferred)
        if not matches:
            matches = _YEAR_RE.findall(page_text[:5000])
        return int(matches[0]) if matches else None

    def _faculty_name(self, soup: BeautifulSoup) -> str:
        dep_match = re.search(r"dep_(\d+)", self.url)
        known = {"01": "Механико-математический факультет", "02": "ВМК"}
        if dep_match and dep_match.group(1) in known:
            return known[dep_match.group(1)]
        headings = [_text(node) for node in soup.select("h1, h2") if _text(node)]
        return headings[-1] if headings else f"Факультет dep_{dep_match.group(1) if dep_match else '?'}"

    def _table_context(self, table: Tag) -> tuple[str, str]:
        submitted_container = table.find_parent("div", class_="submitted-concourse")
        if submitted_container is not None:
            category = _text(submitted_container.select_one(".submitted-concourse-title"))
            program = _text(submitted_container.select_one(".submitted-passport-main"))
            if not program:
                program = _text(submitted_container.find(["h2", "h3"]))
            program = re.sub(
                r"^Образовательная программа:\s*", "", program, flags=re.IGNORECASE
            ).strip()
            return category or _text(submitted_container)[:500], program or "Конкурсная группа МГУ"

        nearest_heading = table.find_previous(["h2", "h3", "h4", "h5", "h6"])
        if nearest_heading is not None and self._is_category_heading(_text(nearest_heading)):
            category = _text(nearest_heading)
            group_title = "Конкурсная группа МГУ"
            for heading in nearest_heading.find_all_previous(
                ["h2", "h3", "h4", "h5", "h6"], limit=30
            ):
                candidate = _text(heading)
                if candidate and not self._is_category_heading(candidate):
                    group_title = candidate
                    break
            return category, group_title

        container = table.find_parent(
            lambda tag: isinstance(tag, Tag)
            and any("concourse" in cls or "competition" in cls for cls in tag.get("class", []))
        )
        if container is None:
            container = table.find_parent("section") or table.parent

        title_nodes = container.select(
            "h2, h3, h4, h5, h6, [class*='title'], [class*='passport-main']"
        ) if isinstance(container, Tag) else []
        titles: list[str] = []
        for node in title_nodes:
            value = _text(node)
            if value and value not in titles:
                titles.append(value)

        # Some versions put the competition title immediately before the table.
        previous = table.find_all_previous(["h2", "h3", "h4", "h5", "h6"], limit=3)
        for node in reversed(previous):
            value = _text(node)
            if value and value not in titles:
                titles.insert(0, value)

        context = " — ".join(titles) or _text(container)[:1000]
        meaningful = [
            value for value in titles
            if "основн" not in _normalized(value) and "кцп" not in _normalized(value)
        ]
        group_title = meaningful[-1] if meaningful else "Основные места в рамках КЦП"
        return context, group_title

    @staticmethod
    def _is_main_budget(context: str) -> bool:
        value = _normalized(context)
        excluded = ("платн", "договор", "целевая", "отдельная квота", "особая квота", "бви")
        explicitly_main = (
            ("основн" in value and ("кцп" in value or "общий конкурс" in value))
            or "по общему конкурсу" in value
        )
        return explicitly_main and not any(token in value for token in excluded)

    @staticmethod
    def _is_category_heading(value: str) -> bool:
        text = _normalized(value)
        markers = (
            "квота",
            "без вступительных испытаний",
            "без вступительных экзаменов",
            "по общему конкурсу",
            "основные места",
            "договорной основе",
            "платные места",
            "иностранные граждане",
        )
        return any(marker in text for marker in markers)

    def _schema_for_table(self, table: Tag) -> list[str | None]:
        rows = table.select("thead tr") or [tr for tr in table.select("tr") if tr.find("th")]
        data_width = max(
            (len(tr.find_all("td", recursive=False)) for tr in table.select("tbody tr")),
            default=0,
        )
        candidates = [self._expand_header_row(row) for row in rows]
        candidates = [candidate for candidate in candidates if candidate]
        if not candidates:
            return []
        return min(candidates, key=lambda candidate: abs(len(candidate) - data_width))

    def _expand_header_row(self, row: Tag) -> list[str | None]:
        schema: list[str | None] = []
        for th in row.find_all("th", recursive=False):
            text = _normalized(_text(th))
            colspan = int(th.get("colspan", 1) or 1)
            if "наличие согласия" in text and "приоритет" in text and colspan >= 2:
                keys: list[str | None] = ["consent", "priority"]
            elif "основной высший приоритет" in text and "высший проходной приоритет" in text:
                keys = ["main_highest_priority", "passing_highest_priority", "passing_priority_rank"]
            elif "результат" in text and "вступитель" in text:
                keys = [None] * colspan
            else:
                key = self._header_key(text)
                keys = [key] + [None] * (colspan - 1)
            schema.extend((keys + [None] * colspan)[:colspan])
        return schema

    @staticmethod
    def _header_key(text: str) -> str | None:
        if text in {"№", "номер", "п/п"}:
            return "rank"
        if ("id" in text and ("абитуриент" in text or "заявлен" in text)) or "номер заявления" in text:
            return "applicant_id"
        if "основной высший приоритет" in text:
            return "main_highest_priority"
        if "высший проходной приоритет" in text and "порядков" not in text:
            return "passing_highest_priority"
        if "порядков" in text and "проходн" in text:
            return "passing_priority_rank"
        if "приоритет" in text:
            return "priority"
        if "соглас" in text:
            return "consent"
        if "сумма конкурсных баллов" in text or text == "сумма баллов":
            return "score"
        if "статус" in text:
            return "status"
        return None
