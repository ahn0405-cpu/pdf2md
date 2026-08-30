"""단계 사이를 오가는 자료 구조.

파서가 무엇이든 파이프라인은 Page/Line 만 본다. 좌표를 주는 파서(pymupdf)는
size·bold·y 를 채우고, 마크다운만 주는 파서(marker 등)는 비워 둔다. 뒤 단계는
값이 있으면 쓰고 없으면 글 모양만으로 판단한다.

페이지 단위로 흘려보내고 곧바로 jsonl 로 떨어뜨린다. 200MB·수천 쪽짜리도
통째로 메모리에 올리지 않기 위해서다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Iterable, Iterator


@dataclass
class Line:
    """한 줄. 좌표가 없는 파서는 size=0, bold=False 로 둔다."""
    text: str
    size: float = 0.0
    bold: bool = False
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    column: int = 0
    zone: str = "body"          # body | footnote | header | footer | sidenote
    # 이 줄 안에서 각주 참조로 읽힌 위첨자 숫자들 (좌표 파서만 채운다)
    sup_numbers: list[int] = field(default_factory=list)

    @property
    def stripped(self) -> str:
        return self.text.strip()


@dataclass
class Page:
    number: int                 # 1-based, 원본 PDF 쪽번호
    lines: list[Line] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    kind: str = "markdown"      # layout(좌표 있음) | markdown(텍스트만)
    body_size: float = 0.0      # 이 문서의 본문 글자 크기(좌표 파서)
    #: 우측 여백에서 떼어낸 강의교안 옆번호 (§4.3). [{"text": "sE-8", "y": 89.9}]
    #: y 를 함께 들고 있어야 어느 헤딩의 옆번호인지 짝지을 수 있다.
    sidenotes: list[dict] = field(default_factory=list)

    def text(self, zone: str | None = None) -> str:
        return "\n".join(l.text for l in self.lines if zone is None or l.zone == zone)


def dump_pages(pages: Iterable[Page], path) -> int:
    """페이지를 jsonl 로 흘려 쓴다. 쓴 쪽수를 돌려준다."""
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for page in pages:
            fh.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
            n += 1
    return n


def load_pages(path) -> Iterator[Page]:
    """jsonl 을 페이지 단위로 되읽는다. 한 번에 한 쪽만 메모리에 올린다."""
    with open(path, encoding="utf-8") as fh:
        for row in fh:
            row = row.strip()
            if not row:
                continue
            d = json.loads(row)
            lines = [Line(**l) for l in d.pop("lines", [])]
            yield Page(lines=lines, **d)
