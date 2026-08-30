"""마크다운 문자열만 돌려주는 파서들의 공통 뼈대.

좌표가 없으므로 각주·위첨자는 footnotes.py 의 글 모양 규칙으로 가려낸다.
쪽 경계는 파서가 주는 페이지 구분을 그대로 쓴다.
"""
from __future__ import annotations

from typing import Iterator

from ..model import Line, Page
from .base import Parser


def page_from_markdown(number: int, text: str) -> Page:
    lines = [Line(text=t.rstrip()) for t in text.splitlines()]
    return Page(number=number, lines=lines, kind="markdown")


class MarkdownParser(Parser):
    """서브클래스는 _pages() 만 구현하면 된다."""

    def _pages(self, pdf_path, pages, profile) -> Iterator[tuple[int, str]]:
        raise NotImplementedError

    def parse(self, pdf_path, pages, profile) -> Iterator[Page]:
        self.require()
        for number, text in self._pages(pdf_path, pages, profile):
            yield page_from_markdown(number, text)

    def page_count(self, pdf_path: str) -> int:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
