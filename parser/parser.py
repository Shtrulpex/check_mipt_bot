"""Admissions parser registry and backwards-compatible public facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests


class AdmissionStage(str, Enum):
    PRELIMINARY = "preliminary"
    COMPETITION = "competition"


class ParserError(RuntimeError):
    """A page cannot be loaded or interpreted safely."""


class UnsupportedSourceError(ParserError):
    """No registered provider supports the supplied URL."""


@dataclass(frozen=True)
class ApplicationResult:
    university: str
    faculty: str
    competition_group: str
    applicant_id: str
    stage: AdmissionStage
    score: Optional[int] = None
    rank: Optional[int] = None
    priority: Optional[int] = None
    consent: Optional[bool] = None
    main_highest_priority: Optional[bool] = None
    passing_highest_priority: Optional[bool] = None
    passing_priority_rank: Optional[int] = None
    status: Optional[str] = None
    extra: dict[str, int | str] = field(default_factory=dict)


class AdmissionsParser:
    """Base class for a cached, refreshable admissions-list parser."""

    provider = "unknown"

    def __init__(self, url: str, *, timeout: int = 20, expected_year: int | None = None):
        self.url = url
        self.timeout = timeout
        self.expected_year = expected_year
        self.results: tuple[ApplicationResult, ...] = ()
        self.title = url
        self.campaign_year: int | None = None
        self.last_updated_at: datetime | None = None
        self.last_error: str | None = None

    @classmethod
    def supports(cls, url: str) -> bool:
        raise NotImplementedError

    def parse(self, html: str) -> tuple[ApplicationResult, ...]:
        raise NotImplementedError

    def refresh(self) -> bool:
        """Refresh the snapshot, retaining the last good one on failure."""
        try:
            response = requests.get(
                self.url,
                timeout=self.timeout,
                headers={"User-Agent": "check-admissions-bot/1.0"},
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            parsed = self.parse(response.text)
            self.results = parsed
            self.last_updated_at = datetime.now(ZoneInfo("Europe/Moscow"))
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def lookup(self, applicant_id: str) -> list[ApplicationResult]:
        normalized = normalize_applicant_id(applicant_id)
        return [result for result in self.results if result.applicant_id == normalized]

    def __call__(self, applicant_id: str | int) -> str:
        return format_results(str(applicant_id), self.lookup(str(applicant_id)), self)


@dataclass(frozen=True)
class _AdapterRegistration:
    provider: str
    parser_class: type[AdmissionsParser]


class ParserRegistry:
    def __init__(self) -> None:
        self._adapters: list[_AdapterRegistration] = []

    def register(self, provider: str, parser_class: type[AdmissionsParser]) -> None:
        self._adapters.append(_AdapterRegistration(provider, parser_class))

    def provider_for(self, url: str) -> str:
        normalized = normalize_url(url)
        for adapter in self._adapters:
            if adapter.parser_class.supports(normalized):
                return adapter.provider
        raise UnsupportedSourceError("Этот URL пока не поддерживается ботом")

    def create(
        self,
        url: str,
        *,
        load: bool = True,
        expected_year: int | None = None,
    ) -> AdmissionsParser:
        normalized = normalize_url(url)
        for adapter in self._adapters:
            if adapter.parser_class.supports(normalized):
                parser = adapter.parser_class(normalized, expected_year=expected_year)
                if load and not parser.refresh():
                    raise ParserError(parser.last_error or "Не удалось загрузить страницу")
                return parser
        raise UnsupportedSourceError("Этот URL пока не поддерживается ботом")


def normalize_applicant_id(value: str) -> str:
    return "".join(str(value).replace("\xa0", " ").split())


def normalize_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UnsupportedSourceError("Нужна полная ссылка, начинающаяся с https://")
    return value.rstrip("/")


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "нет данных"
    return "да" if value else "нет"


def format_results(
    applicant_id: str,
    results: list[ApplicationResult],
    parser: AdmissionsParser,
) -> str:
    if not results:
        suffix = f" Последняя ошибка обновления: {parser.last_error}." if parser.last_error else ""
        return f"ID {applicant_id} не найден в выбранном списке.{suffix}"

    blocks: list[str] = []
    for result in results:
        lines = [
            f"{result.university} — {result.faculty}",
            result.competition_group,
            f"ID: {result.applicant_id}",
        ]
        if result.score is not None:
            lines.append(f"Баллы: {result.score}")
        if result.rank is not None:
            lines.append(f"Место в списке: {result.rank}")
        if result.priority is not None:
            lines.append(f"Приоритет заявления: {result.priority}")
        if result.consent is not None:
            lines.append(f"Согласие в вузе: {_yes_no(result.consent)}")

        if result.stage == AdmissionStage.COMPETITION and result.university == "МГУ":
            lines.append(
                "Основной высший приоритет: "
                + _yes_no(result.main_highest_priority)
            )
            lines.append(
                "Высший проходной приоритет: "
                + _yes_no(result.passing_highest_priority)
            )
            lines.append(
                "Место по высшим проходным приоритетам: "
                + (str(result.passing_priority_rank) if result.passing_priority_rank is not None else "—")
            )
            if result.main_highest_priority is True:
                lines.append("Эта группа соответствует основному высшему приоритету.")
            if result.passing_highest_priority is True:
                lines.append("Эта группа соответствует высшему проходному приоритету.")
        else:
            lines.append("Предварительный список: официальные проходные приоритеты ещё не опубликованы.")

        if result.status:
            lines.append(f"Статус: {result.status}")
        for label, value in result.extra.items():
            lines.append(f"{label}: {value}")
        blocks.append("\n".join(lines))

    updated = parser.last_updated_at
    footer = f"\nОбновлено: {updated:%d.%m.%Y %H:%M %Z}" if updated else ""
    if parser.last_error:
        footer += f"\nПоказан последний успешный снимок; обновление не удалось: {parser.last_error}"
    return ("\n\n".join(blocks) + footer).strip()


def default_registry() -> ParserRegistry:
    from parser.mipt import MiptParser
    from parser.msu import MsuParser

    registry = ParserRegistry()
    registry.register(MsuParser.provider, MsuParser)
    registry.register(MiptParser.provider, MiptParser)
    return registry


# Compatibility for external imports; new code should use ParserRegistry.
class Parser:
    def __new__(cls, url: str) -> AdmissionsParser:
        return default_registry().create(url)
