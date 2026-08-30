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
        want_sidenote = bool(profile.get("sidenote", False))
        side_rx = re.compile(side_cfg.get("pattern", r"^s[A-Z]-\d{1,3}$"))
        side_inline = re.compile(r"s[A-Z]-\d{1,3}")
        margin_ratio = float(side_cfg.get("margin_ratio", 0.78))

        opts = dict(
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

            for i in idx:
                page = doc[i]
                rect = page.rect
                sampler = ImageColorSampler(page, color_cfg) \
                    if self.color_source == "image" else None
                lines, sidenotes = self._page_lines(
                    page, body_size, opts, color_cfg, want_emphasis,
                    want_sidenote, side_rx, side_inline,
                    rect.width * margin_ratio, i + 1, sampler)
                self._mark_zones(lines, rect.height, body_size, opts)
                ordered = self._order(lines, rect.width, profile.get("columns", "auto"))
                yield Page(number=i + 1, lines=ordered, width=rect.width,
                           height=rect.height, kind="layout", body_size=body_size,
                           sidenotes=sidenotes)

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
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s["text"].strip()]
                if not spans:
                    continue
                # ⑩ 옆번호: 우측 여백에 있고 sE-8 꼴인 span 을 먼저 떼어낸다 (§4.3)
                if want_sidenote:
                    kept = []
                    for span in spans:
                        text = span["text"].strip()
                        if span["bbox"][0] >= margin_x and (
                                side_rx.match(text) or side_inline.fullmatch(text)):
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
        for line in lines:
            if line.y1 <= height * opts["header_zone"]:
                line.zone = "header"

        limit = height * (1.0 - opts["bottom_zone"])
        small = body_size * opts["size_ratio"]
        start = None
        for k in range(len(lines) - 1, -1, -1):
            line = lines[k]
            if line.zone == "header" or line.y0 < limit or line.size >= small:
                break
            start = k
        if start is None:
            return
        if not re.match(r"^\d{1,4}\b", lines[start].stripped):
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


def l_center(line) -> float:
    return (line.x0 + line.x1) / 2


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
