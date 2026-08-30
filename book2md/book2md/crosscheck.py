"""두 소스 교차 검증 (§5.3, §5.5).

기본서와 사례집에 같은 두문자가 나온다. 한쪽이 깨져 있으면 여기서 드러난다.
실측 사례: 기본서 `[확객시전]` vs 사례집 `[확객시젠]` — 한 글자 차이다.

**어느 쪽이 옳은지 판정하지 않는다.** 양쪽 원문을 나란히 놓고 사람이 정한다(§2.2).
그래서 '거의 같은데 다른' 짝을 찾아 내는 것이 이 모듈의 핵심이다. 교집합만
보면 한 글자가 다른 순간 서로 다른 항목이 되어 조용히 지나가 버린다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .patterns import Patterns
from .validate import md_files

_SIDE = re.compile(r"s[A-Z]-(\d{1,4})")
_PROBLEM = re.compile(r"^#{1,3}\s+([A-Z])-(\d+)\.", re.M)


def _collect(root: Path, pat: Patterns):
    counts: Counter = Counter()
    context: dict[str, list[str]] = {}
    sides: Counter = Counter()
    problems: set[str] = set()
    for path in md_files(root):
        text = path.read_text(encoding="utf-8")
        for m in pat.mnemonic.finditer(text):
            body = m.group("body")
            if not pat.is_mnemonic_body(body):
                continue
            counts[body] += 1
            context.setdefault(body, []).append(
                f"{path.name}: …{text[max(0, m.start() - 28):m.end() + 28]}…"
                .replace("\n", "⏎"))
        for m in _SIDE.finditer(text):
            sides[m.group(0)] += 1
        for m in _PROBLEM.finditer(text):
            problems.add(f"{m.group(1)}-{m.group(2)}")
    return counts, context, sides, problems


def _distance(a: str, b: str) -> int:
    """레벤슈타인 거리. 길이가 짧아 단순 DP 로 충분하다."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def crosscheck(dir_a, dir_b, cfg: dict, label_a="기본서", label_b="사례집") -> tuple[str, int]:
    pat = Patterns.build(cfg)
    a, ctx_a, side_a, prob_a = _collect(Path(dir_a), pat)
    b, ctx_b, side_b, prob_b = _collect(Path(dir_b), pat)

    both = sorted(set(a) & set(b))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))

    # 한쪽에만 있는 것들 중 '거의 같은' 짝 — 여기가 진짜 위험한 지점이다
    pairs = []
    for x in only_a:
        for y in only_b:
            d = _distance(x, y)
            if 0 < d <= max(1, len(x) // 4) and abs(len(x) - len(y)) <= 1:
                pairs.append((x, y, d))
    pairs.sort(key=lambda t: (t[2], t[0]))

    L = ["# 두문자 교차 검증 (§5.3)", ""]
    L.append(f"- {label_a}: {len(a)}종 / {label_b}: {len(b)}종")
    L.append(f"- 양쪽 모두: {len(both)}종 (글자 단위 일치)")
    L.append(f"- **불일치 의심 짝: {len(pairs)}건**")
    L.append("")
    if pairs:
        L.append("## ⚠️ 불일치 의심 — 어느 쪽이 옳은지 사람이 판단할 것")
        L.append("")
        L.append("자동 교정하지 않았다. 양쪽 원문을 그대로 싣는다.")
        L.append("")
        for x, y, d in pairs:
            L.append(f"### `[{x}]` ({label_a}, {a[x]}회) ↔ `[{y}]` ({label_b}, {b[y]}회) "
                     f"— {d}글자 차이")
            L.append("")
            L.append(f"| 소스 | 표기 | 원문 |")
            L.append("|---|---|---|")
            L.append(f"| {label_a} | `[{x}]` | {ctx_a[x][0]} |")
            L.append(f"| {label_b} | `[{y}]` | {ctx_b[y][0]} |")
            L.append("")
    if both:
        L.append("## 양쪽 일치")
        L.append("")
        for m in both:
            L.append(f"- `[{m}]` — {label_a} {a[m]}회 / {label_b} {b[m]}회")
        L.append("")
    if only_a or only_b:
        L.append("## 한쪽에만 있는 두문자 (정상일 수 있다)")
        L.append("")
        for m in only_a:
            if not any(m == x for x, _, _ in pairs):
                L.append(f"- {label_a} 만: `[{m}]` ×{a[m]}")
        for m in only_b:
            if not any(m == y for _, y, _ in pairs):
                L.append(f"- {label_b} 만: `[{m}]` ×{b[m]}")
        L.append("")

    # §5.5 여백 마커 대조
    L.append("## 여백 마커 대조 (§5.5)")
    L.append("")
    L.append(f"- {label_a} 의 `sE-n` 옆번호: {len(side_a)}종 "
             f"({', '.join(sorted(side_a)[:12]) or '없음'})")
    L.append(f"- {label_b} 의 문제 번호: {len(prob_b)}종 "
             f"({', '.join(sorted(prob_b)[:12]) or '없음'})")
    L.append("")
    L.append("> 옆번호(`sE-8`)는 **강의교안 번호**로 사례집 문제 번호(`E-5`)와 다른 "
             "체계다(§4.3). 숫자가 안 맞는 것 자체는 오류가 아니다. 다만 "
             "`sE-81` 처럼 자릿수가 갑자기 커진 것은 병합 사고다.")
    L.append("")
    big = [s for s in side_a if int(_SIDE.match(s).group(1)) >= 100]
    if big:
        L.append(f"- ⚠️ 자릿수가 큰 옆번호: {', '.join(sorted(big))} — 병합 의심")
        L.append("")

    return "\n".join(L) + "\n", len(pairs)
