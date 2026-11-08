#!/usr/bin/env python3
"""GS 쪽을 컬러 그림으로 — 교정할 때 Claude 가 읽는 용도(92dpi 한 장이면 한 쪽이 읽힌다).

    python 쪽그림.py 89 102        → 안쓰/_work/박형준/그림/h089.png … h102.png (커밋 안 함)
"""
import sys
from pathlib import Path

import fitz

여기 = Path(__file__).resolve().parent
PDF = 여기.parent / "원본" / "26년 박형준 기초 gs.pdf"
출력 = 여기.parent.parent / "_work" / "박형준" / "그림"


def main(argv):
    a, b = int(argv[0]), int(argv[1])
    출력.mkdir(parents=True, exist_ok=True)
    d = fitz.open(PDF)
    for n in range(a, b + 1):
        r = d[n - 1].rect
        d[n - 1].get_pixmap(dpi=92, clip=fitz.Rect(45, 40, r.width - 45, r.height - 45)).save(출력 / f"h{n:03d}.png")
    print(f"{출력}  h{a:03d}～h{b:03d}")


if __name__ == "__main__":
    main(sys.argv[1:])
