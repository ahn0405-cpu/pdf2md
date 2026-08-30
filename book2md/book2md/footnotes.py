"""각주 (§2.4).

각주는 본문 못지않게 중요하다. 실제로 판례 변경 경위(각주 264)나 유일한
사실관계(각주 266)가 각주에만 실려 있다. 그래서 여기서는 **하나도 버리지 않는
것**을 목표로 한다. 참조를 못 찾은 각주도 지우지 않고 섹션 끝에 그대로 붙이고,
정의를 못 찾은 참조는 검증에서 사람에게 알린다.

두 갈래로 각주 영역을 잡는다.
  · 좌표 파서 : 파서가 이미 zone='footnote' 로 표시해 둔 줄
  · 그 외     : 페이지 맨 아래에서 번호로 시작하는 줄 뭉치. 번호가 문서 전체에서
                단조증가한다는 성질을 이용해 목록 항목('1. 문제점')과 구분한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Page
from .patterns import Patterns

_NUM_HEAD = re.compile(r"^(\d{1,4})\s*[).\]]?\s+(\S.*)$")
_SENT_END = ("다.", "다).", "함.", "음.", "요.", ".", "」", "’", '"', ")")


@dataclass
class Footnote:
    number: int
    text: str
    page: int
    emitted: bool = False

    def markdown(self) -> str:
        return f"[^{self.number}]: {self.text}"


@dataclass
class FootnoteState:
    """문서 전체를 훑는 동안 이어지는 상태."""
    last_number: int = 0
    pending: Footnote | None = None          # 페이지를 넘어 이어질 수 있는 각주
    collected: list[Footnote] = field(default_factory=list)


class FootnoteCollector:
    def __init__(self, cfg: dict, pat: Patterns):
        self.pat = pat
        fn = cfg["preserve"]["footnote"]
        self.lo = int(fn.get("number_min", 1))
        self.hi = int(fn.get("number_max", 4000))
        self.tail_lines = int(fn.get("markdown_tail_lines", 12))
        self.inline_from_numbers = bool(fn.get("inline_ref_from_numbers", True))
        self.state = FootnoteState()

    # ── 페이지 처리 ──────────────────────────────────────────────
    def process(self, page: Page) -> list[Footnote]:
        """페이지에서 각주를 떼어내고, 그 페이지에서 새로 확정된 각주를 돌려준다.

        page.lines 는 본문만 남는다(각주 줄은 빠진다).
        """
        zone = [l for l in page.lines if l.zone == "footnote"]
        if not zone and page.kind != "layout":
            zone = self._guess_zone(page)
        if not zone:
            body = [l for l in page.lines if l.zone in ("body", "header")]
            self._inline_refs(page, body, [])
            page.lines = [l for l in body if l.zone != "header"]
            return []

        marked = set(id(l) for l in zone)
        body = [l for l in page.lines if id(l) not in marked and l.zone != "header"]

        found = self._parse_zone(zone, page.number)
        self._inline_refs(page, body, found)
        page.lines = body
        return found

    def finish(self) -> list[Footnote]:
        """마지막 페이지까지 끝난 뒤 남은 각주를 닫는다."""
        if self.state.pending:
            self.state.pending = None
        return []

    # ── 각주 영역 → 각주 목록 ────────────────────────────────────
    def _parse_zone(self, zone, page_no) -> list[Footnote]:
        found: list[Footnote] = []
        current: Footnote | None = None
        for line in zone:
            text = line.stripped
            if not text:
                continue
            m = _NUM_HEAD.match(text)
            n = int(m.group(1)) if m else None
            starts_new = (
                m is not None
                and self.lo <= n <= self.hi
                and n > self.state.last_number
            )
            if starts_new:
                if current:
                    found.append(current)
                current = Footnote(number=n, text=m.group(2).strip(), page=page_no)
                self.state.last_number = n
                self.state.pending = None
                continue
            # 번호 없이 시작하는 줄 = 이어지는 각주 본문
            target = current or self.state.pending
            if target is None:
                # 각주 영역 첫 줄인데 번호가 없다. 앞 페이지에서 끊긴 각주로 본다.
                if self.state.collected:
                    target = self.state.collected[-1]
                else:
                    continue
            target.text = _join(target.text, text)
        if current:
            found.append(current)
        # 페이지 마지막 각주가 문장으로 끝나지 않으면 다음 페이지로 이어질 수 있다
        if found and not found[-1].text.rstrip().endswith(_SENT_END):
            self.state.pending = found[-1]
        self.state.collected.extend(found)
        return found

    # ── 좌표가 없을 때 각주 영역 추정 ─────────────────────────────
    def _guess_zone(self, page: Page):
        lines = [l for l in page.lines if l.stripped]
        if not lines:
            return []
        tail = lines[-self.tail_lines:]
        start = None
        for k, line in enumerate(tail):
            m = _NUM_HEAD.match(line.stripped)
            if not m:
                continue
            n = int(m.group(1))
            if not (self.lo <= n <= self.hi and n > self.state.last_number):
                continue
            # 뒤로 이어지는 줄들이 각주다운지 본다: 번호가 오르거나 이어지는 문장
            if self._tail_is_footnotes(tail[k:]):
                start = k
                break
        if start is None:
            return []
        zone = tail[start:]
        for line in zone:
            line.zone = "footnote"
        return zone

    def _tail_is_footnotes(self, block) -> bool:
        numbers = []
        for line in block:
            m = _NUM_HEAD.match(line.stripped)
            if m:
                numbers.append(int(m.group(1)))
        if not numbers:
            return False
        if numbers != sorted(numbers):
            return False
        # 헤딩('1. 총설')처럼 짧은 줄만 있는 뭉치는 각주가 아니다
        return any(len(l.stripped) > 25 for l in block)

    # ── 본문 안의 각주 참조 (§2.4) ────────────────────────────────
    def _inline_refs(self, page: Page, body, found) -> None:
        """이미 [^n] 이면 그대로 두고, 좌표가 없어 놓친 것만 번호를 근거로 살린다.

        아무 숫자나 참조로 바꾸지 않는다. 그 페이지(또는 바로 앞)에서 실제로
        정의를 본 번호만 바꾼다. 사건번호·연도·조문 번호는 건드리지 않는다.
        """
        if page.kind == "layout" or not self.inline_from_numbers:
            return
        numbers = sorted({f.number for f in found}, reverse=True)
        if not numbers:
            return
        for line in body:
            text = line.text
            if not text:
                continue
            guard = _protected_spans(self.pat, text)
            for n in numbers:
                pat = re.compile(rf"(?<=[가-힣\)\]』」.])({n})(?![\d])")
                out, cursor = [], 0
                for m in pat.finditer(text):
                    if any(a <= m.start() < b for a, b in guard):
                        continue
                    out.append(text[cursor:m.start()])
                    out.append(f"[^{n}]")
                    cursor = m.end()
                if out:
                    out.append(text[cursor:])
                    text = "".join(out)
                    guard = _protected_spans(self.pat, text)
            line.text = text


def _protected_spans(pat: Patterns, text: str) -> list[tuple[int, int]]:
    """건드리면 안 되는 구간: 사건번호, 날짜, 조문, 이미 붙은 [^n]."""
    spans = []
    for rx in (pat.case, pat.date, pat.footnote_ref):
        spans += [(m.start(), m.end()) for m in rx.finditer(text)]
    spans += [(m.start(), m.end()) for m in re.finditer(r"제\d+[편장절관조항호목]", text)]
    return spans


def _join(head: str, tail: str) -> str:
    """줄바꿈으로 끊긴 각주를 잇는다. 한글끼리는 붙이지 않고 공백을 둔다."""
    head = head.rstrip()
    tail = tail.lstrip()
    if not head:
        return tail
    if head.endswith("-"):
        return head[:-1] + tail
    return head + " " + tail
