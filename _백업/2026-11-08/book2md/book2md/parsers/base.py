"""파서 어댑터 인터페이스.

파서는 갈아 끼울 수 있어야 한다(§3.2). 어댑터는 PDF 를 받아 Page 를 하나씩
흘려보내는 일만 한다. 정규화(§4)·검증(§5)은 어댑터가 무엇이든 그대로 돈다.

새 파서를 붙이려면:
  1) 이 파일의 Parser 를 상속해 available() 과 parse() 를 채운다
  2) parsers/__init__.py 의 REGISTRY 에 등록한다
그게 전부다. 뒤 단계는 손대지 않는다.
"""
from __future__ import annotations

from typing import Iterator

from ..model import Page


class ParserUnavailable(RuntimeError):
    """파서 패키지가 설치돼 있지 않다."""


class Parser:
    name = "base"
    #: 좌표·글자 크기를 주는가. 준다면 각주·위첨자를 훨씬 정확히 가려낼 수 있다.
    layout_aware = False
    #: 설치 안내 (available() 이 False 일 때 사람에게 보여준다)
    install_hint = ""

    def available(self) -> tuple[bool, str]:
        """(쓸 수 있나, 사유)."""
        raise NotImplementedError

    def require(self) -> None:
        ok, why = self.available()
        if not ok:
            raise ParserUnavailable(
                f"파서 '{self.name}' 를 쓸 수 없다: {why}\n  설치: {self.install_hint}"
            )

    def parse(self, pdf_path: str, pages: range | None, profile: dict) -> Iterator[Page]:
        """pages 는 0-based 인덱스 범위. None 이면 전부."""
        raise NotImplementedError

    def page_count(self, pdf_path: str) -> int:
        raise NotImplementedError
