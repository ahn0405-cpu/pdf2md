"""색상 강조 (§2.4) = 교재 범례 ⑤ 「답안 활용 가이드」.

저자가 색으로 지정해 둔 범위를 그대로 살리는 것이 목적이다. 색의 '뜻'은
여기서 정하지 않는다. 팔레트를 세어 리포트로 내고(§2.4), 매핑은 사람이
config.yaml 에서 확정한다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field


def to_rgb(value: int) -> tuple[int, int, int]:
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def is_black(rgb, cfg) -> bool:
    """강조색이 아닌가. 곧 본문(검정·회색) 인가.

    무채색은 밝기와 무관하게 강조가 아니다. 회색 머리말·연회색 캡션을 강조로
    세면 §5.4 색상 개수 대조가 통째로 어긋난다. 지침이 말하는 강조색은
    '유채색(검정 아님)' 이고, 회색은 유채색이 아니다.
    """
    spread = max(rgb) - min(rgb)
    if spread <= int(cfg["gray_span"]):
        return True                      # 무채색 = 본문/볼드
    return max(rgb) <= int(cfg["black_max"])   # 아주 어두운 색도 본문으로 본다


def distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


@dataclass
class Palette:
    """유채색 span 통계. 근접색은 병합한다."""
    cfg: dict
    counts: Counter = field(default_factory=Counter)
    samples: dict = field(default_factory=lambda: defaultdict(list))
    chars: Counter = field(default_factory=Counter)
    total_spans: int = 0
    colored_spans: int = 0

    def add(self, rgb, text: str, page: int) -> str | None:
        """span 하나를 넣는다. 유채색이면 병합된 대표색을 돌려준다."""
        self.total_spans += 1
        if is_black(rgb, self.cfg):
            return None
        key = self._merge(rgb)
        self.counts[key] += 1
        self.chars[key] += len(text.strip())
        self.colored_spans += 1
        if len(self.samples[key]) < int(self.cfg.get("samples", 5)):
            self.samples[key].append((page, text.strip()[:80]))
        return key

    def _merge(self, rgb) -> str:
        """근접색 병합 (§2.4). 기존 대표색 중 가까운 것이 있으면 그리로 붙인다."""
        limit = float(self.cfg.get("merge_distance", 60))
        for key in self.counts:
            if distance(rgb, from_hex(key)) <= limit:
                return key
        return to_hex(rgb)

    def ordered(self):
        return self.counts.most_common()

    def markup_for(self, key: str) -> str:
        """색 → 마크업. overrides 가 있으면 그것이 우선."""
        over = (self.cfg.get("overrides") or {}).get(key)
        markup = self.cfg.get("markup", {})
        if over:
            return markup.get(over, markup.get("emphasis", "=="))
        return markup.get("emphasis", "==")


def from_hex(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def report(palette: Palette) -> str:
    """_reports/palette.md (§2.4).

    두 색의 뜻은 판정하지 않는다. 사람이 보고 정할 수 있게 근거만 늘어놓는다.
    """
    lines = ["# 색상 팔레트 리포트 (§2.4)", ""]
    lines.append(f"- 전체 span: {palette.total_spans:,}")
    lines.append(f"- 유채색 span: {palette.colored_spans:,} "
                 f"({_pct(palette.colored_spans, palette.total_spans)})")
    lines.append(f"- 병합 후 색상 종류: **{len(palette.counts)}종**")
    lines.append("")
    if len(palette.counts) == 0:
        lines.append("> 유채색이 없다. 색으로 강조한 부분이 없거나, 파서가 색을 "
                     "내주지 않는다. §5.4 에서 WARN 으로 잡힌다.")
    elif len(palette.counts) > 1:
        lines.append("> **색이 2종 이상이다.** 지침 §2.4 는 최종 1종을 요구한다. "
                     "아래 예문을 보고 병합 기준을 정한 뒤 "
                     "`normalize`… 가 아니라 `preserve.color.merge_distance` 를 "
                     "키우거나 `preserve.color.overrides` 에 색별 매핑을 적을 것.")
    else:
        lines.append("> 색상 1종. 지침이 말한 「강조색 1종(청색 계열)」과 맞는지 확인할 것.")
    lines.append("")
    lines.append("| 색 | span 수 | 글자 수 | 비율 | 제안 마크업 |")
    lines.append("|---|---:|---:|---:|---|")
    for key, count in palette.ordered():
        lines.append(f"| `{key}` | {count:,} | {palette.chars[key]:,} | "
                     f"{_pct(count, palette.colored_spans)} | "
                     f"`{palette.markup_for(key)}텍스트{palette.markup_for(key)}` |")
    lines.append("")
    for key, _ in palette.ordered():
        lines.append(f"### `{key}` 예문")
        lines.append("")
        for page, text in palette.samples[key]:
            lines.append(f"- p.{page} — {text}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**두 색의 뜻(요건/효과 구분인지 단순 교대 강조인지)은 자동 판정하지 "
                 "않는다.** 위 예문을 보고 사람이 정한다.")
    return "\n".join(lines) + "\n"


def _pct(part, whole) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "-"
