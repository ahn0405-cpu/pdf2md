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


def page_image_dpi(page) -> float:
    """쪽에 박힌 그림의 실제 해상도(가로 dpi). 없으면 0."""
    best = 0.0
    try:
        for info in page.get_images(full=True):
            rects = page.get_image_rects(info[0])
            if not rects or not rects[0].width:
                continue
            best = max(best, info[2] / rects[0].width * 72)
    except Exception:                       # pragma: no cover
        return 0.0
    return best


def _pick_dpi(page, cfg: dict) -> int:
    """색을 읽을 해상도.

    원본 그림보다 높게 렌더링해 봐야 없는 화소를 늘리는 것뿐이라 얻을 게 없다.
    반대로 너무 낮으면 글자 획이 한 화소 아래로 얇아져 종이와 섞이고, 색이
    옅어져 판정이 흔들린다. 그래서 원본 해상도에 맞추되 위아래로 가둔다.
    """
    want = cfg.get("image_dpi", "auto")
    if isinstance(want, (int, float)):
        return int(want)
    native = page_image_dpi(page)
    lo = int(cfg.get("image_dpi_min", 100))
    hi = int(cfg.get("image_dpi_max", 200))
    if native <= 0:
        return lo
    return max(lo, min(hi, int(round(native))))


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


class ImageColorSampler:
    """쪽 그림에서 색을 읽는다 (스캔본 + OCR 텍스트 레이어용).

    이 교재는 종이를 스캔한 그림 위에 OCR 텍스트가 얹혀 있다. 그래서 글자 색은
    전부 검정이고, 저자가 칠한 강조색은 **그림 픽셀에만** 남아 있다(§2.4).
    글자 상자 안의 잉크 픽셀을 세어, 유채색이 충분히 섞여 있으면 강조로 본다.

    쪽마다 픽셀을 딱 한 번 훑어 격자에 모아 둔다. 글자 상자마다 다시 훑으면
    500쪽짜리에서 파이썬 반복이 수억 번 돌아 못 쓴다.
    """

    #: 격자 한 칸의 크기(pt). 글자 높이(8~11pt)보다 충분히 작아야 한다.
    CELL = 3.0

    def __init__(self, page, cfg: dict):
        self.cfg = cfg
        self.dpi = _pick_dpi(page, cfg)
        self.ink_max = int(cfg.get("ink_max", 205))
        self.chroma_min = int(cfg.get("chroma_min", 42))
        self.min_ratio = float(cfg.get("min_ratio", 0.34))
        self.step = max(1, int(cfg.get("pixel_step", 2)))
        self.scale = self.dpi / 72.0
        self._page = page
        self._grid = None
        self.cols = self.rows = 0

    # ── 쪽 한 번 훑기 ────────────────────────────────────────────
    def _build(self):
        import pymupdf

        pix = self._page.get_pixmap(dpi=self.dpi, colorspace=pymupdf.csRGB, annots=False)
        rect = self._page.rect
        self.cols = max(1, int(rect.width / self.CELL) + 1)
        self.rows = max(1, int(rect.height / self.CELL) + 1)
        ink = [0] * (self.cols * self.rows)
        chroma = [0] * (self.cols * self.rows)
        rsum = [0] * (self.cols * self.rows)
        gsum = [0] * (self.cols * self.rows)
        bsum = [0] * (self.cols * self.rows)

        samples = pix.samples
        stride, n = pix.stride, pix.n
        step = self.step
        px_per_cell = self.CELL * self.scale
        ink_max, chroma_min = self.ink_max, self.chroma_min

        for y in range(0, pix.height, step):
            row_base = y * stride
            cell_row = int(y / px_per_cell) * self.cols
            for x in range(0, pix.width, step):
                o = row_base + x * n
                r = samples[o]
                g = samples[o + 1]
                b = samples[o + 2]
                hi = r if r > g else g
                if b > hi:
                    hi = b
                if hi > ink_max:
                    continue                        # 종이
                lo = r if r < g else g
                if b < lo:
                    lo = b
                k = cell_row + int(x / px_per_cell)
                ink[k] += 1
                if hi - lo >= chroma_min:
                    chroma[k] += 1
                    rsum[k] += r
                    gsum[k] += g
                    bsum[k] += b
        self._grid = (ink, chroma, rsum, gsum, bsum)

    # ── 글자 상자 하나 ───────────────────────────────────────────
    def classify(self, bbox) -> tuple[str | None, float]:
        """(대표색 또는 None, 유채색 비율)."""
        if self._grid is None:
            self._build()
        ink_g, chroma_g, rsum, gsum, bsum = self._grid
        c0 = max(0, int(bbox[0] / self.CELL))
        c1 = min(self.cols - 1, int(bbox[2] / self.CELL))
        r0 = max(0, int(bbox[1] / self.CELL))
        r1 = min(self.rows - 1, int(bbox[3] / self.CELL))
        ink = chroma = rs = gs = bs = 0
        for row in range(r0, r1 + 1):
            base = row * self.cols
            for col in range(c0, c1 + 1):
                k = base + col
                ink += ink_g[k]
                chroma += chroma_g[k]
                rs += rsum[k]
                gs += gsum[k]
                bs += bsum[k]
        if not ink:
            return None, 0.0
        ratio = chroma / ink
        if ratio < self.min_ratio or not chroma:
            return None, ratio
        return to_hex((rs // chroma, gs // chroma, bs // chroma)), ratio
