#!/usr/bin/env python3
"""GS 쪽 ↔ 준특허법(기본서) 쪽 대응 — 글자 8개 묶음(8-gram) 겹침으로 가장 비슷한 기본서 쪽·절을 찾는다.

    python 대응.py 4        4회차 해설 쪽마다 기본서 후보 3개 (절 · 책 쪽 · 겹침 수)

재료: 안쓰/_work/박형준/p###.json (gs_ocr.py) · 안쓰/_work/준특허법/줄.json (기본서.py).
둘 다 OCR 이라 오타가 있지만 겹치는 묶음이 많으면 같은 문장이다. 암기장의 「기본서 2.3.1 … (p.22)」를 다는 데 쓴다.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

여기 = Path(__file__).resolve().parent
작업 = 여기.parent.parent / "_work"
sys.path.insert(0, str(여기))
from gs_초안 import 회차쪽  # noqa: E402

N = 8


def 묶음(t):
    t = re.sub(r"[^가-힣]", "", t)
    return {t[i:i + N] for i in range(len(t) - N + 1)}


def main(argv):
    회 = int(argv[0])
    줄 = json.loads((작업 / "준특허법" / "줄.json").read_text(encoding="utf-8"))
    쪽글 = defaultdict(str)
    쪽절 = {}
    for r in 줄:
        쪽글[r["pdf"]] += r["글"]
        쪽절.setdefault(r["pdf"], (r["절"], r["쪽"]))
    색인 = defaultdict(set)
    for pdf, t in 쪽글.items():
        for g in 묶음(t):
            색인[g].add(pdf)
    for no in 회차쪽(회):
        d = json.loads((작업 / "박형준" / f"p{no:03d}.json").read_text(encoding="utf-8"))
        글 = "".join(l["text"] for l in d["lines"])
        표 = Counter()
        for g in 묶음(글):
            for pdf in 색인.get(g, ()):
                표[pdf] += 1
        첫 = d["lines"][0]["text"][:30] if d["lines"] else ""
        후보 = " · ".join(f"{쪽절[p][0] or '?'} p.{쪽절[p][1]}({k})" for p, k in 표.most_common(3))
        print(f"GS p{no:3d}  {첫:30s}  {후보}")


if __name__ == "__main__":
    main(sys.argv[1:])
