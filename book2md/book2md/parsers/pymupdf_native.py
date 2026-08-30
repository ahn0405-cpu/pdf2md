"""PyMuPDF 좌표·색상 파서 (§3.2 권장 파서).

마크다운만 뱉는 도구와 달리 span 단위로 색·좌표·글자크기를 함께 받는다.
이 프로젝트가 지키기로 한 것들 중 셋이 여기서만 사실로 확인된다.

  · 강조색(§2.4)  : span 색이 유채색이면 ==…== 로 감싼다. 검정 볼드는 **…**
  · 옆번호(§4.3)  : 우측 여백 x좌표에 있는 sE-8 을 본문에서 떼어낸다.
                    이걸 안 하면 sE-8 + '1.' 이 붙어 sE-81 이 된다.
  · 각주(§2.5)    : 아래쪽에서 본문보다 작은 글자 덩어리 + 위첨자 숫자
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterator

from ..color import ImageColorSampler, Palette, is_black, to_rgb
from ..model import Line, Page
from .base import Parser

_BOLD_FLAG = 1 << 4
_DIGITS = re.compile(r"^\d{1,4}$")


class PyMuPDFParser(Parser):
    name = "pymupdf"
    layout_aware = True
    install_hint = "pip install PyMuPDF"

    def __init__(self):
        self.palette: Palette | None = None
        self.stats = Counter()
        self.keep_sidenotes = False
        self.color_source = "span"

    def available(self):
        try:
            import pymupdf  # noqa: F401
        except Exception as exc:
            try:
                import fitz  # noqa: F401
            except Exception:
                return False, f"import 실패: {exc}"
        return True, ""

    @staticmethod
    def _mod():
        try:
            import pymupdf
            return pymupdf
        except Exception:                       # pragma: no cover
            import fitz
            return fitz

    def page_count(self, pdf_path: str) -> int:
        with self._mod().open(pdf_path) as doc:
            return doc.page_count

    # ── 본문 글자 크기 ───────────────────────────────────────────
    def _body_size(self, doc, sample) -> float:
        tally: Counter = Counter()
        for i in sample:
            for block in doc[i].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span["text"].strip()
                        if txt:
                            tally[round(span["size"] * 2) / 2] += len(txt)
        return tally.most_common(1)[0][0] if tally else 10.0

    # ── 본체 ────────────────────────────────────────────────────
    def parse(self, pdf_path, pages, profile) -> Iterator[Page]:
        self.require()
        cfg = profile.get("_config", {})
        pres = cfg.get("preserve", {})
        fn = pres.get("footnote", {})
        color_cfg = pres.get("color", {})
        legend = cfg.get("legend", {})
        side_cfg = legend.get("sidenote", {})

        self.palette = Palette(cfg=color_cfg)
        want_emphasis = bool(profile.get("emphasis", True)) and bool(color_cfg)
        side_mode = str(side_cfg.get("mode", "drop")).lower()
        want_sidenote = bool(profile.get("sidenote", False)) and side_mode != "off"
        self.keep_sidenotes = side_mode == "keep"
        side_rx = re.compile(side_cfg.get("pattern", r"^s[A-Z]-\d{1,3}$"))
        side_inline = re.compile(r"s[A-Z]-\d{1,3}")
        margin_ratio = float(side_cfg.get("margin_ratio", 0.78))

        ex = cfg.get("extract", {})
        opts = dict(
            space_gap=float(ex.get("space_gap_ratio", 0.18)),
            merge_overlap=float(ex.get("line_merge_overlap", 0.55)),
            merge_gap=float(ex.get("line_merge_max_gap", 0.06)),
            footer_zone=float(cfg.get("running", {}).get("footer_zone", 0.94)),
            footer_rx=[re.compile(x) for x in
                       cfg.get("running", {}).get("footer_patterns", [])],
            size_ratio=float(fn.get("size_ratio", 0.92)),
            bottom_zone=float(fn.get("bottom_zone", 0.42)),
            sup_ratio=float(fn.get("superscript_size_ratio", 0.82)),
            sup_rise=float(fn.get("superscript_rise", 0.12)),
            header_zone=float(cfg.get("running", {}).get("header_zone", 0.08)),
        )

        with self._mod().open(pdf_path) as doc:
            idx = list(range(doc.page_count)) if pages is None else \
                [i for i in pages if 0 <= i < doc.page_count]
            step = max(1, len(idx) // 20)
            body_size = self._body_size(doc, idx[::step][:20] or idx[:1])
            self.color_source = self._pick_color_source(doc, idx, color_cfg) \
                if want_emphasis else "none"
            # 머리말·꼬리말은 책 전체의 성질이다. --pages 로 잘라 돌릴 때도
            # 문서 전체에서 찾아야 한다. 열한 쪽만 보면 그 안에 두어 번밖에
            # 안 나오는 장 꼬리말을 못 잡고, 그게 장 제목으로 둔갑한다.
            opts["running"] = self._detect_running(
                doc, list(range(doc.page_count)), cfg.get("running", {}))

            for i in idx:
                page = doc[i]
                rect = page.rect
                sampler = ImageColorSampler(page, color_cfg) \
                    if self.color_source == "image" else None
                lines, sidenotes = self._page_lines(
                    page, body_size, opts, color_cfg, want_emphasis,
                    want_sidenote, side_rx, side_inline,
                    rect.width * margin_ratio, i + 1, sampler)
                lines = _merge_same_line(lines, opts["merge_overlap"],
                                         rect.width * opts["merge_gap"])
                self._mark_zones(lines, rect.height, body_size, opts)
                ordered = self._order(lines, rect.width, profile.get("columns", "auto"))
                yield Page(number=i + 1, lines=ordered, width=rect.width,
                           height=rect.height, kind="layout", body_size=body_size,
                           sidenotes=sidenotes)

    # ── 되풀이되는 머리말·꼬리말 (§4.1) ──────────────────────────
    @staticmethod
    def _detect_running(doc, idx, cfg) -> set:
        """쪽마다 되풀이되는 위·아래 줄의 '모양'을 모은다.

        'CHAPTER 05 | 소송물 • 153' 은 쪽마다 숫자만 바뀐다. 절대 위치로 자르면
        쪽 크기가 다른 책에서 어긋나므로, 숫자를 뺀 모양이 되풀이되는지로 본다.
        이걸 안 하면 꼬리말이 장 제목으로 잡혀 문서가 통째로 어긋난다.
        """
        if not cfg.get("detect_repeating", True):
            return set()
        zone = float(cfg.get("repeat_zone", 0.12))
        sample = int(cfg.get("repeat_sample", 40))
        pages = idx[::max(1, len(idx) // sample)][:sample] or idx[:1]
        tally: Counter = Counter()
        for i in pages:
            page = doc[i]
            h = page.rect.height
            seen = set()
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    y0, y1 = line["bbox"][1], line["bbox"][3]
                    if y1 > h * zone and y0 < h * (1 - zone):
                        continue
                    text = "".join(sp["text"] for sp in line.get("spans", []))
                    key = _running_key(text)
                    if key and key not in seen:
                        seen.add(key)
                        tally[key] += 1
            # 표본 한 쪽에서 같은 모양이 두 번 나와도 한 번으로 센다
        need = max(2, int(len(pages) * float(cfg.get("repeat_min_ratio", 0.35))))
        return {k for k, n in tally.items() if n >= need}

    # ── 색을 어디서 읽을지 (§2.4) ────────────────────────────────
    def _pick_color_source(self, doc, idx, color_cfg) -> str:
        """span 색이냐 쪽 그림이냐.

        스캔본에 OCR 텍스트가 얹힌 PDF 는 글자 색이 전부 검정이다. 저자가 칠한
        강조는 그림 픽셀에만 남아 있으므로, span 에 유채색이 하나도 없으면
        그림에서 읽는다. 판단을 표본 몇 쪽으로 끝내 전체 비용을 아낀다.
        """
        source = str(color_cfg.get("source", "auto")).lower()
        if source in ("span", "image"):
            return source
        probe = idx[::max(1, len(idx) // 12)][:12] or idx[:1]
        for i in probe:
            for block in doc[i].get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if not span["text"].strip():
                            continue
                        if not is_black(to_rgb(span.get("color", 0)), color_cfg):
                            return "span"
        return "image"

    # ── 한 페이지의 줄 ───────────────────────────────────────────
    def _page_lines(self, page, body_size, opts, color_cfg, want_emphasis,
                    want_sidenote, side_rx, side_inline, margin_x, page_no,
                    sampler=None):
        out: list[Line] = []
        sidenotes: list[dict] = []
        for block in page.get_text("rawdict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if _span_text(s).strip()]
                if not spans:
                    continue
                _restore_spaces(spans, opts["space_gap"])
                # ⑩ 옆번호: 우측 여백에 있고 sE-8 꼴인 span 을 먼저 떼어낸다 (§4.3)
                if want_sidenote:
                    kept = []
                    for span in spans:
                        text = span["text"].strip()   # _restore_spaces 가 채워 둔다
                        if span["bbox"][0] >= margin_x and (
                                side_rx.match(text) or side_inline.fullmatch(text)):
                            if self.keep_sidenotes:
                                sidenotes.append({"text": text,
                                                  "y": round(span["bbox"][1], 1)})
                            self.stats["sidenote"] += 1
                            continue
                        kept.append(span)
                    spans = kept or spans
                    if not kept:
                        continue

                base = max(s["origin"][1] for s in spans)
                pieces, sups, sizes, bolds = [], [], [], []
                for span in spans:
                    raw = span["text"]
                    rgb = to_rgb(span.get("color", 0))
                    bold = bool(span["flags"] & _BOLD_FLAG) or "Bold" in span.get("font", "")
                    small = span["size"] < body_size * opts["sup_ratio"]
                    raised = base - span["origin"][1] > body_size * opts["sup_rise"]
                    if sampler is not None:
                        hexed, _ = sampler.classify(span["bbox"])
                        key = None
                        if hexed:
                            rgb = tuple(int(hexed[j:j + 2], 16) for j in (1, 3, 5))
                            key = self.palette.add(rgb, raw, page_no)
                        else:
                            self.palette.total_spans += 1
                    else:
                        key = self.palette.add(rgb, raw, page_no) if self.palette else None

                    if small and raised and _DIGITS.match(raw.strip()):
                        # 확실한 각주 참조. 그 자리에서 [^n] 로 박는다 (§2.5)
                        n = int(raw.strip())
                        pieces.append(("", f"[^{n}]"))
                        sups.append(n)
                        continue
                    mark = ""
                    if want_emphasis:
                        if key is not None:
                            mark = self.palette.markup_for(key)
                        elif bold and is_black(rgb, color_cfg):
                            mark = color_cfg.get("markup", {}).get("bold", "**")
                    pieces.append((mark, raw))
                    sizes.append(span["size"])
                    bolds.append(bold)

                text = _render(pieces)
                if not text.strip():
                    continue
                x0, y0, x1, y1 = line["bbox"]
                out.append(Line(
                    text=text.rstrip(),
                    size=round(max(sizes) if sizes else body_size, 2),
                    bold=bool(bolds) and all(bolds),
                    x0=round(x0, 1), y0=round(y0, 1), x1=round(x1, 1), y1=round(y1, 1),
                    sup_numbers=sups,
                ))
        return out, sidenotes

    # ── 머리말·각주 영역 ─────────────────────────────────────────
    def _mark_zones(self, lines, height, body_size, opts):
        """각주 영역은 아래에서 위로 올라가며 잡는다.

        본문 크기 줄을 만나면 거기서 끊는다. 그래야 본문 마지막 문단을
        각주로 잘못 삼키지 않는다.
        """
        if not lines:
            return
        running = opts.get("running") or set()
        zone = 0.12
        for line in lines:
            if line.y1 <= height * opts["header_zone"]:
                line.zone = "header"
            elif line.y0 >= height * (1 - zone) and \
                    any(rx.search(strip_markup(line.stripped)) for rx in opts["footer_rx"]):
                line.zone = "header"        # 꼬리말도 본문이 아니다 (§4.1)
            elif running and (line.y1 <= height * zone or line.y0 >= height * (1 - zone)) \
                    and _running_key(strip_markup(line.text)) in running:
                line.zone = "header"        # 쪽마다 되풀이되는 줄

        limit = height * (1.0 - opts["bottom_zone"])
        small = body_size * opts["size_ratio"]
        start = None
        for k in range(len(lines) - 1, -1, -1):
            line = lines[k]
            if line.zone == "header":
                continue            # 꼬리말은 건너뛴다. 여기서 멈추면 각주를 통째로 놓친다
            if line.y0 < limit or line.size >= small:
                break
            start = k
        if start is None:
            return
        if not re.match(r"^\d{1,4}\b", strip_markup(lines[start].stripped)):
            return          # 번호로 시작하지 않으면 각주가 아니다
        for line in lines[start:]:
            if line.zone != "header":
                line.zone = "footnote"

    # ── 읽는 순서 ────────────────────────────────────────────────
    def _order(self, lines, width, want):
        body = [l for l in lines if l.zone == "body"]
        two = want == 2 or (want in ("auto", None) and len(body) >= 8
                            and self._looks_two_column(body, width))
        if not two:
            return sorted(lines, key=lambda l: (l.zone == "footnote", round(l.y0, 1), l.x0))
        mid = width / 2
        for line in lines:
            line.column = 0 if l_center(line) < mid or line.zone != "body" else 1
        return sorted(lines, key=lambda l: (l.zone == "footnote", l.column,
                                            round(l.y0, 1), l.x0))

    @staticmethod
    def _looks_two_column(body, width) -> bool:
        mid, band = width / 2, width * 0.06
        crossing = sum(1 for l in body if l.x0 < mid - band and l.x1 > mid + band)
        left = sum(1 for l in body if l.x1 <= mid + band)
        right = sum(1 for l in body if l.x0 >= mid - band)
        n = len(body)
        return crossing <= n * 0.08 and left >= n * 0.25 and right >= n * 0.25


_MARKUP = re.compile(r"`|={2}|\*{2}")


def strip_markup(text: str) -> str:
    """우리가 넣은 강조 표시를 걷어낸 글자.

    색을 먼저 입히고 구조를 나중에 판단하기 때문에, 제목·꼬리말을 알아볼 때는
    표시를 걷어낸 글자로 봐야 한다. `==IV. 시효중단==` 이 제목으로 안 걸리면
    문서 전체가 평평해진다.
    """
    return _MARKUP.sub("", text)


def l_center(line) -> float:
    return (line.x0 + line.x1) / 2


def _span_text(span) -> str:
    """rawdict 의 span 은 글자 목록으로 온다."""
    if "text" in span:
        return span["text"]
    return "".join(c["c"] for c in span.get("chars", []))


def _restore_spaces(spans, gap_ratio: float) -> None:
    """글자 사이가 벌어진 곳에 공백을 넣고 span['text'] 를 채운다.

    스캔본 OCR 레이어는 낱말 사이 공백을 글자로 넣어 주지 않는다. 그대로 두면
    '수량적가분채권을분할청구하는것을말한다' 가 되어 뒤 처리가 못 읽는다.
    글자 상자의 가로 간격이 글자 크기에 견줘 벌어졌으면 낱말 경계로 본다.
    """
    if gap_ratio <= 0:
        for span in spans:
            span["text"] = _span_text(span)
        return
    prev_x1 = None
    prev_size = 0.0
    for span in spans:
        chars = span.get("chars")
        if not chars:
            span["text"] = _span_text(span)
            prev_x1, prev_size = span.get("bbox", (0, 0, 0, 0))[2], span.get("size", 0)
            continue
        out = []
        for ch in chars:
            x0, _, x1, _ = ch["bbox"]
            size = span.get("size", prev_size) or prev_size
            if (prev_x1 is not None and ch["c"] != " " and out[-1:] != [" "]
                    and x0 - prev_x1 > size * gap_ratio):
                out.append(" ")
            out.append(ch["c"])
            prev_x1, prev_size = x1, size
        span["text"] = "".join(out)


def _merge_same_line(lines, overlap: float, max_gap: float = 1e9):
    """세로로 겹치는 줄을 한 줄로 잇는다.

    OCR 은 한 줄 안에서도 글자 크기가 다르면 따로 떨궈 놓는다.
        y=331 x=75  '.判例[일외별명일]'
        y=332 x=60  '3'
    이대로면 '3.判例' 라는 제목이 영영 안 만들어진다. 세로 범위가 충분히
    겹치는 것들을 모아 x 순서로 잇는다.
    """
    if overlap <= 0 or len(lines) < 2:
        return lines
    rows = sorted(lines, key=lambda l: (round(l.y0, 1), l.x0))
    groups: list[list] = []
    for line in rows:
        placed = False
        for group in reversed(groups[-3:]):
            ref = group[0]
            lo = max(ref.y0, line.y0)
            hi = min(ref.y1, line.y1)
            span = min(ref.y1 - ref.y0, line.y1 - line.y0)
            if span > 0 and (hi - lo) / span >= overlap and ref.zone == line.zone:
                group.append(line)
                placed = True
                break
        if not placed:
            groups.append([line])

    merged: list = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda l: l.x0)
        # 가로로 멀리 떨어진 조각은 같은 줄이라도 다른 것이다. 여백에 찍힌
        # 장식 글자가 제목에 들러붙는 것을 막는다.
        kept, dropped = [group[0]], []
        for nxt in group[1:]:
            if nxt.x0 - kept[-1].x1 > max_gap:
                dropped.append(nxt)
            else:
                kept.append(nxt)
        merged.extend(dropped)
        group = kept
        head = group[0]
        text = head.text
        for nxt in group[1:]:
            text = _join_pieces(text, nxt.text,
                                nxt.x0 - _prev_x1(group, nxt) > 1.0)
        head.text = text
        head.x1 = max(l.x1 for l in group)
        head.y0 = min(l.y0 for l in group)
        head.y1 = max(l.y1 for l in group)
        head.size = max(l.size for l in group)
        head.bold = all(l.bold for l in group)
        head.sup_numbers = [n for l in group for n in l.sup_numbers]
        merged.append(head)
    return sorted(merged, key=lambda l: (l.zone == "footnote", round(l.y0, 1), l.x0))


#: 글자만 남긴다. OCR 이 쪽번호를 ']6!' 처럼 흘려 놓아 숫자만 빼서는
#: 'CHAPTER 06 | 소송절차 개시 - ]6!' 이 쪽마다 다른 모양이 된다.
_RUNNING_KEEP = re.compile(r"[^0-9A-Za-z가-힣一-鿿]+")


def _running_key(text: str) -> str:
    """쪽번호·장식을 뺀 모양. 쪽마다 되풀이되는 줄을 한 덩어리로 묶는다."""
    key = _RUNNING_KEEP.sub("", strip_markup(text or ""))
    key = re.sub(r"\d+", "", key)
    return key if len(key) >= 4 else ""


def _join_pieces(head: str, tail: str, gap: bool) -> str:
    """번호 조각과 제목 조각을 잇는다.

    '3' 과 '.判例' 는 인쇄상 붙어 있는데 OCR 이 둘로 떨궈 놓는다. 사이가
    벌어졌다고 공백을 넣으면 '3 . 判例' 가 되어 번호 무늬가 깨진다.
    """
    if not head:
        return tail.strip()
    a, b = strip_markup(head).rstrip(), strip_markup(tail).lstrip()
    glue = gap
    if b[:1] in ".)]" and (a[-1:].isdigit() or a[-1:] in "IVXivx"):
        glue = False
    return (head + (" " if glue else "") + tail).strip()


def _prev_x1(group, target) -> float:
    prev = None
    for line in group:
        if line is target:
            break
        prev = line
    return prev.x1 if prev else target.x0


def _render(pieces) -> str:
    """같은 마크업이 이어지는 span 을 한 덩어리로 묶는다.

    span 마다 ==…== 를 두르면 '==청==구==취지==' 처럼 쪼개져 뒤 처리가 깨진다.
    """
    out, run_mark, run_text = [], "", ""

    def flush():
        nonlocal run_mark, run_text
        if not run_text:
            return
        if run_mark:
            head = run_text[:len(run_text) - len(run_text.lstrip())]
            tail = run_text[len(run_text.rstrip()):]
            core = run_text.strip()
            out.append(f"{head}{run_mark}{core}{run_mark}{tail}" if core else run_text)
        else:
            out.append(run_text)
        run_mark, run_text = "", ""

    for mark, text in pieces:
        if mark == run_mark:
            run_text += text
        else:
            flush()
            run_mark, run_text = mark, text
    flush()
    return "".join(out)
