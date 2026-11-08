"""텍스트 파일 파서.

PDF 가 아니라 .txt/.md 를 읽는다. 폼피드(\\f) 나 '<!-- page N -->' 로 쪽을 나눈다.
파서를 갈아 끼워도 §4·§5 가 그대로 도는지 확인하는 회귀 테스트용이고,
파서 출력을 손으로 고쳐 다시 돌릴 때도 쓴다.
"""
from __future__ import annotations

import re

from .markdown_base import MarkdownParser

_MARK = re.compile(r"^<!--\s*page\s+(\d+)\s*-->\s*$", re.M)


class TextFileParser(MarkdownParser):
    name = "textfile"
    install_hint = "(내장)"

    def available(self):
        return True, ""

    def page_count(self, pdf_path: str) -> int:
        return len(list(self._raw(pdf_path)))

    def _raw(self, path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if _MARK.search(text):
            parts = _MARK.split(text)
            it = iter(parts[1:])
            for number, body in zip(it, it):
                yield int(number), body
            return
        for k, body in enumerate(text.split("\f")):
            yield k + 1, body

    def _pages(self, pdf_path, pages, profile):
        for number, body in self._raw(pdf_path):
            if pages is not None and (number - 1) not in pages:
                continue
            yield number, body
