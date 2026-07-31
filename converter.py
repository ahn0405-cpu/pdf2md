"""PDF -> Markdown 변환기.

원본 PDF의 시각적 서식(제목 계층, 문단, 목록, 표, 굵게/기울임, 이미지, 링크)을
최대한 보존해 Markdown으로 옮기는 것을 목표로 한다.

핵심 아이디어
- PyMuPDF의 span 단위 정보(글자 크기 / bold·italic·mono 플래그 / 좌표)를 그대로 활용한다.
- 문서 전체의 글자 크기 분포에서 '본문 크기'를 추정하고, 그보다 큰 크기를 등급별로
  h1..h6에 매핑한다. PDF 북마크(TOC)가 있으면 그쪽을 우선한다.
- 페이지를 가로 여백(gutter) 기준으로 단(column)으로 나눠 읽기 순서를 복원한다.
- 여러 페이지에 반복되는 머리말/꼬리말·쪽번호를 통계로 찾아 제거한다.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import re
import threading
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

import pymupdf

# find_tables() 가 매번 찍는 레이아웃 패키지 광고 문구를 끈다.
if hasattr(pymupdf, "no_recommend_layout"):
    pymupdf.no_recommend_layout()

# MuPDF 컨텍스트는 프로세스에 하나뿐이라 동시 호출하면 결과가 섞인다
# (여러 파일을 병렬 변환하면 표 셀 글자가 중복되는 식으로 깨진다).
# 변환 전체를 한 번에 하나씩만 수행하도록 직렬화한다.
_MUPDF_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# 옵션
# ---------------------------------------------------------------------------


@dataclass
class Options:
    detect_headings: bool = True     # 글자 크기/북마크로 제목 인식
    use_toc: bool = True             # PDF 북마크를 제목 계층에 사용
    detect_lists: bool = True        # 글머리표·번호 목록 인식
    inline_styles: bool = True       # **굵게**, *기울임*, `고정폭`
    links: bool = True               # PDF 링크 주석을 [text](url) 로
    tables: str = "markdown"         # markdown | html | text | skip
    images: str = "extract"          # extract | base64 | skip
    strip_header_footer: bool = True  # 반복 머리말/꼬리말·쪽번호 제거
    join_hyphens: bool = True        # 줄바꿈 하이픈 병합
    page_separator: bool = False     # 페이지마다 --- 삽입
    page_comment: bool = False       # 페이지마다 <!-- page N --> 주석
    front_matter: bool = False       # YAML front matter(제목/작성자/출처)
    columns: bool = True             # 다단 레이아웃 읽기 순서 복원

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Options":
        opt = cls()
        if not data:
            return opt
        for key, value in data.items():
            if not hasattr(opt, key):
                continue
            current = getattr(opt, key)
            if isinstance(current, bool):
                if isinstance(value, str):
                    value = value.lower() in ("1", "true", "on", "yes")
                setattr(opt, key, bool(value))
            elif isinstance(current, str):
                setattr(opt, key, str(value))
        if opt.tables not in ("markdown", "html", "text", "skip"):
            opt.tables = "markdown"
        if opt.images not in ("extract", "base64", "skip"):
            opt.images = "extract"
        return opt

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Asset:
    name: str
    data: bytes
    mime: str


@dataclass
class Result:
    markdown: str
    assets: list[Asset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    asset_dir: str = ""      # 추출 이미지를 담는 폴더명 (없으면 빈 문자열)


# ---------------------------------------------------------------------------
# span 플래그 / 문자열 유틸
# ---------------------------------------------------------------------------

FLAG_SUPERSCRIPT = 1 << 0
FLAG_ITALIC = 1 << 1
FLAG_MONO = 1 << 3
FLAG_BOLD = 1 << 4

_BOLD_NAME = re.compile(r"(bold|black|heavy|semib|demib|extrab|ultrab)", re.I)
_ITALIC_NAME = re.compile(r"(italic|oblique)", re.I)
_MONO_NAME = re.compile(r"(mono|courier|consol|menlo|d2coding|nanumgothiccoding)", re.I)

# 글머리표로 쓰이는 문자들
_BULLETS = "•‣▪▫●○◦⁃∙·■□❖➤➔§"
_BULLET_RE = re.compile(rf"^\s*([{_BULLETS}]|[-*+–—])\s+(?=\S)")
_ORDERED_RE = re.compile(
    r"^\s*("
    r"\d{1,3}[.)]"                      # 1. / 1)
    r"|\(\d{1,3}\)"                     # (1)
    r"|[a-zA-Z][.)]"                    # a. / a)
    r"|\([a-zA-Z]\)"                    # (a)
    r"|[ivxIVX]{1,5}[.)]"               # iv.
    r"|[가-힣][.)]"                      # 가. / 가)
    r"|\([가-힣]\)"                      # (가)
    r")\s+(?=\S)"
)
_CIRCLED_RE = re.compile(r"^\s*([①-⑳㉑-㉟㊱-㊿])\s*(?=\S)")

# 번호형 제목: "1.", "1.1", "2.3.4", "제1장", "제 3 조"
_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:(\d+(?:\.\d+){0,4})[.)]?\s+\S|제\s*\d+\s*[장절편관조항]\s*)"
)

_CJK_RE = re.compile(
    r"[ᄀ-ᇿ⺀-鿿ꥠ-꥿가-퟿豈-﫿＀-ﾟ]"
)


_NOSPACE_CJK_RE = re.compile(
    "[⺀-鿿豈-﫿぀-ヿㇰ-ㇿ]"
)


def _is_cjk(ch: str) -> bool:
    """한글·한자·가나 등 CJK 글자인지."""
    return bool(_CJK_RE.match(ch))


def _is_nospace_cjk(ch: str) -> bool:
    """줄바꿈에 공백이 개입하지 않는 문자(한자·가나)인지.

    한글은 어절 사이 공백에서 줄이 바뀌므로 이어 붙일 때 공백을 되살려야 하지만,
    한자·가나는 아무 곳에서나 줄이 바뀌므로 공백 없이 붙여야 원문이 복원된다.
    """
    return bool(_NOSPACE_CJK_RE.match(ch))


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fingerprint(text: str) -> str:
    """머리말/꼬리말 비교용 지문 — 숫자는 자리표시자로 바꾼다."""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"\d+", "#", t)
    return re.sub(r"\s+", "", t).strip().lower()


def escape_md(text: str) -> str:
    """Markdown 특수문자 이스케이프(과하지 않게)."""
    text = text.replace("\\", "\\\\")
    text = re.sub(r"([*_`\[\]<>])", r"\\\1", text)
    return text


_LEADING_NUM_RE = re.compile(r"^(\s*)(\d{1,9})([.)]\s)")


def _escape_leading(line: str) -> str:
    """문단 첫머리가 우연히 Markdown 문법으로 읽히는 것을 막는다.

    번호는 `\\1.` 이 아니라 `1\\.` 처럼 구두점 앞에 역슬래시를 넣어야 한다.
    (`\\1` 은 Markdown 이스케이프가 아니라서 역슬래시가 그대로 보인다.)
    """
    m = _LEADING_NUM_RE.match(line)
    if m:
        return f"{m.group(1)}{m.group(2)}\\{m.group(3)}{line[m.end():]}"
    return re.sub(r"^(\s*)([#>|]|[-+*](?=\s))", r"\1\\\2", line, count=1)


def _strip_outer_emphasis(text: str) -> str:
    """전체가 하나의 강조로 감싸인 경우에만 그 표시를 벗긴다.

    `**A** **B**` 처럼 강조가 여러 개면 벗기다 마크업이 깨지므로 손대지 않는다.
    """
    for mark in ("***", "**", "*"):
        if len(text) > 2 * len(mark) and text.startswith(mark) and text.endswith(mark):
            inner = text[len(mark):-len(mark)]
            if mark not in inner:
                return inner
    return text


# ---------------------------------------------------------------------------
# 저수준 추출 구조
# ---------------------------------------------------------------------------


@dataclass
class Span:
    text: str
    size: float
    bold: bool
    italic: bool
    mono: bool
    superscript: bool
    bbox: tuple[float, float, float, float]
    link: str | None = None


@dataclass
class Line:
    spans: list[Span]
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def size(self) -> float:
        weighted = [(len(s.text.strip()), s.size) for s in self.spans if s.text.strip()]
        if not weighted:
            return 0.0
        total = sum(w for w, _ in weighted)
        return sum(w * s for w, s in weighted) / max(total, 1)

    @property
    def all_bold(self) -> bool:
        spans = [s for s in self.spans if s.text.strip()]
        return bool(spans) and all(s.bold for s in spans)

    @property
    def all_mono(self) -> bool:
        spans = [s for s in self.spans if s.text.strip()]
        return bool(spans) and all(s.mono for s in spans)


@dataclass
class Element:
    kind: str                       # "text" | "table" | "image"
    bbox: tuple[float, float, float, float]
    lines: list[Line] = field(default_factory=list)
    payload: Any = None


# ---------------------------------------------------------------------------
# 페이지 파싱
# ---------------------------------------------------------------------------


def _span_from_raw(raw: dict, links: list[tuple[pymupdf.Rect, str]]) -> Span:
    flags = raw.get("flags", 0)
    font = raw.get("font", "") or ""
    bbox = tuple(raw.get("bbox", (0, 0, 0, 0)))
    uri = None
    if links:
        rect = pymupdf.Rect(bbox)
        for lrect, luri in links:
            inter = rect & lrect
            if inter.is_valid and inter.get_area() > 0.4 * max(rect.get_area(), 1e-6):
                uri = luri
                break
    return Span(
        text=raw.get("text", ""),
        size=round(float(raw.get("size", 0.0)), 2),
        bold=bool(flags & FLAG_BOLD) or bool(_BOLD_NAME.search(font)),
        italic=bool(flags & FLAG_ITALIC) or bool(_ITALIC_NAME.search(font)),
        mono=bool(flags & FLAG_MONO) or bool(_MONO_NAME.search(font)),
        superscript=bool(flags & FLAG_SUPERSCRIPT),
        bbox=bbox,
        link=uri,
    )


def _page_links(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    out: list[tuple[pymupdf.Rect, str]] = []
    try:
        for link in page.get_links():
            uri = link.get("uri")
            if uri and link.get("from"):
                out.append((pymupdf.Rect(link["from"]), uri))
    except Exception:
        pass
    return out


def _rect_overlap_ratio(a: tuple, b: tuple) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    area = max((ax1 - ax0) * (ay1 - ay0), 1e-6)
    return inter / area


# ---------------------------------------------------------------------------
# 읽기 순서 복원 (밴드 -> 단)
# ---------------------------------------------------------------------------


def _split_columns(elems: list[Element], x0: float, x1: float, depth: int = 0) -> list[list[Element]]:
    """수직 여백(gutter)을 찾아 요소들을 단 단위로 나눈다."""
    if depth >= 2 or len(elems) < 4:
        return [elems]

    width = x1 - x0
    if width <= 0:
        return [elems]

    bins = 200
    covered = [False] * bins
    for el in elems:
        b0 = max(0, int((el.bbox[0] - x0) / width * bins))
        b1 = min(bins - 1, int(math.ceil((el.bbox[2] - x0) / width * bins)))
        for i in range(b0, b1 + 1):
            covered[i] = True

    # 페이지 가운데 부분(20~80%)에서 가장 넓은 빈 띠 찾기
    best = None
    i = 0
    while i < bins:
        if covered[i]:
            i += 1
            continue
        j = i
        while j < bins and not covered[j]:
            j += 1
        run = (i, j - 1)
        center = (run[0] + run[1]) / 2 / bins
        if 0.20 <= center <= 0.80 and (j - i) >= bins * 0.035:
            if best is None or (run[1] - run[0]) > (best[1] - best[0]):
                best = run
        i = j

    if best is None:
        return [elems]

    cut = x0 + ((best[0] + best[1]) / 2 / bins) * width
    left = [e for e in elems if (e.bbox[0] + e.bbox[2]) / 2 < cut]
    right = [e for e in elems if (e.bbox[0] + e.bbox[2]) / 2 >= cut]
    if not left or not right:
        return [elems]

    out: list[list[Element]] = []
    out.extend(_split_columns(left, x0, cut, depth + 1))
    out.extend(_split_columns(right, cut, x1, depth + 1))
    return out


def _order_elements(elems: list[Element], page_rect: pymupdf.Rect, use_columns: bool) -> list[Element]:
    elems = sorted(elems, key=lambda e: (round(e.bbox[1], 1), round(e.bbox[0], 1)))
    if not use_columns or len(elems) < 4:
        return elems

    page_w = page_rect.width or 1.0
    full_width = [e for e in elems if (e.bbox[2] - e.bbox[0]) > page_w * 0.66]
    full_set = {id(e) for e in full_width}

    # 전폭 요소를 경계로 세로 밴드를 나눈 뒤, 각 밴드 안에서만 단을 찾는다.
    ordered: list[Element] = []
    band: list[Element] = []
    for el in elems:
        if id(el) in full_set:
            if band:
                ordered.extend(_flush_band(band, page_rect))
                band = []
            ordered.append(el)
        else:
            band.append(el)
    if band:
        ordered.extend(_flush_band(band, page_rect))
    return ordered


def _flush_band(band: list[Element], page_rect: pymupdf.Rect) -> list[Element]:
    columns = _split_columns(band, page_rect.x0, page_rect.x1)
    if len(columns) <= 1:
        return sorted(band, key=lambda e: (round(e.bbox[1], 1), round(e.bbox[0], 1)))
    columns.sort(key=lambda col: min(e.bbox[0] for e in col))
    out: list[Element] = []
    for col in columns:
        out.extend(sorted(col, key=lambda e: (round(e.bbox[1], 1), round(e.bbox[0], 1))))
    return out


# ---------------------------------------------------------------------------
# 표
# ---------------------------------------------------------------------------


def _cell_text(value: Any) -> str:
    """셀 원문. 줄바꿈은 `\\n` 으로 남겨 두고 표현은 각 렌더러가 정한다."""
    if value is None:
        return ""
    text = str(value).replace("\r", "\n").strip()
    text = re.sub(r"\n+", "\n", text)
    return re.sub(r"[ \t]+", " ", text)


def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _grid(rows: list[list[Any]]) -> tuple[list[list[str]], int]:
    rows = [r for r in rows if any(_cell_text(c) for c in r)]
    if not rows:
        return [], 0
    width = max(len(r) for r in rows)
    return [[_cell_text(c) for c in r] + [""] * (width - len(r)) for r in rows], width


def _table_to_markdown(rows: list[list[Any]]) -> str:
    grid, width = _grid(rows)
    if not grid:
        return ""

    def cell(text: str) -> str:
        # 셀 안의 문자가 표 문법·강조·원시 HTML 로 읽히지 않게 막는다
        text = escape_md(text).replace("|", "\\|")
        return text.replace("\n", "<br>")

    header = [c or f"열{i + 1}" for i, c in enumerate(grid[0])]
    lines = ["| " + " | ".join(cell(c) for c in header) + " |",
             "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(cell(c) for c in r) + " |" for r in grid[1:])
    return "\n".join(lines)


def _table_to_html(rows: list[list[Any]]) -> str:
    grid, _ = _grid(rows)
    if not grid:
        return ""
    out = ["<table>"]
    for idx, row in enumerate(grid):
        tag = "th" if idx == 0 else "td"
        cells = (f"<{tag}>{_html_escape(c).replace(chr(10), '<br>')}</{tag}>" for c in row)
        out.append("  <tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def _table_to_text(rows: list[list[Any]]) -> str:
    grid, _ = _grid(rows)
    if not grid:
        return ""
    body = "\n".join("\t".join(c.replace("\n", " ") for c in row) for row in grid)
    return "```\n" + body + "\n```"


# ---------------------------------------------------------------------------
# 본문 렌더링
# ---------------------------------------------------------------------------


class _Renderer:
    def __init__(self, opt: Options, body_size: float, heading_map: dict[float, int],
                 list_stops: list[float]):
        self.opt = opt
        self.body_size = body_size
        self.heading_map = heading_map
        # 문서 전체에서 관찰된 목록 항목의 왼쪽 시작 위치들(오름차순) = 들여쓰기 단계
        self.list_stops = list_stops

    # -- 인라인 -------------------------------------------------------------

    def render_inline(self, spans: list[Span]) -> str:
        merged: list[Span] = []
        for sp in spans:
            if not sp.text:
                continue
            if merged:
                prev = merged[-1]
                same = (
                    prev.bold == sp.bold
                    and prev.italic == sp.italic
                    and prev.mono == sp.mono
                    and prev.link == sp.link
                )
                if same:
                    prev.text += sp.text
                    continue
            merged.append(Span(**{**sp.__dict__}))

        parts: list[str] = []
        for sp in merged:
            raw = sp.text
            if not raw.strip():
                parts.append(" " if raw else "")
                continue
            lead = raw[: len(raw) - len(raw.lstrip())]
            trail = raw[len(raw.rstrip()):]
            core = raw.strip()

            if self.opt.inline_styles and sp.mono:
                tick = "`"
                while tick in core:
                    tick += "`"
                # 내용이 백틱으로 시작/끝나면 공백을 한 칸 덧대야 안쪽 백틱이 살아남는다
                pad = " " if core.startswith("`") or core.endswith("`") else ""
                text = f"{tick}{pad}{core}{pad}{tick}"
            else:
                text = escape_md(core)
                if self.opt.inline_styles:
                    if sp.bold and sp.italic:
                        text = f"***{text}***"
                    elif sp.bold:
                        text = f"**{text}**"
                    elif sp.italic:
                        text = f"*{text}*"

            if self.opt.links and sp.link:
                text = f"[{text}]({sp.link})"

            parts.append(f"{lead}{text}{trail}")

        out = "".join(parts)
        return re.sub(r"[ \t]+", " ", out).strip()

    # -- 줄 -> 문단 ---------------------------------------------------------

    def join_lines(self, chunks: list[tuple[Line, str]]) -> str:
        """같은 문단에 속한 줄들을 자연스럽게 잇는다."""
        out = ""
        for line, rendered in chunks:
            if not rendered:
                continue
            if not out:
                out = rendered
                continue
            prev_char = out.rstrip()[-1:] if out.rstrip() else ""
            next_char = rendered.lstrip()[:1]
            if self.opt.join_hyphens and prev_char == "-" and next_char.isalpha() and not _is_cjk(next_char):
                out = out.rstrip()[:-1] + rendered.lstrip()
            elif next_char in ",.)]}·":
                out = out.rstrip() + rendered.lstrip()
            elif _is_nospace_cjk(prev_char) and _is_nospace_cjk(next_char):
                out = out.rstrip() + rendered.lstrip()
            else:
                out = out.rstrip() + " " + rendered.lstrip()
        return out

    # -- 목록/제목 판정 -----------------------------------------------------

    def list_marker(self, text: str) -> tuple[str, str, str] | None:
        """(마크다운 글머리, 원본 마커, 마커를 뗀 본문) 또는 None."""
        if not self.opt.detect_lists:
            return None
        m = _BULLET_RE.match(text)
        if m:
            return "-", m.group(1), text[m.end():]
        m = _ORDERED_RE.match(text)
        if m:
            marker = m.group(1)
            num = re.sub(r"\D", "", marker)
            return (f"{num}." if num else "1."), marker, text[m.end():]
        m = _CIRCLED_RE.match(text)
        if m:
            # 원문자는 번호 정보를 잃지 않도록 본문 앞에 남긴다
            return "-", "", text[m.start():]
        return None

    def indent_level(self, x0: float) -> int:
        if not self.list_stops:
            return 0
        nearest = min(range(len(self.list_stops)),
                      key=lambda i: abs(self.list_stops[i] - x0))
        return min(4, nearest)

    def heading_level(self, line: Line) -> int | None:
        if not self.opt.detect_headings:
            return None
        text = _norm_ws(line.text)
        if not text or len(text) > 200:
            return None
        size = round(line.size, 2)
        for mapped_size, level in self.heading_map.items():
            if abs(size - mapped_size) < 0.26:
                return level
        # 본문 크기지만 굵고 짧으며 마침표로 끝나지 않는 번호형 제목
        if (
            line.all_bold
            and size >= self.body_size - 0.3
            and len(text) <= 80
            and not text.endswith((".", "다.", "요.", ",", ";"))
            and _NUMBERED_HEADING_RE.match(text)
        ):
            return min(6, len(self.heading_map) + 1) if self.heading_map else 3
        return None


# ---------------------------------------------------------------------------
# 메인 변환
# ---------------------------------------------------------------------------


def _collect_size_stats(doc: pymupdf.Document, pages: list[dict]) -> tuple[float, dict[float, int]]:
    counter: Counter = Counter()
    for page in pages:
        for block in page.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        counter[round(float(span.get("size", 0)), 1)] += len(text)
    if not counter:
        return 10.0, {}

    body_size = counter.most_common(1)[0][0]
    # 본문보다 확실히 큰 크기만 제목 후보 (본문 대비 최소 8%)
    candidates = sorted(
        # 한글 제목은 "개요"처럼 두세 글자인 경우가 흔하므로 문턱을 낮게 잡는다
        (size for size, chars in counter.items()
         if size >= body_size * 1.08 and chars >= 3),
        reverse=True,
    )
    # 0.5pt 이내는 같은 등급으로 묶는다
    grouped: list[float] = []
    for size in candidates:
        if grouped and abs(grouped[-1] - size) < 0.5:
            continue
        grouped.append(size)

    heading_map = {size: min(6, idx + 1) for idx, size in enumerate(grouped[:6])}
    return body_size, heading_map


def _in_running_zone(y0: float, y1: float, page_height: float) -> bool:
    """머리말/꼬리말이 놓이는 페이지 위·아래 10% 구간인지."""
    return y1 <= page_height * 0.10 or y0 >= page_height * 0.90


def _page_line_index(page: dict) -> list[tuple[tuple, str]]:
    """페이지의 (줄 상자, 지문) 목록 — 반복 문구 판정에 쓴다."""
    out: list[tuple[tuple, str]] = []
    for block in page.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = _norm_ws("".join(s.get("text", "") for s in line.get("spans", [])))
            if text:
                out.append((tuple(line.get("bbox", (0, 0, 0, 0))), _fingerprint(text)))
    return out


def _is_standalone_line(bbox: tuple, page_lines: list[tuple[tuple, str]],
                        running: set[str]) -> bool:
    """그 줄이 가로줄 하나를 혼자 쓰는지.

    매 페이지 같은 자리에 반복되는 본문 말머리("Best for:" 처럼 뒤에 내용이 이어지는 말)는
    지문만 보면 꼬리말과 구별되지 않는다. 같은 가로줄에 매번 달라지는 글이 함께 있으면
    본문으로 보고 남긴다. 진짜 머리말/꼬리말은 그 줄을 혼자 차지한다.
    """
    y0, y1 = bbox[1], bbox[3]
    height = max(y1 - y0, 1e-6)
    for other_bbox, other_fp in page_lines:
        if other_bbox == bbox:
            continue
        overlap = min(y1, other_bbox[3]) - max(y0, other_bbox[1])
        if overlap > height * 0.5 and other_fp not in running:
            return False
    return True


def _detect_running(pages: list[dict], page_count: int) -> set[str]:
    """여러 페이지에 반복 등장하는 머리말/꼬리말 지문을 찾는다."""
    if page_count < 3:
        return set()
    seen: dict[str, set[int]] = defaultdict(set)
    for pno, page in enumerate(pages):
        height = page.get("height", 842) or 842
        for block in page.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                y0 = line.get("bbox", (0, 0, 0, 0))[1]
                y1 = line.get("bbox", (0, 0, 0, 0))[3]
                if not _in_running_zone(y0, y1, height):
                    continue
                text = _norm_ws("".join(s.get("text", "") for s in line.get("spans", [])))
                if not text or len(text) > 120:
                    continue
                seen[_fingerprint(text)].add(pno)
    threshold = max(2, math.ceil(page_count * 0.5))
    return {fp for fp, pnos in seen.items() if len(pnos) >= threshold and fp}


def _looks_like_list(text: str) -> bool:
    return bool(_BULLET_RE.match(text) or _ORDERED_RE.match(text) or _CIRCLED_RE.match(text))


def _list_indent_stops(pages: list[dict], body_size: float) -> list[float]:
    """목록 항목들의 왼쪽 시작 x좌표를 군집화해 들여쓰기 단계를 만든다.

    고정 폭으로 나누면 문서마다 들여쓰기 폭이 달라 단계가 틀어진다.
    실제로 등장한 위치만 모아 순서를 매기는 편이 정확하다.
    """
    xs: list[float] = []
    for page in pages:
        for block in page.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = _norm_ws("".join(s.get("text", "") for s in line.get("spans", [])))
                if text and _looks_like_list(text):
                    xs.append(round(line.get("bbox", (0, 0, 0, 0))[0], 1))
    if not xs:
        return []

    tolerance = max(4.0, body_size * 0.5)
    xs.sort()
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    # 단계는 최대 5개까지, 자주 등장한 위치를 우선한다(오탐 방지)
    clusters.sort(key=len, reverse=True)
    keep = clusters[:5]
    keep.sort(key=lambda c: c[0])
    return [sum(c) / len(c) for c in keep]


def _all_mono(el: Element) -> bool:
    return bool(el.lines) and all(l.all_mono for l in el.lines)


def _elem_size(el: Element) -> float:
    sizes = [l.size for l in el.lines if l.size]
    if not sizes:
        return 0.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def _merge_text_elements(elems: list[Element]) -> list[Element]:
    """줄 간격만큼만 떨어진 연속 텍스트 블록을 한 문단 덩어리로 합친다.

    PDF 생성기에 따라 한 문단의 각 줄이 별개 블록으로 나오는 경우가 많다.
    합쳐 두면 뒤에서 줄 잇기·문단 분리를 일관되게 처리할 수 있다.
    """
    out: list[Element] = []
    for el in elems:
        if el.kind != "text" or not out or out[-1].kind != "text":
            out.append(el)
            continue

        prev = out[-1]
        size = _elem_size(el) or 10.0
        prev_size = _elem_size(prev) or 10.0
        gap = el.bbox[1] - prev.bbox[3]
        # 코드는 줄마다 들여쓰기가 달라지는 게 정상이라 정렬 조건을 적용하지 않는다
        both_mono = _all_mono(prev) and _all_mono(el)
        aligned = both_mono or abs(el.bbox[0] - prev.bbox[0]) <= max(2.0, size * 1.6)
        similar = abs(size - prev_size) <= max(0.4, prev_size * 0.12)

        if -1.0 <= gap <= max(size * 0.55, 2.5) and aligned and similar:
            prev.lines.extend(el.lines)
            prev.bbox = (
                min(prev.bbox[0], el.bbox[0]), min(prev.bbox[1], el.bbox[1]),
                max(prev.bbox[2], el.bbox[2]), max(prev.bbox[3], el.bbox[3]),
            )
        else:
            out.append(el)
    return out


def _tighten_lists(markdown: str) -> str:
    """연속된 목록 항목 사이의 빈 줄을 없애 촘촘한 목록으로 만든다."""
    item = re.compile(r"^\s*(?:[-*+]|\d{1,3}\.)\s+\S")
    lines = markdown.split("\n")
    out: list[str] = []
    for idx, line in enumerate(lines):
        if (
            not line.strip()
            and out and item.match(out[-1])
            and idx + 1 < len(lines) and item.match(lines[idx + 1])
        ):
            continue
        out.append(line)
    return "\n".join(out)


def _toc_by_page(doc: pymupdf.Document) -> dict[int, list[tuple[int, str]]]:
    out: dict[int, list[tuple[int, str]]] = defaultdict(list)
    try:
        for level, title, page in doc.get_toc(simple=True):
            if page and page > 0:
                out[page - 1].append((min(6, max(1, level)), _norm_ws(title)))
    except Exception:
        pass
    return out


def convert(pdf_bytes: bytes, filename: str = "document.pdf",
            options: Options | dict | None = None) -> Result:
    with _MUPDF_LOCK:
        return _convert(pdf_bytes, filename, options)


def _convert(pdf_bytes: bytes, filename: str,
             options: Options | dict | None) -> Result:
    opt = options if isinstance(options, Options) else Options.from_dict(options)
    stem = re.sub(r"\.pdf$", "", filename, flags=re.I) or "document"
    safe_stem = re.sub(r"[^\w\-.가-힣]+", "_", stem).strip("_") or "document"
    asset_dir = f"{safe_stem}.assets"

    warnings: list[str] = []
    assets: list[Asset] = []

    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # 손상 파일
        raise ValueError(f"PDF를 열 수 없습니다: {exc}") from exc

    if doc.needs_pass:
        raise ValueError("암호로 보호된 PDF입니다. 암호를 해제한 뒤 다시 시도하세요.")

    page_dicts = [page.get_text("dict") for page in doc]
    body_size, heading_map = _collect_size_stats(doc, page_dicts)
    running = _detect_running(page_dicts, doc.page_count) if opt.strip_header_footer else set()
    toc_pages = _toc_by_page(doc) if (opt.use_toc and opt.detect_headings) else {}

    total_chars = sum(
        len(s.get("text", "").strip())
        for pd in page_dicts
        for b in pd.get("blocks", []) if b.get("type") == 0
        for l in b.get("lines", [])
        for s in l.get("spans", [])
    )
    if total_chars < 40 * max(1, doc.page_count) and doc.page_count:
        has_image = any(
            b.get("type") == 1 for pd in page_dicts for b in pd.get("blocks", [])
        )
        warnings.append(
            "텍스트 레이어가 거의 없습니다. 스캔 이미지 PDF로 보이며, OCR 처리 후 변환해야 본문이 추출됩니다."
            if has_image else
            "추출할 텍스트를 찾지 못했습니다. 내용이 없는 PDF이거나 지원하지 않는 인코딩일 수 있습니다."
        )

    list_stops = _list_indent_stops(page_dicts, body_size) if opt.detect_lists else []
    renderer = _Renderer(opt, body_size, heading_map, list_stops)

    out: list[str] = []
    image_paths: dict[str, str] = {}    # 이미지 내용 해시 -> 파일 경로
    n_tables = 0
    n_images = 0
    n_headings = 0

    if opt.front_matter:
        meta = doc.metadata or {}
        fm = ["---", f'source: "{filename}"']
        if meta.get("title"):
            fm.append(f'title: "{_norm_ws(meta["title"])}"')
        if meta.get("author"):
            fm.append(f'author: "{_norm_ws(meta["author"])}"')
        fm.append(f"pages: {doc.page_count}")
        fm.append("---")
        out.append("\n".join(fm))

    for pno, page in enumerate(doc):
        pd = page_dicts[pno]
        page_rect = page.rect
        links = _page_links(page) if opt.links else []

        # --- 표 ------------------------------------------------------------
        table_elems: list[Element] = []
        if opt.tables != "skip":
            try:
                found = page.find_tables()
                for tbl in found.tables:
                    rows = tbl.extract()
                    if not rows or len(rows) < 2:
                        continue
                    table_elems.append(Element("table", tuple(tbl.bbox), payload=rows))
            except Exception:
                pass
        table_boxes = [e.bbox for e in table_elems]

        # --- 텍스트 / 이미지 ------------------------------------------------
        page_lines = _page_line_index(pd) if (opt.strip_header_footer and running) else []
        elems: list[Element] = list(table_elems)
        for block in pd.get("blocks", []):
            bbox = tuple(block.get("bbox", (0, 0, 0, 0)))

            if block.get("type") == 1:
                if opt.images == "skip":
                    continue
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                if width < 12 or height < 12:      # 구분선·아이콘 수준은 건너뜀
                    continue
                elems.append(Element("image", bbox, payload=block))
                continue

            if any(_rect_overlap_ratio(bbox, tb) > 0.55 for tb in table_boxes):
                continue

            lines: list[Line] = []
            for raw_line in block.get("lines", []):
                spans = [_span_from_raw(s, links) for s in raw_line.get("spans", [])]
                spans = [s for s in spans if s.text]
                if not spans or not "".join(s.text for s in spans).strip():
                    continue
                text = _norm_ws("".join(s.text for s in spans))
                if opt.strip_header_footer:
                    line_bbox = tuple(raw_line.get("bbox", (0, 0, 0, 0)))
                    y0, y1 = line_bbox[1], line_bbox[3]
                    page_h = pd.get("height", page_rect.height) or 1
                    # 반복 문구 제거는 페이지 위/아래 가장자리에서, 그 가로줄을 혼자
                    # 쓰는 줄에만 적용한다. (본문에 같은 문구가 있으면 함께 지워진다)
                    if (
                        _in_running_zone(y0, y1, page_h)
                        and _fingerprint(text) in running
                        and _is_standalone_line(line_bbox, page_lines, running)
                    ):
                        continue
                    edge = y1 < page_h * 0.08 or y0 > page_h * 0.92
                    if edge and re.fullmatch(r"[-–—\s]*\d{1,4}\s*(/\s*\d{1,4})?[-–—\s]*", text):
                        continue
                lines.append(Line(spans, tuple(raw_line.get("bbox", bbox))))
            if lines:
                elems.append(Element("text", bbox, lines=lines))

        elems = _merge_text_elements(_order_elements(elems, page_rect, opt.columns))

        page_md: list[str] = []
        toc_titles = toc_pages.get(pno, [])

        for el in elems:
            if el.kind == "table":
                rendered = (
                    _table_to_markdown(el.payload) if opt.tables == "markdown"
                    else _table_to_html(el.payload) if opt.tables == "html"
                    else _table_to_text(el.payload)
                )
                if rendered:
                    page_md.append(rendered)
                    n_tables += 1
                continue

            if el.kind == "image":
                block = el.payload
                data = block.get("image")
                if not data:
                    continue
                ext = (block.get("ext") or "png").lower()
                n_images += 1
                alt = f"{safe_stem} 이미지 {n_images}"

                if opt.images == "base64":
                    b64 = base64.b64encode(data).decode("ascii")
                    page_md.append(f"![{alt}](data:image/{ext};base64,{b64})")
                    continue

                # 페이지마다 반복되는 로고 등은 같은 파일 하나로 모은다
                digest = hashlib.sha1(data).hexdigest()
                path = image_paths.get(digest)
                if path is None:
                    path = f"{asset_dir}/{safe_stem}-p{pno + 1}-{n_images}.{ext}"
                    image_paths[digest] = path
                    assets.append(Asset(path, data, f"image/{ext}"))
                page_md.append(f"![{alt}]({path})")
                continue

            page_md.extend(_render_text_block(el, renderer, toc_titles))

        n_headings += sum(1 for chunk in page_md if chunk.startswith("#"))

        if page_md:
            if opt.page_comment:
                out.append(f"<!-- page {pno + 1} -->")
            out.extend(page_md)
        if opt.page_separator and pno < doc.page_count - 1:
            out.append("---")

    doc.close()

    markdown = "\n\n".join(chunk for chunk in out if chunk.strip())
    markdown = _tighten_lists(re.sub(r"\n{3,}", "\n\n", markdown)).strip() + "\n"

    return Result(
        markdown=markdown,
        assets=assets,
        asset_dir=asset_dir if assets else "",
        warnings=warnings,
        stats={
            "pages": len(page_dicts),
            "tables": n_tables,
            "images": n_images,
            "headings": n_headings,
            "chars": len(markdown),
            "body_size": body_size,
        },
    )


def _code_block_body(lines: list[Line]) -> str:
    """코드 블록 본문 — 들여쓰기를 살린다.

    공백을 정규화해 버리면 코드의 계단 구조가 사라진다. 원문에 공백이 없으면
    각 줄의 x좌표 차이를 글자 폭으로 나눠 들여쓰기를 복원한다.
    """
    base_x = min(l.bbox[0] for l in lines)
    sizes = [l.size for l in lines if l.size]
    char_w = max(1.0, (sum(sizes) / len(sizes) if sizes else 10.0) * 0.6)

    out: list[str] = []
    for line in lines:
        raw = line.text.rstrip()
        if not raw.strip():
            out.append("")
            continue
        if raw[:1].isspace():
            out.append(raw)
        else:
            pad = max(0, int(round((line.bbox[0] - base_x) / char_w)))
            out.append(" " * pad + raw)
    return "\n".join(out)


def _render_text_block(el: Element, r: _Renderer, toc_titles: list[tuple[int, str]]) -> list[str]:
    """텍스트 블록 하나를 Markdown 조각 목록으로 바꾼다."""
    chunks: list[str] = []

    # 줄 간격 중앙값 — 문단 분리 기준
    gaps: list[float] = []
    for prev, cur in zip(el.lines, el.lines[1:]):
        gaps.append(max(0.0, cur.bbox[1] - prev.bbox[3]))
    gaps_sorted = sorted(g for g in gaps if g >= 0)
    median_gap = gaps_sorted[len(gaps_sorted) // 2] if gaps_sorted else 0.0

    # 코드 블록: 블록 전체가 고정폭 글꼴
    if el.lines and all(l.all_mono for l in el.lines) and len(el.lines) > 1:
        return [f"```\n{_code_block_body(el.lines)}\n```"]

    pending: list[tuple[Line, str]] = []
    pending_prefix = ""

    def flush() -> None:
        nonlocal pending, pending_prefix
        if not pending:
            return
        text = r.join_lines(pending)
        if text:
            chunks.append(pending_prefix + text if pending_prefix else _escape_leading(text))
        pending = []
        pending_prefix = ""

    prev_line: Line | None = None
    for line in el.lines:
        text = _norm_ws(line.text)
        if not text:
            continue

        # 1) 북마크(TOC) 제목 우선
        level = None
        for lvl, title in toc_titles:
            if title and (text == title or (len(title) > 6 and text.startswith(title))):
                level = lvl
                break
        # 2) 글자 크기 기반
        if level is None:
            level = r.heading_level(line)

        if level is not None:
            flush()
            inline = _strip_outer_emphasis(r.render_inline(line.spans)).strip()
            if inline:
                chunks.append("#" * level + " " + inline)
            prev_line = line
            continue

        marker = r.list_marker(text)
        if marker is not None:
            flush()
            bullet, raw_marker, rest = marker
            indent = "  " * r.indent_level(line.bbox[0])
            # 마커 글자를 span 목록에서 잘라낸다
            trimmed = _strip_marker_spans(line.spans, raw_marker)
            inline = r.render_inline(trimmed) or escape_md(_norm_ws(rest))
            pending_prefix = f"{indent}{bullet} "
            pending = [(line, inline)]
            prev_line = line
            continue

        # 문단 분리: 줄 간격이 눈에 띄게 벌어지면 새 문단
        if prev_line is not None and median_gap > 0:
            gap = line.bbox[1] - prev_line.bbox[3]
            if gap > max(median_gap * 1.8, median_gap + line.size * 0.6):
                flush()

        inline = r.render_inline(line.spans)
        if inline:
            pending.append((line, inline))
        prev_line = line

    flush()
    return [c for c in chunks if c.strip()]


def _strip_marker_spans(spans: list[Span], marker: str) -> list[Span]:
    """목록 마커(예: "•", "1)")를 span 목록 앞부분에서 걷어낸 사본을 돌려준다.

    마커 판정은 공백을 정규화한 문자열로 하지만 span 안의 원문에는 공백이 그대로
    남아 있다. 글자 수로 자르면 어긋나므로, 공백을 건너뛰며 마커 글자만 지운다.
    """
    wanted = [ch for ch in marker if not ch.isspace()]
    out: list[Span] = []
    done = not wanted

    for sp in spans:
        if done:
            out.append(sp)
            continue
        kept = []
        for idx, ch in enumerate(sp.text):
            if done:
                kept.append(sp.text[idx:])
                break
            if ch.isspace():
                continue
            if wanted and ch == wanted[0]:
                wanted.pop(0)
                if not wanted:
                    done = True
                continue
            # 예상과 다른 글자를 만나면 자르기를 중단한다(안전)
            done = True
            kept.append(sp.text[idx:])
            break
        rest = "".join(kept)
        if rest.strip():
            clone = Span(**sp.__dict__)
            clone.text = rest
            out.append(clone)

    return out or spans


def convert_to_zip_entries(result: Result, md_name: str) -> Iterable[tuple[str, bytes]]:
    yield md_name, result.markdown.encode("utf-8")
    for asset in result.assets:
        yield asset.name, asset.data


def markdown_bytes(result: Result) -> bytes:
    return result.markdown.encode("utf-8")


def make_zip(items: Iterable[tuple[str, bytes]]) -> bytes:
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in items:
            zf.writestr(name, data)
    return buf.getvalue()
