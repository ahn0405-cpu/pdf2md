"""구조화 (§6) + 교재 범례 요소 추출 (§1.5, §4.3~4.5, §4.7).

원문의 번호 체계를 그대로 두고 헤딩만 얹는다. 번호를 다시 매기거나 문장을
손보지 않는다(§4.8). 두문자·옆번호·기출연도·배점은 백틱으로 감싸 뒤 단계에서
정규식 한 줄로 뽑을 수 있게 한다.

기본서에서 'N.' 이 절 제목인지 굵은 소항목인지는 위치로 가른다. 로마숫자
제목(Ⅳ.) 아래면 소항목, 그 앞이면 절이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .footnotes import Footnote
from .model import Page
from .patterns import Patterns

_LIST_HEAD = re.compile(
    r"^(?:[-•‣▪·]|\(\s*\d+\s*\)|\d+\s*\)|[가-하]\s*[.)]|[①-⑳]|[ⅰ-ⅹ]\s*\)|\(\s*[ⅰ-ⅹ]\s*\))\s*"
)
_SENT_END = re.compile(r"(?:[.?!]|다\.|음\.|함\.|[」』’”\)])\s*$")
_CJK = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ぀-ヿ一-鿿]")
_NUM_ITEM = re.compile(r"^(\d{1,2})\s*\.\s*")


@dataclass
class Block:
    kind: str                 # heading | para | bold | bonus | prompt | footnotes
    text: str
    level: int = 0
    page: int = 0
    cases: list = field(default_factory=list)      # [{id,label,standard}]
    mnemonics: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)       # exam_years / sidenote / outline …


class Structurer:
    def __init__(self, cfg: dict, prof: dict, pat: Patterns):
        self.cfg, self.prof, self.pat = cfg, prof, pat
        self.join = cfg.get("paragraph", {}).get("join", "space")
        self.flush_level = int(prof.get("footnote_flush_level", 4))
        self.blocks: list[Block] = []
        self._para: list[str] = []
        self._para_page = 0
        self._pending: list[Footnote] = []
        self._in_roman = False
        self._last_item = 0            # 직전 'N.' 소항목 번호 (☑ 박스 끝 판정용)
        self._bonus: list[str] | None = None
        self._bonus_title = ""
        self._sidenotes: list[dict] = []
        self._in_prompt = False
        self._page = 0

        legend = cfg["legend"]
        self._exam_rx = re.compile(legend["exam_year"]["pattern"])
        self._century = int(legend["exam_year"]["century_split"])
        self._bonus_marker = legend["bonus"]["marker"]
        self._bonus_misread = set(legend["bonus"].get("misread", []))
        self._bonus_ascii = set(legend["bonus"].get("misread_ascii", []))
        self._bonus_max = int(legend["bonus"].get("max_lines", 24))
        self._label_rx = re.compile(legend["case_label"]["pattern"])
        self._outline = legend["outline"]
        self._side_rx = re.compile(legend["sidenote"]["pattern"])
        self._side_tol = float(legend["sidenote"].get("match_tolerance", 12))

        self._heads = [(h["level"], re.compile(h["pattern"]))
                       for h in prof.get("headings", [])]
        self._sec_rx = re.compile(prof["section_item"]) if prof.get("section_item") else None
        self._sec_max = int(prof.get("section_max_len", 40))
        self._problem_rx = re.compile(prof["problem"]) if prof.get("problem") else None
        self._ans_heads = [(h["level"], re.compile(h["pattern"]))
                           for h in prof.get("answer_headings", [])]
        self._score_rx = re.compile(prof["score"]) if prof.get("score") else None
        self._score_max = float(prof.get("score_max", 50))
        self._last_problem: Block | None = None
        self._prompt = tuple(prof.get("prompt_markers", []))
        self._answer = tuple(prof.get("answer_markers", []))

    # ── 입력 ────────────────────────────────────────────────────
    def feed(self, page: Page, footnotes: list[Footnote]) -> None:
        self._page = page.number
        self._pending.extend(footnotes)
        # 옆번호는 그 쪽 안에서만 짝짓는다. 남으면 버리지 않고 다음 쪽으로
        # 넘기지도 않는다 — 엉뚱한 헤딩에 붙는 쪽이 못 붙는 쪽보다 나쁘다.
        self._sidenotes = [dict(s) if isinstance(s, dict) else {"text": s, "y": None}
                           for s in (page.sidenotes or [])]
        for line in page.lines:
            text = line.stripped
            if not text:
                self._flush_para()
                continue
            if self._bonus is not None and self._bonus_continues(text):
                self._bonus.append(text)
                continue
            if self._bonus is not None:
                self._close_bonus(page.number)
            marker = self._bonus_head(text)
            if marker:
                self._flush_para()
                self._bonus, self._bonus_title = [], marker
                continue
            if self.prof["name"] == "casebook":
                self._feed_casebook(text, line, page.number)
            else:
                self._feed_textbook(text, line, page.number)

    def finish(self) -> list[Block]:
        if self._bonus is not None:
            self._close_bonus(self._para_page)
        self._flush_para()
        self._flush_footnotes(final=True)
        return self.blocks

    # ── 기본서 (§6.1) ────────────────────────────────────────────
    def _feed_textbook(self, text: str, line, page_no: int) -> None:
        for level, rx in self._heads:
            if rx.match(text):
                self._heading(level, text, page_no, y=getattr(line, "y0", None))
                self._in_roman = (level == 4)
                self._last_item = 0
                return
        items = self._outline_items(text)
        if items:
            self._flush_para()
            self.blocks.append(self._mk("para", text, page=page_no,
                                        meta={"outline": items}))
            return
        m = self._sec_rx.match(text) if self._sec_rx else None
        if m:
            short = len(text) <= self._sec_max and not _SENT_END.search(text)
            if self._in_roman:
                if not short:
                    # 'N. 검토 …' 처럼 한 줄에 본문까지 이어진 경우다.
                    # 굵게 감싸면 문단 전체가 제목이 되어 버리므로 본문으로 둔다.
                    self._paragraph(text, page_no)
                    return
                self._flush_para()
                self._last_item = int(m.group(1))
                self.blocks.append(self._mk("bold", f"**{_inline(self.pat, text)}**",
                                            page=page_no))
                return
            if short:
                self._heading(3, text, page_no, y=getattr(line, "y0", None))
                return
        self._paragraph(text, page_no)

    # ── 사례집 (§6.2, §4.7) ──────────────────────────────────────
    def _feed_casebook(self, text: str, line, page_no: int) -> None:
        if self._problem_rx:
            m = self._problem_rx.match(text)
            if m and m.group(3).strip():
                self._in_prompt = False
                title = m.group(3).strip()
                score, title = _split_score(self._score_rx, title, self._score_max)
                self._heading(2, f"{m.group(1)}-{m.group(2)}. {title}",
                              page_no, score=score)
                self._last_problem = self.blocks[-1]
                return
        bare = text.strip("【】[]()（） ")
        if bare.startswith(self._prompt) or bare.startswith(self._answer):
            is_prompt = bare.startswith(self._prompt)
            label = "문제" if is_prompt else "답안"
            rest = bare[len(label):].strip()
            score, _ = _split_score(self._score_rx, rest, self._score_max,
                                    allow_bare=True)
            self._flush_para()
            self._in_prompt = is_prompt
            # 총 배점은 §6.2 대로 문제 헤딩 옆에 붙인다. 뒤 처리가 답안 목차를
            # 설계할 때 문제 단위 배점을 먼저 보기 때문이다.
            if score and self._last_problem is not None:
                self._last_problem.text += f" `{score}점`"
                score = None
            suffix = f" `{score}`" if score else ""
            self.blocks.append(self._mk("bold", f"**{label}**{suffix}", page=page_no))
            return
        for level, rx in self._ans_heads:
            if rx.match(text) and len(text) <= 60:
                self._in_prompt = False
                score, title = _split_score(self._score_rx, text, self._score_max)
                self._heading(level, title, page_no, score=score)
                return
        self._paragraph(text, page_no)

    # ── 공통 ────────────────────────────────────────────────────
    def _heading(self, level: int, text: str, page_no: int,
                 score: str | None = None, y: float | None = None) -> None:
        self._flush_para()
        if level <= self.flush_level:
            self._flush_footnotes()
        title = text.strip()
        meta: dict = {}

        # ⑨ 기출연도 (§4.5)
        years, title = _take_exam_years(self._exam_rx, title, self._century)
        if years:
            meta["exam_years"] = years
        # ⑩ 옆번호 (§4.3) — 같은 쪽에서 세로 위치가 가장 가까운 것을 붙인다.
        # 첫 헤딩에 무조건 붙이면 편·장 제목이 절의 옆번호를 가로챈다.
        side = self._take_sidenote(y)
        if side:
            meta["sidenote"] = side

        body = _inline(self.pat, title)
        for y in years:
            body += f" `({str(y)[2:]})`"
        if side:
            body += f" `{side}`"
        if score:
            body += f" `{score}`"
        self.blocks.append(self._mk("heading", body, level=level, page=page_no, meta=meta))

    def _take_sidenote(self, y: float | None) -> str | None:
        if not self._sidenotes:
            return None
        if y is None:
            return self._sidenotes.pop(0)["text"]
        best, dist = None, None
        for k, s in enumerate(self._sidenotes):
            sy = s.get("y")
            d = abs(sy - y) if sy is not None else self._side_tol
            if dist is None or d < dist:
                best, dist = k, d
        if dist is not None and dist <= self._side_tol:
            return self._sidenotes.pop(best)["text"]
        return None

    def _paragraph(self, text: str, page_no: int) -> None:
        new = bool(_LIST_HEAD.match(text)) or not self._para or _SENT_END.search(self._para[-1])
        if new:
            self._flush_para()
            self._para_page = page_no
        self._para.append(text)

    def _flush_para(self) -> None:
        if not self._para:
            return
        text = _join_lines(self._para, self.join)
        self._para = []
        if not text.strip():
            return
        kind = "prompt" if self._in_prompt else "para"
        rendered = _inline(self.pat, text)
        if kind == "prompt":
            rendered = "\n".join("> " + l for l in rendered.splitlines())
        self.blocks.append(self._mk(kind, rendered, page=self._para_page))

    def _flush_footnotes(self, final: bool = False) -> None:
        """섹션이 바뀌기 직전에 그 섹션의 각주를 통째로 쏟아낸다 (§2.5).

        단, 지금 읽고 있는 쪽의 각주는 아직 내보내지 않는다. 각주는 페이지
        아래쪽에 있어 본문보다 먼저 수집되는데, 그대로 쏟으면 그 각주를
        참조하는 섹션보다 **앞에** 놓이게 된다. 그 쪽을 다 지난 뒤에 내보내야
        참조와 정의가 같은 섹션 안에서 만난다.

        참조를 못 찾은 각주도 버리지 않는다. 불일치는 검증이 알린다.
        """
        ready = self._pending if final else [f for f in self._pending if f.page < self._page]
        if not ready:
            return
        rest = [f for f in self._pending if f not in ready]
        body = "\n".join(f.markdown() for f in sorted(ready, key=lambda f: f.number))
        self.blocks.append(self._mk("footnotes", _inline(self.pat, body),
                                    page=ready[0].page))
        self._pending = rest

    # ── ⑧ 보너스 논점 박스 (§4.4) ────────────────────────────────
    def _bonus_head(self, text: str) -> str | None:
        """줄 맨 앞 ☑(또는 그 오인식) 뒤에 한글 제목이 오면 박스 시작으로 본다."""
        first = text[0]
        rest = text[1:].strip()
        if first == self._bonus_marker or first in self._bonus_misread:
            return rest or None
        if first in self._bonus_ascii and text[1:2] in (" ", "\t") and _CJK.match(rest[:1] or ""):
            return rest or None
        return None

    def _bonus_continues(self, text: str) -> bool:
        if len(self._bonus) >= self._bonus_max:
            return False
        for _, rx in self._heads:
            if rx.match(text):
                return False
        m = _NUM_ITEM.match(text)
        if m and int(m.group(1)) == self._last_item + 1:
            return False        # 박스 앞 번호가 이어진다 = 박스 끝
        return True

    def _close_bonus(self, page_no: int) -> None:
        lines = [f"> ### ☑ {_inline(self.pat, self._bonus_title)}"]
        for text in self._bonus:
            lines.append("> " + _inline(self.pat, text))
        self.blocks.append(self._mk("bonus", "\n".join(lines), page=page_no,
                                    meta={"bonus_topic": self._bonus_title}))
        self._bonus, self._bonus_title = None, ""

    # ── ① 논점 윤곽 띠 ───────────────────────────────────────────
    def _outline_items(self, text: str) -> list[str]:
        """'& 의의 - 소송물 - 중복소제기 - 시효중단 - 기판력' 같은 띠를 가른다.

        아는 낱말 수만으로 판정하면 교재마다 어휘가 달라 놓친다. 그래서 모양
        (짧은 토막 여럿이 구분자로 이어지고 문장으로 끝나지 않는다)을 먼저 보고,
        아는 낱말이 하나라도 있는지로 확인한다.
        """
        body = text.strip()
        if len(body) > 60 or _SENT_END.search(body):
            return []
        lead = self._outline.get("lead_marker")
        if lead:
            body = re.sub(lead, "", body)
        items = [t.strip() for t in re.split(self._outline["separator"], body) if t.strip()]
        if len(items) < int(self._outline["min_items"]):
            return []
        if any(len(t) > int(self._outline.get("max_item_len", 10)) for t in items):
            return []
        keys = set(self._outline["keywords"])
        if sum(1 for t in items if t in keys) < int(self._outline.get("min_known", 1)):
            return []
        return items

    # ── 블록 만들기 ──────────────────────────────────────────────
    def _mk(self, kind, text, level=0, page=0, meta=None) -> Block:
        return Block(kind=kind, text=text, level=level, page=page,
                     cases=_case_entries(self.pat, self._label_rx, text),
                     mnemonics=self.pat.find_mnemonics(text),
                     meta=meta or {})


# ── 도우미 ──────────────────────────────────────────────────────
def _case_entries(pat: Patterns, label_rx: re.Pattern, text: str) -> list[dict]:
    """③ 판례 제목 라벨 + ④ 표준판례(*) 를 사건번호에 짝지어 뽑는다 (§1.5).

    사건번호만으로는 무슨 판례인지 알 수 없다. 라벨이 있으면 반드시 함께 남긴다.
    """
    out = []
    for chunk in text.split("\n"):
        label = _label_of(label_rx, chunk)
        for m in pat.case.finditer(chunk):
            standard = chunk[m.end():m.end() + 1] == "*"
            out.append({"id": m.group(0), "label": label, "standard": standard})
    return out


def _label_of(label_rx: re.Pattern, chunk: str) -> str:
    chunk = _strip_markup(chunk).strip()
    m = label_rx.match(chunk)
    if m:
        return m.group("label").strip()
    # 라벨이 대괄호로 안 싸인 짧은 머리말도 받는다: '(1) 원칙 …'
    m = _LIST_HEAD.match(chunk)
    if not m:
        return ""
    head = re.split(r"[\[(（.]", chunk[m.end():], 1)[0].strip()
    return head if 0 < len(head) <= 12 else ""


def _strip_markup(text: str) -> str:
    """우리가 넣은 마크업(==, **, 백틱)을 걷어낸다. 라벨·제목을 읽을 때만 쓴다."""
    return re.sub(r"`|={2}|\*{2}", "", text)


def _take_exam_years(rx: re.Pattern, title: str, century: int) -> tuple[list[int], str]:
    """⑨ 제목 뒤 (11) → 2011. 복수는 (15)(20). 제목에서 떼어낸다."""
    years, spans = [], []
    for m in rx.finditer(title):
        two = int(m.group(1))
        years.append((1900 if two >= century else 2000) + two)
        spans.append((m.start(), m.end()))
    for a, b in reversed(spans):
        title = title[:a] + title[b:]
    return years, re.sub(r"\s{2,}", " ", title).strip()


def _split_score(rx: re.Pattern | None, text: str, limit: float = 50,
                 allow_bare: bool = False) -> tuple[str | None, str]:
    """제목 끝 배점을 뗀다. '2. 일부청구 소송물 (2.5)' → ('2.5', '2. 일부청구 소송물')

    정규식이 줄 끝만 보고, 앞이 글자·숫자면 안 잡도록 돼 있다. 그래서
    '(74다1557)' 의 1557 은 배점으로 새지 않는다. 값이 너무 크면 배점이
    아니라고 보고 원문을 그대로 둔다.
    """
    if not rx:
        return None, text
    m = rx.search(text)
    if not m:
        return None, text
    try:
        if float(m.group(1)) > limit:
            return None, text
    except ValueError:                       # pragma: no cover
        return None, text
    head = text[:m.start()].rstrip(" .·-—")
    if not head and not allow_bare:
        return None, text                    # 숫자만 있는 줄은 제목이 아니다
    return m.group(1), head


def _inline(pat: Patterns, text: str) -> str:
    """두문자를 백틱으로 감싼다 (§6.1).

    자리까지 보고 고른 것만 감싼다. 줄 맨 앞 대괄호는 ③ 판례 제목 라벨이라
    두문자가 아니다. 두 번 감싸지 않는다.
    """
    spans = pat.mnemonic_spans(text)
    if not spans:
        return text
    out, cursor = [], 0
    for start, end, _ in spans:
        if text[max(0, start - 1):start] == "`" and text[end:end + 1] == "`":
            continue
        out.append(text[cursor:start])
        out.append(f"`{text[start:end]}`")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _join_lines(lines: list[str], mode: str) -> str:
    """줄바꿈으로 끊긴 문단을 잇는다.

    space  줄 사이에 공백 하나(기본). 한글 책은 어절 안에서도 줄을 바꾸지만,
           붙여 버리면 없던 낱말이 생겨 뒤 처리가 더 크게 망가진다.
    none   붙인다. 원문에 없던 글자를 절대 넣지 않아야 할 때.
    break  줄바꿈을 그대로 둔다. 완전 무손실.
    """
    if mode == "break":
        return "\n".join(lines)
    out = lines[0]
    for tail in lines[1:]:
        head = out.rstrip()
        if head.endswith("-") and tail[:1].isascii():
            out = head[:-1] + tail
            continue
        if re.search(r"\d{2,4}[가-힣]{1,2}$", head) and tail[:1].isdigit():
            out = head + tail          # 사건번호가 줄에서 끊긴 경우
            continue
        if mode == "none" and _CJK.search(head[-1:] or "") and _CJK.search(tail[:1] or ""):
            out = head + tail
            continue
        out = head + " " + tail
    return out


def render(blocks: list[Block]) -> str:
    out = []
    for b in blocks:
        out.append("#" * b.level + " " + b.text if b.kind == "heading" else b.text)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
