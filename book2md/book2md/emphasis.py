"""표준판례 판시 문단만 그림으로 떠 둔다 (§P0-2 폴백).

색을 픽셀에서 읽는 것이 끝내 안 될 때를 위한 마지막 수단이다. 전부를
포기하더라도 표준판례(별표) 판시만은 확보해야 한다 — 저자가 색으로 지정해
둔 답안 현출 범위가 거기 있기 때문이다.

그림과 함께 뽑힌 글자를 나란히 실어, 사람이 보고 강조 범위를 손으로 표시할
수 있게 한다. **프로그램이 대신 정하지 않는다.**
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_MARKUP = re.compile(r"(?:==|\*\*|`)")


def crops(blocks, pdf_path, out_dir, cfg, pages=None) -> tuple[int, Path | None]:
    """표준판례가 있는 문단을 잘라 낸다. (뜬 그림 수, 목록 파일)

    pages 를 주면 그 쪽들만 본다 (§V3 이 얇다고 짚은 쪽).
    """
    src = Path(pdf_path) if pdf_path else None
    if not src or not src.exists():
        return 0, None
    rc = cfg.get("report", {})
    limit = int(rc.get("max_emphasis_crops", 60))
    dpi = int(rc.get("page_image_dpi", 130))
    pad = float(rc.get("crop_padding", 6))
    want = set(pages or [])

    targets = []
    for b in blocks:
        page = int(getattr(b, "page", 0) or 0)
        if not page or (want and page not in want):
            continue
        std = [c["id"] for c in (b.cases or []) if c.get("standard")]
        if not std:
            continue
        text = _MARKUP.sub("", b.text or "").strip()
        if len(text) < 10:
            continue
        targets.append((page, std, text))
    if not targets:
        return 0, None

    try:
        import pymupdf
    except ImportError:                                # pragma: no cover
        return 0, None

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, made = [], 0
    with pymupdf.open(str(src)) as doc:
        for page_no, std, text in targets[:limit]:
            if not (1 <= page_no <= doc.page_count):
                continue
            page = doc[page_no - 1]
            rect = _band(page, text) or page.rect
            name = f"p{page_no:04d}_{made + 1:02d}.png"
            page.get_pixmap(dpi=dpi, clip=rect).save(str(out / name))
            rows.append({"page": page_no, "image": name, "cases": std, "text": text})
            made += 1

    index = out / "index.md"
    L = ["# 표준판례 판시 — 강조를 손으로 표시할 것 (§P0-2 폴백)", "",
         "색을 픽셀에서 읽지 못한 쪽이다. 그림을 열어 저자가 칠해 둔 범위를 보고,",
         "아래 글자에 `==` 를 손으로 둘러 `config.yaml` 의 `corrections:` 로 넣거나",
         "결과 마크다운을 직접 고칠 것. **프로그램은 판정하지 않았다.**", ""]
    for r in rows:
        L.append(f"## p.{r['page']} — {', '.join(r['cases'])}")
        L.append("")
        L.append(f"![p{r['page']}]({r['image']})")
        L.append("")
        L.append("```")
        L.append(r["text"])
        L.append("```")
        L.append("")
    index.write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "index.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return made, index


def _band(page, text):
    """문단이 놓인 자리를 찾는다. 못 찾으면 None (쪽 전체를 뜬다)."""
    for needle in _needles(text):
        try:
            hits = page.search_for(needle)
        except Exception:                              # pragma: no cover
            continue
        if not hits:
            continue
        box = hits[0]
        # 문단 끝까지 담기게 아래로 넉넉히 늘린다. 폭은 쪽 전체를 쓴다.
        lines = max(1, len(text) // 34 + 1)
        top = max(page.rect.y0, box.y0 - box.height)
        bottom = min(page.rect.y1, box.y0 + box.height * (lines + 1.5))
        return page.rect.__class__(page.rect.x0, top, page.rect.x1, bottom)
    return None


def _needles(text: str) -> list[str]:
    """찾아볼 글자 후보들.

    스캔본 OCR 레이어에는 낱말 사이 공백이 없다. 정규화가 넣어 준 공백을 그대로
    들고 찾으면 한 건도 안 걸린다. 그래서 붙인 꼴을 먼저 시도한다. 괄호·별표는
    OCR 이 흘린 자리라 후보에서 뺀다.
    """
    plain = re.sub(r"[\s()\[\]＜＞*·,.]", "", text)
    out = [plain[:10], plain[:6]]
    chunks = [c.strip("().,·*") for c in re.split(r"\s+", text)]
    chunks = [c for c in chunks if len(c) >= 3 and not re.search(r"[0-9()]", c)]
    if chunks:
        out.append(chunks[0][:10])
        if len(chunks) > 1:
            out.append(" ".join(chunks[:2])[:16])
    return [n for n in dict.fromkeys(out) if len(n) >= 3]
