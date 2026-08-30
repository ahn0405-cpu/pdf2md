"""원문 증거 뜨기.

진단(§3.1)이 "없다"고 말할 때, 정말 없는 것인지 우리가 엉뚱한 데를 보고 있는
것인지 가르려면 원문을 그대로 봐야 한다. 이 모듈은 판정하지 않는다. 파서가 준
것을 그대로 늘어놓는다.

  probe scan   표본 쪽에서 괄호·색·옆번호·두문자 후보를 세어 늘어놓는다
  probe find   글자를 찾아 어느 쪽에 있는지 알려 준다 (변환할 장을 고를 때)
  probe page   한 쪽의 span 과 도형을 전부 덤프한다 (마지막 수단)

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
