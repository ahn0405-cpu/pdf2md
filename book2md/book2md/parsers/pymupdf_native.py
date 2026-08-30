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
            footer_gap_ratio=float(cfg.get("running", {}).get("footer_gap_ratio", 1.8)),
            repeat_zone=float(cfg.get("running", {}).get("repeat_zone", 0.12)),
            band_max_len=int(cfg.get("running", {}).get("band_max_len", 40)),
            band_max_hangul=int(cfg.get("running", {}).get("band_max_hangul", 5)),
            strip_small_in_band=bool(cfg.get("running", {}).get(
                "strip_small_in_band", True)),
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
                if want_sidenote:
                    lines, more = _pull_sidenote_lines(
                        lines, side_rx, self.keep_sidenotes,
                        rect.width * margin_ratio)
                    sidenotes.extend(more)
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
                        # 버릴 때는 자리를 가리지 않는다. 여백에서 벗어난 옆번호가
                        # 본문에 섞이면 붙은 글자만큼 참조가 바뀐다(§4.3).
                        # 남길 때는 여백에 있는 것만 — 본문 속 같은 꼴을 뺏지 않도록.
                        at_margin = span["bbox"][0] >= margin_x
                        if (at_margin or not self.keep_sidenotes) and (
                                side_rx.match(text) or side_inline.fullmatch(text)):
                            # 안 쓸 때도 무엇을 뺐는지는 남긴다 (§P2-1).
                            sidenotes.append({"text": text,
                                              "y": round(span["bbox"][1], 1),
                                              "kept": bool(self.keep_sidenotes)})
                            self.stats["sidenote"] += 1
                            continue
                        kept.append(span)
                    spans = kept or spans
                    if not kept:
                        continue

                base = max(s["origin"][1] for s in spans)
                pieces, sups, sizes, bolds = [], [], [], []
                #: 그림에서 색을 읽을 때 줄 안의 낱말 판정을 모아 둔다 (§P0-2).
                words: list[list] = []
                for span in spans:
                    raw = span["text"]
                    rgb = to_rgb(span.get("color", 0))
                    bold = bool(span["flags"] & _BOLD_FLAG) or "Bold" in span.get("font", "")
                    small = span["size"] < body_size * opts["sup_ratio"]
                    raised = base - span["origin"][1] > body_size * opts["sup_rise"]
                    if small and raised and _DIGITS.match(raw.strip()):
                        # 확실한 각주 참조. 그 자리에서 [^n] 로 박는다 (§2.5)
                        n = int(raw.strip())
                        pieces.append(("", f"[^{n}]"))
                        sups.append(n)
                        continue

                    if sampler is not None:
                        # 그림에서 색을 읽을 때는 **낱말마다** 판정한다 (§P0-2).
                        # span 은 OCR 이 멋대로 끊어 놓은 덩어리라 강조 한 낱말이
                        # 문장 전체를 물들이거나, 반대로 평균에 묻혀 사라진다.
                        # 이 모드에서는 bold·크기를 판정에 쓰지 않는다 — 스캔본의
                        # 글자 속성은 OCR 이 지어낸 것이라 근거가 못 된다.
                        for seg, box in (span.get("_segs") or [(raw, span["bbox"])]):
                            if box is None or not seg.strip():
                                pieces.append(("", seg))
                                continue
                            hexed, ratio, weak = sampler.classify(box)
                            pieces.append(("", seg))
                            words.append([len(pieces) - 1, seg, hexed, ratio, weak,
                                          sampler.density(box)])
                    else:
                        key = self.palette.add(rgb, raw, page_no) if self.palette else None
                        mark = ""
                        if want_emphasis:
                            if key is not None:
                                mark = self.palette.markup_for(key)
                            elif bold and is_black(rgb, color_cfg):
                                mark = color_cfg.get("markup", {}).get("bold", "**")
                        pieces.append((mark, raw))
                    sizes.append(span["size"])
                    bolds.append(bold)

                if words:
                    self._settle_words(words, pieces, page_no, want_emphasis,
                                       color_cfg)
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

    def _settle_words(self, words, pieces, page_no, want_emphasis,
                      color_cfg) -> None:
        """줄 안의 낱말 판정을 확정한다 (§P0-2).

        ① 색. 낱말마다 따로 재면 같은 구절인데도 획이 얇은 낱말, 한두 글자짜리
        낱말이 문턱을 못 넘어 누더기가 된다. 저자는 낱말이 아니라 **구절**을
        칠했으므로, 확실한 낱말 사이에 낀 애매한 낱말은 같은 구절로 본다.
        확실한 낱말이 하나도 없는 줄에서는 애매한 낱말을 살리지 않는다.

        ② 굵기. 이 교재의 본문 강조는 **검정 굵은 글씨**다(청색은 제목과
        두문자에만 쓴다). 스캔본이라 OCR 이 붙여 준 글꼴 속성은 못 쓰므로,
        그림에서 잰 잉크 밀도를 같은 줄의 가운뎃값과 견준다. 줄이 짧으면
        가운뎃값을 믿을 수 없어 굵기를 판정하지 않는다 — 없는 강조를 지어내는
        것이 놓치는 것보다 나쁘다.
        """
        strong = [k for k, w in enumerate(words) if w[2]]
        if strong:
            lo, hi = strong[0], strong[-1]
            for k in range(lo, hi + 1):
                w = words[k]
                if not w[2] and w[4]:
                    # 확실한 낱말 사이에 낀 애매한 낱말 — 같은 구절로 본다
                    w[2] = w[4]

        bold_mark = ""
        if want_emphasis and color_cfg.get("bold_from_image", True):
            bold_mark = color_cfg.get("markup", {}).get("bold", "**")
        heavy = set()
        if bold_mark:
            body = [w for w in words if len(w[1].strip()) >= 2 and w[5] > 0]
            if len(body) >= int(color_cfg.get("bold_min_words", 6)):
                dens = sorted(w[5] for w in body)
                mid = dens[len(dens) // 2]
                cut = mid * float(color_cfg.get("bold_density_ratio", 1.22))
                heavy = {id(w) for w in body if w[5] >= cut}

        for w in words:
            idx, seg, hexed = w[0], w[1], w[2]
            if hexed:
                rgb = tuple(int(hexed[j:j + 2], 16) for j in (1, 3, 5))
                key = self.palette.add(rgb, seg, page_no)
            else:
                key = None
                self.palette.total_spans += 1
            if want_emphasis and key is not None:
                mark = self.palette.markup_for(key)
            elif id(w) in heavy:
                mark = bold_mark
            else:
                mark = ""
            pieces[idx] = (mark, seg)

    # ── 머리말·각주 영역 ─────────────────────────────────────────
    def _mark_zones(self, lines, height, body_size, opts):
        """머리말·꼬리말·각주 영역을 가른다.

        **읽는 순서(y)로 세워 놓고** 본다. rawdict 가 주는 차례는 조판 순서라
        위아래가 뒤섞여 있다. 그대로 아래에서 위로 훑으면 엉뚱한 줄을 각주
        첫 줄로 잡는다.
        """
        if not lines:
            return
        ordered = sorted(lines, key=lambda l: (round(l.y0, 1), l.x0))
        running = opts.get("running") or set()
        zone = float(opts.get("repeat_zone", 0.12))
        small = body_size * opts["size_ratio"]
        band_len = int(opts.get("band_max_len", 40))
        top_id = id(ordered[0])

        for line in ordered:
            if line.y1 <= height * opts["header_zone"]:
                line.zone = "header"
                continue
            # 위·아래 띠, 그리고 쪽의 첫 줄·끝 줄. 장 제목 띠는 책마다 위에
            # 오기도 하고 아래 오기도 하며, 여백이 넉넉한 쪽에서는 띠를
            # 벗어나 앉는다. 자리(첫 줄·끝 줄)로도 함께 본다.
            at_top = line.y1 <= height * zone or id(line) == top_id
            in_band = at_top or line.y0 >= height * (1 - zone)
            # 되풀이 지문은 자리를 가리지 않는다. OCR 이 앞뒤에 잡글자를 붙여
            # 놓아도('O과 nr CHAPTER 6 소송절차 개시 nr“') 지문이 그 안에
            # 들어 있으면 머리말이다. 다만 **본문보다 작을 때만** — 진짜
            # 장 제목('CHAPTER 05 소송물')은 본문보다 크다.
            if (not in_band and running and line.size < small
                    and _running_inside(strip_markup(line.stripped), running)):
                line.zone = "header"
                continue
            if not in_band:
                continue
            plain = strip_markup(line.stripped)
            if any(rx.search(plain) for rx in opts["footer_rx"]):
                line.zone = "header"        # 머리말·꼬리말은 본문이 아니다 (§4.1)
            elif running and _running_key(plain) in running:
                line.zone = "header"        # 쪽마다 되풀이되는 줄
            elif (opts.get("strip_small_in_band", True)
                  and line.size < small and len(plain) <= band_len
                  and not _HEADING_LIKE.match(plain)
                  and not _FOOTNOTE_LIKE.match(plain)
                  and (at_top or len(_HANGUL.findall(plain))
                       <= int(opts.get("band_max_hangul", 5)))):
                # 쪽 맨 위의 작고 짧은 줄. OCR 이 쪽마다 다르게 흘려 놓아
                # ('O과 己厂—I !') 무늬로도 되풀이로도 못 잡는다. 본문은 이 자리에
                # 이렇게 작고 짧게 서지 않는다.
                #
                # 아래 띠에서는 한글이 거의 없을 때만 쓴다. 아래는 각주가
                # 차지하고 있어서, 그냥 쓰면 '262) 소유권 확인의 소에서…' 같은
                # 각주와 여러 줄로 이어지는 각주의 뒷줄을 통째로 버린다.
                # 각주 뒷줄은 읽히는 한국어고, OCR 이 흘린 꼬리말은 아니다.
                line.zone = "header"

        limit = height * (1.0 - opts["bottom_zone"])
        start = None
        for k in range(len(ordered) - 1, -1, -1):
            line = ordered[k]
            if line.zone == "header":
                continue            # 꼬리말은 건너뛴다. 여기서 멈추면 각주를 통째로 놓친다
            if line.y0 < limit or line.size >= small:
                break
            start = k
        if start is None:
            return
        start = self._strip_tail_footer(ordered, start, height, opts)
        if start is None:
            return
        if not re.match(r"^\d{1,4}\b", strip_markup(ordered[start].stripped)):
            return          # 번호로 시작하지 않으면 각주가 아니다
        for line in ordered[start:]:
            if line.zone != "header":
                line.zone = "footnote"

    @staticmethod
    def _strip_tail_footer(lines, start, height, opts):
        """각주 아래에 남은 줄을 꼬리말로 떼어낸다 (§4.1).

        이 책은 [본문] → [가로선] → [각주] → [꼬리말] 순이다. 무늬로 잡으려
        하면 못 잡는다 — OCR 이 'O과 nr CHAPTER 6 소송절차 개시' 나
        'O과 己厂—I !' 처럼 쪽마다 다르게 흘려 놓기 때문이다.

        가르는 것은 **세로 간격**이다. 각주는 줄간격으로 촘촘히 붙어 있고,
        꼬리말은 그 아래로 한참 떨어져 있다. 각주 번호로 시작하지 않는다는
        것만으로 떼면 여러 줄로 이어지는 긴 각주의 뒷줄을 통째로 버린다.
        """
        tail = [k for k in range(start, len(lines)) if lines[k].zone != "header"]
        if len(tail) < 2:
            return start
        gaps = [lines[b].y0 - lines[a].y0 for a, b in zip(tail, tail[1:])]
        gaps = [g for g in gaps if g > 0]
        if not gaps:
            return start
        # 중앙값이 아니라 아래쪽 4분위를 쓴다. 각주가 한두 줄뿐인 쪽에서는
        # 꼬리말까지의 큰 간격이 중앙값을 끌어올려 제 발등을 찍는다.
        typical = sorted(gaps)[max(0, len(gaps) // 4)]
        cut = float(opts.get("footer_gap_ratio", 1.8))
        k = len(tail) - 1
        while k > 0:
            last, prev = lines[tail[k]], lines[tail[k - 1]]
            if last.y0 - prev.y0 <= typical * cut:
                break                    # 각주와 붙어 있다 — 각주의 뒷줄이다
            if re.match(r"^\d{1,4}\b", strip_markup(last.stripped)):
                break                    # 번호로 시작하면 각주다
            last.zone = "header"
            k -= 1
        while start < len(lines) and lines[start].zone == "header":
            start += 1
        return start if start < len(lines) else None

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

    덤으로 span['_segs'] 에 낱말 단위 조각을 (글자, 상자) 로 남긴다. 색을
    그림에서 읽을 때 span 통째로 판정하면 한 문장에 강조가 한 낱말만 섞여도
    문장 전체가 강조가 되거나 통째로 날아간다 (§P0-2).
    """
    if gap_ratio <= 0:
        for span in spans:
            span["text"] = _span_text(span)
            span["_segs"] = _segments(_char_pairs(span))
        return
    prev_x1 = None
    prev_size = 0.0
    for span in spans:
        chars = span.get("chars")
        if not chars:
            span["text"] = _span_text(span)
            span["_segs"] = _segments(_char_pairs(span))
            prev_x1, prev_size = span.get("bbox", (0, 0, 0, 0))[2], span.get("size", 0)
            continue
        out = []
        for ch in chars:
            x0, _, x1, _ = ch["bbox"]
            size = span.get("size", prev_size) or prev_size
            if (prev_x1 is not None and ch["c"] != " " and out[-1:] != [(" ", None)]
                    and x0 - prev_x1 > size * gap_ratio):
                out.append((" ", None))
            out.append((ch["c"], ch["bbox"]))
            prev_x1, prev_size = x1, size
        span["text"] = "".join(c for c, _ in out)
        span["_segs"] = _segments(out)


def _char_pairs(span) -> list[tuple[str, tuple | None]]:
    chars = span.get("chars")
    if chars:
        return [(c["c"], c["bbox"]) for c in chars]
    return [(ch, span.get("bbox")) for ch in _span_text(span)]


def _segments(pairs) -> list[tuple[str, tuple | None]]:
    """(글자, 상자) 목록을 낱말/공백 덩어리로 묶는다.

    공백 덩어리의 상자는 None 이다 — 색을 읽을 것이 없다.
    """
    segs: list[tuple[str, tuple | None]] = []
    buf: list[str] = []
    box: list[float] | None = None
    space = None
    for ch, bbox in pairs:
        blank = not ch.strip()
        if space is not None and blank != space:
            segs.append(("".join(buf), tuple(box) if box else None))
            buf, box = [], None
        space = blank
        buf.append(ch)
        if not blank and bbox:
            if box is None:
                box = list(bbox)
            else:
                box[0] = min(box[0], bbox[0])
                box[1] = min(box[1], bbox[1])
                box[2] = max(box[2], bbox[2])
                box[3] = max(box[3], bbox[3])
    if buf:
        segs.append(("".join(buf), tuple(box) if box else None))
    return segs


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


#: 띠 안에 있어도 제목 꼴이면 남긴다. 논점 번호('046 일부청구')가 쪽 맨 위에
#: 오는 일이 있다.
_HEADING_LIKE = re.compile(
    r"^\s*(?:\d{3}\s|CHAPTER\s*\d|제\s*\d+\s*[편장절관]|[IVX]{1,5}\s*[.)])")

#: 각주는 절대 머리말로 보면 안 된다.
_FOOTNOTE_LIKE = re.compile(r"^\s*\d{1,4}\s*[).\]]")

_HANGUL = re.compile(r"[가-힣]")


def _running_inside(text: str, running: set, min_len: int = 6) -> bool:
    """되풀이 지문이 이 줄 안에 들어 있는가.

    OCR 은 머리말 앞뒤에 잡글자를 붙인다. 정확히 같기를 요구하면 쪽마다
    다르게 흘러나온 것을 하나도 못 잡는다. 짧은 지문은 본문에도 우연히
    들어갈 수 있으므로 길이를 요구한다.
    """
    key = _running_key(text)
    if not key:
        return False
    return any(len(r) >= min_len and r in key for r in running)


def _running_key(text: str) -> str:
    """쪽번호·장식을 뺀 모양. 쪽마다 되풀이되는 줄을 한 덩어리로 묶는다."""
    key = _RUNNING_KEEP.sub("", strip_markup(text or ""))
    key = re.sub(r"\d+", "", key)
    return key if len(key) >= 4 else ""


def _pull_sidenote_lines(lines, side_rx, keep: bool, margin_x: float):
    """줄 전체가 옆번호인 것을 떼어낸다.

    span 이 'sO', '-', '13' 으로 쪼개져 오면 span 단위 검사가 놓친다. 줄로
    합쳐진 뒤에 한 번 더 본다. 안 떼면 본문에 남아 §4.3 의 사고가 난다.
    """
    kept, pulled = [], []
    for line in lines:
        text = strip_markup(line.stripped)
        if side_rx.match(text) and (not keep or line.x0 >= margin_x):
            if keep:
                pulled.append({"text": text, "y": line.y0})
            continue
        kept.append(line)
    return kept, pulled


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

    # 낱말마다 색을 읽으면 강조 사이에 공백 조각이 낀다 (§P0-2). 공백만으로
    # 덩어리를 끊으면 '==확장의== ==뜻을==' 이 되므로, 공백은 붙들어 두었다가
    # 앞뒤 마크업이 같을 때만 덩어리 안으로 넣는다.
    pending = ""
    for mark, text in pieces:
        if not text:
            continue
        if not text.strip():
            pending += text
            continue
        if mark == run_mark:
            run_text += pending + text
        else:
            flush()
            if pending:
                out.append(pending)
            run_mark, run_text = mark, text
        pending = ""
    flush()
    if pending:
        out.append(pending)
    return "".join(out)
