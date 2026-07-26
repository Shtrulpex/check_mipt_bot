from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from parser.parser import (
    AdmissionStage,
    AdmissionsParser,
    ApplicationResult,
    ParserError,
    normalize_applicant_id,
)


class MiptParser(AdmissionsParser):
    provider = "mipt"

    @classmethod
    def supports(cls, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "mipt.ru" or host.endswith(".mipt.ru")

    def parse(self, html: str) -> tuple[ApplicationResult, ...]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.select_one("tbody")
        if table is None:
            raise ParserError("На странице МФТИ не найдена таблица поступающих")

        headings = [node.get_text(" ", strip=True) for node in soup.select("h6")]
        title = " — ".join(filter(None, headings)) or "Конкурсный список"
        self.title = title
        priority_count: dict[int, int] = {}
        accepted_priority_count: dict[int, int] = {}
        accepted_rank = 0
        results: list[ApplicationResult] = []

        for row_number, tr in enumerate(table.select("tr"), start=1):
            cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(cells) < 11:
                continue
            try:
                priority = int(cells[1])
                applicant_id = normalize_applicant_id(cells[2])
                score = int(cells[5])
            except (ValueError, IndexError):
                continue

            consent = cells[10] in {"✓", "Да", "да", "+"}
            higher_priority = 1 + sum(
                count for key, count in priority_count.items() if key <= priority
            )
            higher_priority_accepted = 1 + sum(
                count for key, count in accepted_priority_count.items() if key <= priority
            )
            results.append(
                ApplicationResult(
                    university="МФТИ",
                    faculty="",
                    competition_group=title,
                    applicant_id=applicant_id,
                    stage=AdmissionStage.COMPETITION,
                    score=score,
                    rank=row_number,
                    priority=priority,
                    consent=consent,
                    extra={
                        "Место среди подавших согласие": accepted_rank + 1,
                        "Место среди кандидатов с не меньшим приоритетом": higher_priority,
                        "То же, с согласием": higher_priority_accepted,
                    },
                )
            )
            priority_count[priority] = priority_count.get(priority, 0) + 1
            if consent:
                accepted_rank += 1
                accepted_priority_count[priority] = accepted_priority_count.get(priority, 0) + 1

        if not results:
            raise ParserError("Таблица МФТИ пуста или её формат изменился")
        return tuple(results)
