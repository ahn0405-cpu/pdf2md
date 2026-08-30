"""원문 증거 뜨기.

진단(§3.1)이 "없다"고 말할 때, 정말 없는 것인지 우리가 엉뚱한 데를 보고 있는
것인지 가르려면 원문을 그대로 봐야 한다. 이 모듈은 판정하지 않는다. 파서가 준
것을 그대로 늘어놓는다.

  probe scan   표본 쪽에서 괄호·색·옆번호·두문자 후보를 세어 늘어놓는다
  probe find   글자를 찾아 어느 쪽에 있는지 알려 준다 (변환할 장을 고를 때)
  probe page   한 쪽의 span 과 도형을 전부 덤프한다 (마지막 수단)
  probe color  한 쪽의 낱말마다 유채색 비율을 재어 늘어놓는다 (임계값 정할 때)

색이 span 색으로 안 나오면 형광펜(칠한 네모)일 수 있다. 그래서 도형도 함께 본다.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .color import is_black, to_hex, to_rgb
from .patterns import Patterns

_BRACKETS = "[](){}［］｛｝〔〕【】〈〉《》「」『』＜＞≪≫<>"
_SIDE_ANY = re.compile(r"s\s*[A-Z]\s*-\s*\d{1,4}")
_MNEMONIC_ANY = re.compile(
    r"([\[［｛{〔【〈《「『＜])([가-힣]{2,6}(?:\s[가-힣]{2,6}){0,2})([\]］｝}〕】〉》」』＞])")


def _pages(doc, sample: int):
    n = doc.page_count
    if n <= sample:
        return list(range(n))
    lo, hi = int(n * 0.05), int(n * 0.95)
    step = max(1, (hi - lo) // sample)
    return [min(n - 1, lo + j * step) for j in range(sample)]


def scan(pdf_path: str, cfg: dict, sample: int = 40, pages=None) -> str:
    import pymupdf

    pat = Patterns.build(cfg)
    color_cfg = cfg["preserve"]["color"]
    doc = pymupdf.open(pdf_path)
    idx = [i for i in pages if 0 <= i < doc.page_count] if pages \
        else _pages(doc, sample)

    before_case: Counter = Counter()
    after_case: Counter = Counter()
    case_samples: list[str] = []
    brackets: Counter = Counter()
    mnem: Counter = Counter()
    mnem_samples: list[str] = []
    span_colors: Counter = Counter()
    draw_fill: Counter = Counter()
    draw_stroke: Counter = Counter()
    draw_samples: dict = defaultdict(list)
    sides: list[tuple[int, str, float, float]] = []
    small_lines: Counter = Counter()
    sizes: Counter = Counter()
    images: list[dict] = []

    for i in idx:
        page = doc[i]
        width = page.rect.width
        text = page.get_text("text")

        for ch in text:
            if ch in _BRACKETS:
                brackets[ch] += 1
        for m in pat.case_loose.finditer(text):
            left = text[m.start() - 1:m.start()]
            right = text[m.end():m.end() + 1]
            before_case[left if left.strip() else "(공백)"] += 1
            after_case[right if right.strip() else "(공백)"] += 1
            if len(case_samples) < 12:
                case_samples.append(text[max(0, m.start() - 24):m.end() + 6]
                                    .replace("\n", "⏎"))
        for m in _MNEMONIC_ANY.finditer(text):
            mnem[m.group(1) + m.group(3)] += 1
            if len(mnem_samples) < 12:
                mnem_samples.append(m.group(0))

        d = page.get_text("dict")
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                joined = "".join(s["text"] for s in line.get("spans", []))
                for m in _SIDE_ANY.finditer(joined):
                    sides.append((i + 1, m.group(0), round(line["bbox"][0], 1),
                                  round(line["bbox"][0] / width, 2)))
                for s in line.get("spans", []):
                    if not s["text"].strip():
                        continue
                    rgb = to_rgb(s.get("color", 0))
                    span_colors[to_hex(rgb)] += 1
                    sizes[round(s["size"] * 2) / 2] += len(s["text"].strip())

        body = sizes.most_common(1)[0][0] if sizes else 9.0
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                mx = max((s["size"] for s in line.get("spans", [])), default=0)
                if mx and mx < body * 0.92:
                    small_lines[round(line["bbox"][1] / page.rect.height, 1)] += 1

        if len(images) < 12:
            area = page.rect.width * page.rect.height
            for info in page.get_images(full=True):
                xref, _, w, h, bpc, cs = info[0], info[1], info[2], info[3], info[4], info[5]
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                r = rects[0]
                images.append({
                    "page": i + 1, "w": w, "h": h,
                    "dx": (w / r.width * 72) if r.width else 0,
                    "dy": (h / r.height * 72) if r.height else 0,
                    "cs": cs or "?", "bpc": bpc,
                    "cov": (r.width * r.height / area) if area else 0,
                })

        for dr in page.get_drawings():
            for key, tally in (("fill", draw_fill), ("color", draw_stroke)):
                col = dr.get(key)
                if not col:
                    continue
                rgb = tuple(int(round(c * 255)) for c in col[:3])
                if rgb == (255, 255, 255):
                    continue
                hexed = to_hex(rgb)
                tally[hexed] += 1
                if len(draw_samples[hexed]) < 3:
                    r = dr.get("rect")
                    draw_samples[hexed].append(
                        f"p.{i + 1} {key} {dr.get('type')} "
                        f"{round(r.width, 1)}×{round(r.height, 1)}" if r else f"p.{i + 1}")
    doc.close()

    body = sizes.most_common(1)[0][0] if sizes else 0
    L = [f"# 원문 증거 — `{pdf_path}`", "",
         f"표본 {len(idx)}쪽. 판정하지 않는다. 파서가 준 것을 그대로 싣는다.", ""]

    L += ["## 사건번호 둘레 글자", ""]
    L.append("| 앞 글자 | 횟수 |   | 뒤 글자 | 횟수 |")
    L.append("|---|---:|---|---|---:|")
    a = before_case.most_common(8)
    b = after_case.most_common(8)
    for k in range(max(len(a), len(b))):
        la = f"`{a[k][0]}` | {a[k][1]}" if k < len(a) else " | "
        lb = f"`{b[k][0]}` | {b[k][1]}" if k < len(b) else " | "
        L.append(f"| {la} |   | {lb} |")
    L += ["", "원문 조각:", ""]
    for s in case_samples:
        L.append(f"- `{s}`")
    L.append("")

    L += ["## 괄호 글자 빈도", "",
          ", ".join(f"`{c}`×{n}" for c, n in brackets.most_common(20)) or "없음", ""]

    L += ["## 두문자 후보 (괄호 종류를 가리지 않고)", ""]
    if mnem:
        L.append(", ".join(f"`{k}`×{n}" for k, n in mnem.most_common(10)))
        L.append("")
        for s in mnem_samples:
            L.append(f"- `{s}`")
    else:
        L.append("표본에 없음. 두문자가 이 구간에 없거나, 대괄호가 아닌 다른 방식이다.")
    L.append("")

    L += ["## 글자 색 (span)", ""]
    chromatic = [(c, n) for c, n in span_colors.most_common()
                 if not is_black(tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)), color_cfg)]
    L.append("| 색 | span 수 | 유채색? |")
    L.append("|---|---:|---|")
    for c, n in span_colors.most_common(12):
        rgb = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        L.append(f"| `{c}` | {n:,} | {'**유채색**' if not is_black(rgb, color_cfg) else '무채색'} |")
    L.append("")
    if not chromatic:
        L.append("> 글자 색으로는 강조가 없다. 아래 도형(형광펜·밑줄)을 볼 것.")
        L.append("")

    L += ["## 도형 색 (형광펜·밑줄·테두리)", ""]
    if draw_fill or draw_stroke:
        L.append("| 색 | 칠 | 선 | 보기 |")
        L.append("|---|---:|---:|---|")
        for c in sorted(set(draw_fill) | set(draw_stroke),
                        key=lambda c: -(draw_fill[c] + draw_stroke[c]))[:12]:
            L.append(f"| `{c}` | {draw_fill[c]:,} | {draw_stroke[c]:,} | "
                     f"{'; '.join(draw_samples[c][:2])} |")
        L.append("")
        L.append("> 넓적한 칠(가로로 길고 세로 8~15pt)은 형광펜, 가늘고 긴 것은 밑줄이다.")
    else:
        L.append("도형이 없다.")
    L.append("")

    L += ["## 옆번호 `sE-n` 후보 (여백 여부를 가리지 않고)", ""]
    if sides:
        L.append("| 쪽 | 글자 | x | 쪽폭 대비 |")
        L.append("|---:|---|---:|---:|")
        for p, t, x, ratio in sides[:20]:
            L.append(f"| {p} | `{t}` | {x} | {ratio} |")
        L.append("")
        L.append("> `쪽폭 대비` 가 `legend.sidenote.margin_ratio`(기본 0.78)보다 작으면 "
                 "그 값을 낮춰야 여백으로 잡힌다.")
    else:
        L.append("표본에 없음.")
    L.append("")

    L += ["## 쪽 그림 해상도", "",
          "색을 그림에서 읽을 때(§2.4) 이 값이 품질을 좌우한다.", ""]
    if images:
        L.append("| 쪽 | 넓이×높이(px) | 가로 dpi | 세로 dpi | 색공간 | bpc | 쪽 덮은 비율 |")
        L.append("|---:|---|---:|---:|---|---:|---:|")
        for row in images[:12]:
            L.append("| {page} | {w:,}×{h:,} | {dx:.0f} | {dy:.0f} | {cs} | {bpc} "
                     "| {cov:.0%} |".format(**row))
        dpis = sorted(r["dx"] for r in images)
        mid = dpis[len(dpis) // 2]
        L.append("")
        L.append(f"- 가로 dpi 중앙값: **{mid:.0f}**")
        L.append(f"- 지금 설정된 표본 해상도: `preserve.color.image_dpi` = "
                 f"**{cfg['preserve']['color'].get('image_dpi', 110)}**")
        if mid < 100:
            L.append("- ⚠️ 원본이 낮다. 색 판정이 흔들릴 수 있으니 결과를 꼼꼼히 볼 것.")
        elif cfg["preserve"]["color"].get("image_dpi", 110) > mid:
            L.append("- ⚠️ 표본 해상도가 원본보다 높다. 더 얻을 것이 없으니 "
                     "`image_dpi` 를 원본 값까지 낮추면 그만큼 빨라진다.")
        else:
            L.append(f"- `image_dpi` 를 최대 {mid:.0f} 까지 올리면 글자 획이 "
                     f"두껍게 잡혀 색 판정이 또렷해진다. 그 위로는 얻을 것이 없다.")
    else:
        L.append("쪽에 박힌 그림이 없다. 스캔본이 아니라 born-digital PDF다.")
    L.append("")

    L += ["## 작은 글자가 있는 세로 위치", "",
          f"본문 {body}pt. 아래 값은 쪽 높이 대비 위치다.", "",
          ", ".join(f"{k}→{n}줄" for k, n in sorted(small_lines.items())) or "없음",
          "",
          "> 0.6 이상에 몰려 있으면 각주다. "
          "`preserve.footnote.bottom_zone` 을 그 위치에 맞춘다.", ""]
    return "\n".join(L) + "\n"


def find(pdf_path: str, needle: str, limit: int = 30) -> str:
    """글자가 어느 쪽에 있는지. 변환할 장을 고를 때 쓴다 (§8-2)."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    hits = []
    for i in range(doc.page_count):
        text = doc[i].get_text("text")
        pos = text.find(needle)
        if pos < 0:
            continue
        hits.append((i + 1, text[max(0, pos - 40):pos + 60].replace("\n", "⏎")))
        if len(hits) >= limit:
            break
    doc.close()
    L = [f"# `{needle}` 찾기 — {len(hits)}건", ""]
    for page, ctx in hits:
        L.append(f"- **p.{page}** …{ctx}…")
    if not hits:
        L.append("없다.")
    return "\n".join(L) + "\n"


def page(pdf_path: str, number: int) -> str:
    """한 쪽의 span 과 도형을 전부 덤프한다."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    p = doc[number - 1]
    L = [f"# p.{number} 덤프 — `{pdf_path}`", "",
         f"쪽 크기 {round(p.rect.width, 1)}×{round(p.rect.height, 1)}", "",
         "## span", "",
         "| x | y | pt | 색 | 굵게 | 글꼴 | 글자 |",
         "|---:|---:|---:|---|---|---|---|"]
    for block in p.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for s in line.get("spans", []):
                if not s["text"].strip():
                    continue
                shown = s["text"][:48].replace("|", "\\|")
                L.append(f"| {s['bbox'][0]:.0f} | {s['bbox'][1]:.0f} | {s['size']:.1f} "
                         f"| `{to_hex(to_rgb(s.get('color', 0)))}` "
                         f"| {'o' if s['flags'] & 16 else ''} "
                         f"| {s.get('font', '')[:18]} "
                         f"| {shown} |")
    L += ["", "## 도형", "", "| 종류 | 칠 | 선 | 위치 | 크기 |", "|---|---|---|---|---|"]
    for dr in p.get_drawings():
        r = dr.get("rect")
        fill = to_hex(tuple(int(round(c * 255)) for c in dr["fill"][:3])) if dr.get("fill") else ""
        stroke = to_hex(tuple(int(round(c * 255)) for c in dr["color"][:3])) if dr.get("color") else ""
        L.append(f"| {dr.get('type')} | `{fill}` | `{stroke}` "
                 f"| {r.x0:.0f},{r.y0:.0f} | {r.width:.0f}×{r.height:.0f} |" if r else "")
    doc.close()
    return "\n".join(L) + "\n"


def lines(pdf_path: str, cfg: dict, prof: dict, pages) -> str:
    """줄마다 '무엇으로 읽혔는지'를 보여 준다.

    헤딩이 안 잡힐 때 규칙을 고치려면, 어느 줄이 어떤 규칙에 걸렸고 어느 줄이
    아무 데도 안 걸렸는지를 봐야 한다. 추측으로 정규식을 고치면 다른 데가 깨진다.
    """
    import pymupdf

    from .footnotes import FootnoteCollector
    from .model import Page
    from .normalize import Normalizer
    from .parsers import get_parser
    from .parsers.pymupdf_native import strip_markup

    pat = Patterns.build(cfg)
    prof = dict(prof)
    prof["_config"] = cfg
    parser = get_parser("pymupdf")
    norm = Normalizer(cfg, pat)
    collector = FootnoteCollector(cfg, pat)

    heads = [(h["level"], re.compile(h["pattern"])) for h in prof.get("headings", [])]
    sec_rx = re.compile(prof["section_item"]) if prof.get("section_item") else None
    sec_max = int(prof.get("section_max_len", 40))
    ans_heads = [(h["level"], re.compile(h["pattern"]))
                 for h in prof.get("answer_headings", [])]
    problem_rx = re.compile(prof["problem"]) if prof.get("problem") else None

    L = [f"# 줄 판정 — `{pdf_path}`", "",
         "`역할` 이 `본문` 인데 제목이어야 할 줄이 있으면 그 줄의 정규식을 고쳐야 한다.",
         "각주 영역으로 떨어진 줄은 본문에서 빠진 것이다.", "",
         "| 쪽 | y | x | pt | 영역 | 역할 | 줄 |",
         "|---:|---:|---:|---:|---|---|---|"]
    in_roman = False
    for page in parser.parse(pdf_path, pages, prof):
        zones = {id(l): l.zone for l in page.lines}
        norm.normalize_page(page)
        body_before = list(page.lines)
        found = collector.process(page)
        kept = {id(l) for l in page.lines}
        for line in body_before:
            text = line.stripped
            if not text:
                continue
            zone = {"header": "머리말·꼬리말", "footnote": "각주",
                    "sidenote": "여백"}.get(line.zone, "본문")
            if zone == "본문" and id(line) not in kept:
                zone = "각주"
            plain = strip_markup(text)
            role = "본문"
            if zone == "본문":
                for level, rx in heads:
                    if rx.match(plain):
                        role = f"**헤딩 H{level}**"
                        in_roman = (level == 4)
                        break
                else:
                    if problem_rx and problem_rx.match(plain):
                        role = "**문제 헤딩**"
                    elif any(rx.match(plain) for _, rx in ans_heads) and len(plain) <= 60:
                        role = "**답안 헤딩**"
                    elif sec_rx and sec_rx.match(plain):
                        short = len(plain) <= sec_max
                        role = ("굵은 소항목" if in_roman and short else
                                "절 헤딩 H3" if short else "본문(N. 이지만 길다)")
            shown = text[:60].replace("|", "\\|")
            L.append(f"| {page.number} | {line.y0:.0f} | {line.x0:.0f} | {line.size:.1f} "
                     f"| {zone} | {role} | {shown} |")
        for f in found:
            L.append(f"| {page.number} |  |  |  | 각주 | 정의 | "
                     f"[^{f.number}] {f.text[:44]} |")
    return "\n".join(L) + "\n"


def color(pdf_path: str, cfg: dict, number: int) -> str:
    """한 쪽의 낱말마다 유채색 비율을 잰다 (§P0-2 임계값 정하기).

    강조가 덜 잡히는지 더 잡히는지는 **비율 분포**를 봐야 안다. 문턱을 짐작으로
    올리고 내리면 한쪽을 고칠 때마다 다른 쪽이 깨진다. 이 표를 보고
    `preserve.color.min_ratio` 와 `min_ratio_weak` 를 정한다.
    """
    import pymupdf

    from .color import ImageColorSampler
    from .parsers.pymupdf_native import _restore_spaces, _span_text

    color_cfg = cfg["preserve"]["color"]
    gap = float(cfg.get("extract", {}).get("space_gap_ratio", 0.18))
    doc = pymupdf.open(pdf_path)
    if not (1 <= number <= doc.page_count):
        return f"{number} 쪽이 없다 (전체 {doc.page_count}쪽)."
    page = doc[number - 1]
    sampler = ImageColorSampler(page, color_cfg)

    rows = []
    for block in page.get_text("rawdict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [sp for sp in line.get("spans", []) if _span_text(sp).strip()]
            if not spans:
                continue
            _restore_spaces(spans, gap)
            for span in spans:
                for seg, box in (span.get("_segs") or []):
                    if box is None or not seg.strip():
                        continue
                    hexed, ratio, weak = sampler.classify(box)
                    rows.append((ratio, seg.strip(), hexed or weak or "-",
                                 round(box[1], 1),
                                 "강조" if hexed else ("애매" if weak else "본문")))
    doc.close()
    if not rows:
        return f"{number} 쪽에서 글자를 못 찾았다."

    strong = sum(1 for r in rows if r[4] == "강조")
    weakn = sum(1 for r in rows if r[4] == "애매")
    L = [f"# 낱말별 유채색 비율 — `{pdf_path}` {number}쪽", "",
         f"- 낱말 {len(rows)}개 · 강조 {strong} · 애매 {weakn} · "
         f"본문 {len(rows) - strong - weakn}",
         f"- 지금 문턱: `min_ratio` {sampler.min_ratio} · "
         f"`min_ratio_weak` {sampler.weak_ratio} · "
         f"`chroma_min` {sampler.chroma_min} · `grid_cell` {sampler.CELL}",
         f"- 렌더 해상도 {sampler.dpi} dpi", ""]

    bands = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.65, 1.01]
    L.append("## 비율 분포")
    L.append("")
    L.append("| 구간 | 낱말 수 | |")
    L.append("|---|---:|---|")
    for lo, hi in zip(bands, bands[1:]):
        n = sum(1 for r in rows if lo <= r[0] < hi)
        L.append(f"| {lo:.2f} ~ {hi:.2f} | {n} | {'█' * min(60, n)} |")
    L.append("")
    L.append("> 색칠된 낱말과 검정 낱말은 두 봉우리로 갈린다. **골짜기**에 문턱을")
    L.append("> 놓는다. 골짜기가 안 보이면 `chroma_min` 을 낮추거나 `image_dpi` 를")
    L.append("> 올려야 한다 — 아직 색과 검정이 안 갈린 것이다.")
    L.append("")

    L.append("## 비율이 높은 낱말 (강조여야 한다)")
    L.append("")
    L.append("| 비율 | 판정 | 색 | y | 낱말 |")
    L.append("|---:|---|---|---:|---|")
    for ratio, seg, hexed, y, verdict in sorted(rows, reverse=True)[:60]:
        L.append(f"| {ratio:.3f} | {verdict} | `{hexed}` | {y} | {seg[:30]} |")
    L.append("")

    middle = sorted((r for r in rows if 0.02 <= r[0] < sampler.min_ratio),
                    reverse=True)
    L.append("## 문턱 바로 아래 낱말 (놓치고 있는지 볼 것)")
    L.append("")
    L.append("| 비율 | 판정 | 색 | y | 낱말 |")
    L.append("|---:|---|---|---:|---|")
    for ratio, seg, hexed, y, verdict in middle[:60]:
        L.append(f"| {ratio:.3f} | {verdict} | `{hexed}` | {y} | {seg[:30]} |")
    L.append("")
    L.append("이 표에 **원본에서 파란 낱말**이 섞여 있으면 `min_ratio` 를 그 아래로")
    L.append("내린다. 검정 낱말만 있으면 지금 문턱이 맞다.")
    return "\n".join(L) + "\n"
