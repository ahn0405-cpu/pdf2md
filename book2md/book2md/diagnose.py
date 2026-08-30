"""사전 진단 (§3.1). 변환 전에 반드시 먼저 돈다.

여기서 보는 것은 딱 네 가지다.
  1) 텍스트 레이어가 있나 (없으면 OCR 로 가야 한다)
  2) 조판 — 단 구성, 각주 위치와 구분선, 한자, 사건번호 괄호 모양
  3) span 단위 색이 나오나, 몇 종인가 (§2.4)
  4) 우측 여백에 옆번호(sE-8)가 있나, 본문과 붙어 나오나 (§4.3)

판정은 하되 고치지는 않는다. 진단 결과가 파서 선택의 근거가 된다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field, asdict

from .color import ImageColorSampler, Palette, is_black, to_hex, to_rgb
from .patterns import Patterns

_HANJA = re.compile(r"[一-鿿豈-﫿]")
_SIDE = re.compile(r"[sS][A-Z]-\d{1,4}")
_SIDE_MERGED = re.compile(r"[sS][A-Z]-\d{3,}|[sS][A-Z]-\d{1,2}\s*\d")
_EXAM = re.compile(r"\((\d{2})\)")
_CHECK = re.compile(r"☑")
_PROBLEM = re.compile(r"^\s*([A-Z])\s*-\s*(\d+)\s*\.", re.M)


@dataclass
class PageDiag:
    page: int
    columns: int
    chars: int
    spans: int
    footnote_lines: int
    footnote_rule: bool
    hanja: int
    cases: list = field(default_factory=list)
    bad_open: list = field(default_factory=list)
    sidenotes: list = field(default_factory=list)
    sidenote_merged: list = field(default_factory=list)


def run(pdf_path: str, cfg: dict, sample: int = 24, layout_pages: int = 3,
        layout_range=None) -> dict:
    import pymupdf

    pat = Patterns.build(cfg)
    color_cfg = cfg["preserve"]["color"]
    palette = Palette(cfg=color_cfg)
    opens = set(cfg["normalize"]["open_brackets"]) - {"("}

    size = os.path.getsize(pdf_path)
    doc = pymupdf.open(pdf_path)
    n = doc.page_count

    fonts, embedded = Counter(), Counter()
    text_pages = 0
    scan = _spread(n, sample)
    tally = Counter()
    per_page: list[PageDiag] = []
    stars = 0
    mnemonics: Counter = Counter()
    footnote_numbers: list[int] = []
    exam_years: Counter = Counter()
    problems: Counter = Counter()
    side_all: list = []
    bonus = 0
    sizes: Counter = Counter()
    draw_colors: Counter = Counter()
    image_count: Counter = Counter()
    coverage: list[float] = []
    span_boxes: dict[int, list] = {}

    for i in scan:
        page = doc[i]
        for f in page.get_fonts(full=True):
            fonts[f[3]] += 1
            embedded["embedded" if f[1] not in ("", "n/a") else "external"] += 1
        text = page.get_text("text")
        if text.strip():
            text_pages += 1
        tally["chars"] += len(text)

        d = page.get_text("dict")
        spans = [s for b in d["blocks"] if b.get("type") == 0
                 for l in b.get("lines", []) for s in l.get("spans", [])
                 if s["text"].strip()]
        for s in spans:
            palette.add(to_rgb(s.get("color", 0)), s["text"], i + 1)
            sizes[round(s["size"] * 2) / 2] += len(s["text"].strip())
        if len(span_boxes) < 6:
            span_boxes[i] = [(s["bbox"], s["text"]) for s in spans][:400]

        # 스캔본인지 본다. 쪽을 거의 덮는 그림이 있으면 종이를 찍은 것이다.
        area = page.rect.width * page.rect.height
        biggest = 0.0
        for block in d["blocks"]:
            if block.get("type") == 1:
                x0, y0, x1, y1 = block["bbox"]
                biggest = max(biggest, abs((x1 - x0) * (y1 - y0)) / area)
        image_count[len(page.get_images())] += 1
        coverage.append(round(biggest, 3))

        # 옆번호는 조판 상세 3쪽만 보면 놓친다. 표본 전체에서 찾는다 (§4.3).
        margin_x = page.rect.width * float(cfg["legend"]["sidenote"]["margin_ratio"])
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                t = "".join(sp["text"] for sp in line.get("spans", [])).strip()
                if t and _SIDE.fullmatch(t):
                    side_all.append((i + 1, t, round(line["bbox"][0] / page.rect.width, 2),
                                     line["bbox"][0] >= margin_x))

        stars += len(pat.case_star.findall(text))
        for m in pat.mnemonic.finditer(text):
            if pat.is_mnemonic_body(m.group("body")):
                mnemonics[m.group("body")] += 1
        for m in _EXAM.finditer(text):
            exam_years[m.group(1)] += 1
        bonus += len(_CHECK.findall(text))
        # 색이 글자에 없으면 형광펜(칠한 네모)일 수 있다. 도형도 함께 본다.
        # get_drawings 는 무거워서 앞쪽 표본 몇 쪽만 본다.
        if len(draw_colors) < 40 and scan.index(i) < 8:
            for dr in page.get_drawings():
                for key in ("fill", "color"):
                    col = dr.get(key)
                    if not col:
                        continue
                    rgb = tuple(int(round(c * 255)) for c in col[:3])
                    if rgb == (255, 255, 255) or is_black(rgb, color_cfg):
                        continue
                    draw_colors[to_hex(rgb)] += 1
        for m in _PROBLEM.finditer(text):
            problems[f"{m.group(1)}-{m.group(2)}"] += 1

    body_size = sizes.most_common(1)[0][0] if sizes else 10.0

    # 글자에 색이 없고 쪽이 그림으로 덮여 있으면, 색은 그림에만 남아 있다 (§2.4).
    image_palette = Palette(cfg=color_cfg)
    color_source = "span"
    max_cov = max(coverage) if coverage else 0.0
    if palette.colored_spans == 0 and max_cov >= 0.5:
        color_source = "image"
        for i, boxes in span_boxes.items():
            sampler = ImageColorSampler(doc[i], color_cfg)
            for bbox, text in boxes:
                hexed, _ = sampler.classify(bbox)
                image_palette.total_spans += 1
                if hexed:
                    rgb = tuple(int(hexed[j:j + 2], 16) for j in (1, 3, 5))
                    image_palette.add(rgb, text, i + 1)

    # ── 조판 상세는 표본 3쪽만 (§3.1 2) ──────────────────────────
    detail = [i for i in layout_range if 0 <= i < n] if layout_range \
        else _spread(n, layout_pages)
    for i in detail:
        per_page.append(_layout(doc, i, body_size, cfg, pat, opens))
        footnote_numbers += _footnote_numbers(doc, i, body_size, cfg)

    doc.close()

    scanned = text_pages == 0 or tally["chars"] / max(1, len(scan)) < 40
    columns = Counter(p.columns for p in per_page).most_common(1)[0][0] if per_page else 1
    key = "scanned" if scanned else (
        "text_two_column" if columns >= 2 else "text_single_column")

    colors = len(palette.counts)
    result = {
        "file": os.path.abspath(pdf_path),
        "size_bytes": size,
        "pages": n,
        "sampled_pages": [i + 1 for i in scan],
        "text_layer": not scanned,
        "text_pages_in_sample": text_pages,
        "avg_chars_per_page": round(tally["chars"] / max(1, len(scan)), 1),
        "fonts": fonts.most_common(12),
        "font_embedding": dict(embedded),
        "pdffonts": _pdffonts(pdf_path),
        "body_size": body_size,
        "columns": columns,
        "parser_key": key,
        "parser_order": cfg["parsers"]["by_diagnosis"].get(key, []),
        "profile_hint": "textbook",
        "images": {
            "per_page": image_count.most_common(5),
            "max_coverage": max_cov,
            "scanned_with_text_layer": max_cov >= 0.5 and not scanned,
        },
        "color": {
            "source": color_source,
            "span_rgb_available": palette.total_spans > 0,
            "total_spans": palette.total_spans,
            "colored_spans": palette.colored_spans,
            "distinct_colors": colors,
            "image_sampled_spans": image_palette.total_spans,
            "image_colored_spans": image_palette.colored_spans,
            "image_palette": [{"hex": k, "spans": c, "chars": image_palette.chars[k],
                               "samples": image_palette.samples[k]}
                              for k, c in image_palette.ordered()],
            "palette": [{"hex": k, "spans": c, "chars": palette.chars[k],
                         "samples": palette.samples[k]} for k, c in palette.ordered()],
            "drawing_colors": draw_colors.most_common(8),
        },
        "sidenote": {
            "found": sum(1 for _, _, _, in_margin in side_all if in_margin),
            "found_anywhere": len(side_all),
            "merged_suspect": [s for p in per_page for s in p.sidenote_merged],
            "samples": [t for _, t, _, _ in side_all][:12],
            "x_ratios": sorted({r for _, _, r, _ in side_all})[:8],
        },
        "cases": {
            "samples": [c for p in per_page for c in p.cases][:12],
            "bad_open_brackets": [b for p in per_page for b in p.bad_open],
            "stars_in_sample": stars,
        },
        "mnemonics": mnemonics.most_common(10),
        "hanja_in_sample": sum(p.hanja for p in per_page),
        "footnote": {
            "lines_in_sample": sum(p.footnote_lines for p in per_page),
            "rule_found": any(p.footnote_rule for p in per_page),
            "numbers": sorted(set(footnote_numbers))[:20],
        },
        "exam_years": exam_years.most_common(10),
        "bonus_boxes_in_sample": bonus,
        "problem_numbers": problems.most_common(10),
        "pages_detail": [asdict(p) for p in per_page],
    }
    return result


def _spread(n: int, k: int) -> list[int]:
    """문서 전체에 고루 퍼진 표본 페이지. 앞뒤 표지는 피한다."""
    if n <= k:
        return list(range(n))
    lo, hi = int(n * 0.05), int(n * 0.95)
    span = max(1, (hi - lo) // k)
    return [min(n - 1, lo + j * span) for j in range(k)]


def _layout(doc, i, body_size, cfg, pat, opens) -> PageDiag:
    page = doc[i]
    rect = page.rect
    d = page.get_text("dict")
    lines = [l for b in d["blocks"] if b.get("type") == 0 for l in b.get("lines", [])]
    spans = [s for l in lines for s in l.get("spans", []) if s["text"].strip()]
    text = page.get_text("text")

    # 단 구성
    mid, band = rect.width / 2, rect.width * 0.06
    body = [l for l in lines if l["bbox"][1] > rect.height * 0.1]
    crossing = sum(1 for l in body if l["bbox"][0] < mid - band and l["bbox"][2] > mid + band)
    left = sum(1 for l in body if l["bbox"][2] <= mid + band)
    right = sum(1 for l in body if l["bbox"][0] >= mid - band)
    two = bool(body) and crossing <= len(body) * 0.08 and \
        left >= len(body) * 0.25 and right >= len(body) * 0.25

    # 각주: 아래쪽 작은 글자 + 그 위 가로선
    fn_cfg = cfg["preserve"]["footnote"]
    limit = rect.height * (1 - float(fn_cfg["bottom_zone"]))
    small = body_size * float(fn_cfg["size_ratio"])
    fn_lines = [l for l in lines
                if l["bbox"][1] >= limit
                and max((s["size"] for s in l.get("spans", [])), default=0) < small]
    rule = _has_rule(page, rect, limit)

    # 사건번호 괄호 모양 (§3.1 2)
    cases, bad = [], []
    for m in pat.case_loose.finditer(text):
        left_ctx = text[max(0, m.start() - 1):m.start()]
        cases.append(text[max(0, m.start() - 1):m.end() + 1])
        if left_ctx and left_ctx[-1] in opens:
            bad.append(f"…{text[max(0, m.start()-12):m.end()+2]}…")

    # 우측 여백 옆번호 (§4.3)
    margin_x = rect.width * float(cfg["legend"]["sidenote"]["margin_ratio"])
    side, merged = [], []
    for l in lines:
        t = "".join(s["text"] for s in l.get("spans", [])).strip()
        if not t:
            continue
        if l["bbox"][0] >= margin_x and _SIDE.fullmatch(t):
            side.append(t)
        for m in _SIDE_MERGED.finditer(t):
            merged.append(f"…{t[max(0, m.start()-10):m.end()+10]}…")

    return PageDiag(
        page=i + 1, columns=2 if two else 1, chars=len(text), spans=len(spans),
        footnote_lines=len(fn_lines), footnote_rule=rule,
        hanja=len(_HANJA.findall(text)),
        cases=cases[:6], bad_open=bad[:6], sidenotes=side, sidenote_merged=merged[:4],
    )


def _has_rule(page, rect, limit) -> bool:
    """각주 구분선: 페이지 아래쪽의 가로로 긴 얇은 선."""
    try:
        drawings = page.get_drawings()
    except Exception:                                   # pragma: no cover
        return False
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        if r.y0 >= limit * 0.9 and r.width > rect.width * 0.2 and r.height <= 2.5:
            return True
    return False


def _footnote_numbers(doc, i, body_size, cfg) -> list[int]:
    page = doc[i]
    rect = page.rect
    fn = cfg["preserve"]["footnote"]
    limit = rect.height * (1 - float(fn["bottom_zone"]))
    small = body_size * float(fn["size_ratio"])
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            if l["bbox"][1] < limit:
                continue
            if max((s["size"] for s in l.get("spans", [])), default=0) >= small:
                continue
            t = "".join(s["text"] for s in l.get("spans", [])).strip()
            m = re.match(r"^(\d{1,4})\b", t)
            if m:
                out.append(int(m.group(1)))
    return out


def _pdffonts(pdf_path: str) -> str:
    """pdffonts 가 깔려 있으면 그 출력도 함께 싣는다 (§3.1 1)."""
    exe = shutil.which("pdffonts")
    if not exe:
        return "(pdffonts 없음 — PyMuPDF 폰트 목록으로 대신함)"
    try:
        out = subprocess.run([exe, "-l", "5", pdf_path], capture_output=True,
                             text=True, timeout=120)
        return (out.stdout or out.stderr).strip()[:4000]
    except Exception as exc:                            # pragma: no cover
        return f"(pdffonts 실행 실패: {exc})"


# ── 리포트 ──────────────────────────────────────────────────────
def report(d: dict, cfg: dict) -> str:
    L: list[str] = []
    a = L.append
    a(f"# 진단 리포트 — `{os.path.basename(d['file'])}` (§3.1)")
    a("")
    a(f"- 경로: `{d['file']}`")
    a(f"- 크기: {d['size_bytes'] / 1024 / 1024:.1f} MB, {d['pages']:,}쪽")
    a(f"- 표본: {len(d['sampled_pages'])}쪽 "
      f"({', '.join(str(p) for p in d['sampled_pages'][:12])}…)")
    a("")

    a("## 1) 텍스트 레이어 (§3.1-1)")
    a("")
    verdict = "**텍스트 PDF — 추출 방식**" if d["text_layer"] else "**스캔 PDF — OCR 방식**"
    a(f"- 판정: {verdict}")
    a(f"- 표본 {len(d['sampled_pages'])}쪽 중 글자 있는 쪽: {d['text_pages_in_sample']}")
    a(f"- 쪽당 평균 글자 수: {d['avg_chars_per_page']:,}")
    a(f"- 폰트 {len(d['fonts'])}종: " +
      ", ".join(f"`{n}`×{c}" for n, c in d["fonts"][:8]))
    a(f"- 임베딩: {d['font_embedding']}")
    a("")
    a("<details><summary>pdffonts 출력</summary>")
    a("")
    a("```")
    a(d["pdffonts"])
    a("```")
    a("</details>")
    a("")

    a("## 2) 조판 (§3.1-2)")
    a("")
    a(f"- 단 구성: **{d['columns']}단**")
    fnt = d["footnote"]
    a(f"- 각주: 표본에서 하단 작은 글자 {fnt['lines_in_sample']}줄, "
      f"구분 가로선 {'**있음**' if fnt['rule_found'] else '없음'}")
    if fnt["numbers"]:
        a(f"  - 각주 번호 표본: {', '.join(str(x) for x in fnt['numbers'][:12])}")
    a(f"- 한자 인식: 표본에서 {d['hanja_in_sample']}자 "
      f"({'甲乙判例 계열 인식됨' if d['hanja_in_sample'] else '한자 없음 — 확인 필요'})")
    a(f"- 본문 글자 크기: {d['body_size']}pt")
    a("")
    a("**사건번호 괄호 모양**")
    a("")
    if d["cases"]["samples"]:
        a("- 표본: " + ", ".join(f"`{s}`" for s in d["cases"]["samples"][:8]))
    else:
        a("- 표본 쪽에서 사건번호를 찾지 못했다. 표본 쪽을 바꿔 다시 볼 것.")
    if d["cases"]["bad_open_brackets"]:
        a("")
        a("- ⚠️ **여는 괄호 오인식이 있다. 지침 §3.1 에 따라 파서 교체를 검토할 것.**")
        for s in d["cases"]["bad_open_brackets"][:6]:
            a(f"  - `{s}`")
    else:
        a("- 여는 괄호 오인식 없음 (정상 `(74다1557)` 꼴)")
    a(f"- 표본 내 별표(`*`) 붙은 사건번호: {d['cases']['stars_in_sample']}건")
    a("")

    img = d.get("images", {})
    if img:
        a("## 2-1) 쪽 그림 (스캔본 판별)")
        a("")
        a(f"- 쪽을 덮는 그림의 최대 비율: **{img['max_coverage']:.0%}**")
        a(f"- 쪽당 그림 수: " + ", ".join(f"{k}장×{v}쪽" for k, v in img["per_page"][:4]))
        if img.get("scanned_with_text_layer"):
            a("")
            a("- ⚠️ **종이를 스캔한 그림 위에 OCR 텍스트가 얹힌 PDF다.**")
            a("  - 글자 색은 전부 검정이 된다. 저자가 칠한 강조색은 그림에만 남는다(§2.4).")
            a("  - 추출 글자에 OCR 오인식(`＜`, `2010^99040`)이 섞인다(§4.6).")
            a("  - 파서를 바꿔도 이 오인식은 그대로다. 정규화(§4)로 되돌린다.")
        a("")

    a("## 3) 색상 추출 (§3.1-3, §2.4)")
    a("")
    c = d["color"]
    a(f"- 색을 읽은 곳: **{'쪽 그림(픽셀)' if c.get('source') == 'image' else '글자(span)'}**")
    a(f"- span 단위 RGB: {'**나온다**' if c['span_rgb_available'] else '안 나온다'}")
    a(f"- 전체 span {c['total_spans']:,} 중 유채색 {c['colored_spans']:,}")
    a(f"- 병합 후 색상 종류: **{c['distinct_colors']}종**")
    if c["palette"]:
        a("")
        a("| 색 | span | 글자 | 예문 |")
        a("|---|---:|---:|---|")
        for p in c["palette"][:6]:
            ex = p["samples"][0][1] if p["samples"] else ""
            a(f"| `{p['hex']}` | {p['spans']:,} | {p['chars']:,} | {ex[:40]} |")
    if c.get("source") == "image":
        a("")
        a(f"- 쪽 그림에서 다시 본 결과: 글자상자 {c['image_sampled_spans']:,}개 중 "
          f"**유채색 {c['image_colored_spans']:,}개**")
        if c.get("image_palette"):
            a("")
            a("| 색 | 글자상자 | 예문 |")
            a("|---|---:|---|")
            for pal in c["image_palette"][:6]:
                ex = pal["samples"][0][1] if pal["samples"] else ""
                a(f"| `{pal['hex']}` | {pal['spans']:,} | {ex[:44]} |")
            a("")
            a("- ✅ **강조색이 그림에 남아 있다.** `preserve.color.source: auto` 가 "
              "이 경로를 자동으로 탄다. §2.4 보존 가능.")
        else:
            a("")
            a("- ⚠️ 그림에서도 유채색을 못 찾았다. 흑백 스캔이거나 임계값이 안 맞는다. "
              "`preserve.color.chroma_min` 을 낮춰 보고, `convert probe --page N` 으로 "
              "그 쪽을 직접 볼 것.")
    if c.get("drawing_colors"):
        a("")
        a("- 도형(형광펜·밑줄·테두리) 유채색: " +
          ", ".join(f"`{h}`×{n}" for h, n in c["drawing_colors"][:6]))
    if c["distinct_colors"] > 1:
        a("")
        a("- ⚠️ 색이 2종 이상이다. `_reports/palette.md` 를 보고 **사람이** 병합 기준을 "
          "정할 것 (§2.4). 자동 판정하지 않는다.")
    elif c["distinct_colors"] == 0 and not c.get("image_colored_spans"):
        a("")
        if c.get("drawing_colors"):
            a("- ⚠️ **글자 색으로는 강조가 없다. 다만 도형에 색이 있다** — 강조가 "
              "글자색이 아니라 형광펜(칠한 네모)일 수 있다. "
              "`convert probe <pdf>` 로 확인할 것.")
        else:
            a("- ⚠️ 유채색이 글자에도 도형에도 없다. 강조색이 없는 판본이거나 색이 "
              "소실됐다(압축본이면 그럴 수 있다). §5.4 WARN 대상. "
              "`convert probe <pdf>` 로 원문을 직접 확인할 것.")
    a("")

    a("## 4) 우측 여백 옆번호 (§3.1-4, §4.3)")
    a("")
    sd = d["sidenote"]
    a(f"- 여백에서 찾은 `sE-n` 꼴: {sd['found']}건 "
      f"(자리를 가리지 않으면 {sd.get('found_anywhere', sd['found'])}건)")
    if sd["samples"]:
        a(f"  - 표본: {', '.join('`' + s + '`' for s in sd['samples'])}")
    if sd.get("x_ratios"):
        a(f"  - 쪽폭 대비 x: {', '.join(str(r) for r in sd['x_ratios'])} "
          f"(`legend.sidenote.margin_ratio` 보다 커야 여백으로 잡힌다)")
    if sd["merged_suspect"]:
        a("- ⚠️ **본문과 병합 의심** (sE-8 + 1. → sE-81):")
        for s in sd["merged_suspect"][:6]:
            a(f"  - `{s}`")
        a("  - 좌표 기반 분리가 반드시 필요하다. `pymupdf` 파서를 쓸 것.")
    else:
        a("- 병합 의심 없음")
    a("")

    a("## 5) 그 밖에 확인된 범례 요소 (§1.5)")
    a("")
    a(f"- ② 두문자: {len(d['mnemonics'])}종 — " +
      (", ".join(f"`[{m}]`×{c}" for m, c in d["mnemonics"][:6]) or "표본에 없음"))
    a(f"- ⑧ ☑ 보너스 박스: 표본에서 {d['bonus_boxes_in_sample']}건")
    if d.get("problem_numbers"):
        a(f"- 사례집 문제 번호: " +
          ", ".join(f"`{p}`×{c}" for p, c in d["problem_numbers"][:8]))
    a(f"- ⑨ 기출연도 `(nn)`: " +
      (", ".join(f"`({y})`×{c}" for y, c in d["exam_years"][:8]) or "표본에 없음"))
    a("")

    a("## 판정")
    a("")
    a(f"- 파서 분류: `{d['parser_key']}`")
    a(f"- 파서 우선순위: {' → '.join(d['parser_order'])}")
    a(f"- 권장 프로파일: `{d['profile_hint']}`")
    a("")
    a("### 쪽별 상세")
    a("")
    a("| 쪽 | 단 | 글자 | span | 각주줄 | 구분선 | 한자 | 옆번호 |")
    a("|---:|---:|---:|---:|---:|---|---:|---|")
    for p in d["pages_detail"]:
        a(f"| {p['page']} | {p['columns']} | {p['chars']:,} | {p['spans']} | "
          f"{p['footnote_lines']} | {'○' if p['footnote_rule'] else '-'} | "
          f"{p['hanja']} | {', '.join(p['sidenotes']) or '-'} |")
    a("")
    return "\n".join(L) + "\n"


def save(d: dict, cfg: dict, out_dir) -> tuple[str, str]:
    """지침이 말한 `_reports/diagnosis.md` 와, 파일별 사본을 함께 남긴다.

    기본서와 사례집을 잇달아 진단하면 한 이름으로는 뒤엣것이 앞엣것을 덮는다.
    그러면 run 단계의 '진단 먼저' 확인이 엉뚱한 파일을 보게 된다.
    """
    import pathlib
    reports = pathlib.Path(out_dir)
    reports.mkdir(parents=True, exist_ok=True)
    stem = pathlib.Path(d["file"]).stem
    text = report(d, cfg)
    blob = json.dumps(d, ensure_ascii=False, indent=2)
    md = reports / f"diagnosis-{stem}.md"
    js = reports / f"diagnosis-{stem}.json"
    md.write_text(text, encoding="utf-8")
    js.write_text(blob, encoding="utf-8")
    (reports / "diagnosis.md").write_text(text, encoding="utf-8")
    (reports / "diagnosis.json").write_text(blob, encoding="utf-8")
    return str(md), str(js)
