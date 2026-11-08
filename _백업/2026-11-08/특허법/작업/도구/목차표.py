#!/usr/bin/env python3
"""기본서 PDF 북마크로 논점 목차표(`references/기본서목차.tsv`)를 만든다.

변환(book2md)과 같은 방식으로 북마크를 깁는다 — `config-patent.yaml` 의
`outline_patch`·`outline_renumber`. 그래서 순번이 `출력/기본서/NNN_*.md` 와 같다.
원본 PDF 는 리포에 없으므로 PDF 가 있는 PC 에서 한 번 돌려 TSV 를 커밋한다.

    python3 목차표.py "F:/…/테마 특허법.pdf"

책쪽 = PDF 쪽 − 14 (PDF 49쪽 꼬리말이 35). 추록은 책쪽으로 가리킨다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 목차표, 기본서

리포 = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(리포 / "book2md"))
from book2md.config import load_config, profile          # noqa: E402
from book2md.split import patch_outline                   # noqa: E402

책쪽차 = 14


def main(pdf):
    import pymupdf
    cfg = load_config([리포 / "book2md" / "config.yaml", 리포 / "book2md" / "config-patent.yaml"])
    prof = profile(cfg, "textbook")
    lv = int(prof.get("outline_level", 2))
    with pymupdf.open(pdf) as doc:
        toc, 끝쪽 = doc.get_toc(), doc.page_count
    rows = patch_outline(toc, prof.get("outline_patch"), lv, bool(prof.get("outline_renumber")))
    out, 장 = [], ("", "")
    starts = [p for l, _, p in rows if l == lv]
    for l, 제목, 쪽 in rows:
        if l < lv:
            번, _, 이름 = 제목.partition("|")
            장 = (번.replace("CHAPTER", "").strip(), 이름.strip())
            continue
        if l != lv:
            continue
        k = len(out)
        끝 = (starts[k + 1] - 1) if k + 1 < len(starts) else 끝쪽
        번호, _, 이름 = 제목.partition(" ")
        out.append([f"{k + 1:03d}", f"{int(장[0]):02d}", 장[1], 번호, 이름.strip(),
                    str(쪽), str(max(쪽, 끝)), f"{쪽 - 책쪽차}-{max(쪽, 끝) - 책쪽차}"])
    # 변환물과 순번이 맞는지 — 어긋나면 북마크 깁기가 서로 다르다는 뜻이다
    for r in out:
        if not list(기본서.glob(f"{r[0]}_{r[3]}*.md")):
            sys.exit(f"출력/기본서 에 {r[0]}_{r[3]}… 이 없다 — config 와 변환물이 어긋난다")
    head = ["순번", "장", "장제목", "장내번호", "논점", "PDF시작", "PDF끝", "책쪽"]
    목차표.write_text("\n".join("\t".join(x) for x in [head] + out) + "\n", encoding="utf-8")
    print(f"{목차표} — 논점 {len(out)}개")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
