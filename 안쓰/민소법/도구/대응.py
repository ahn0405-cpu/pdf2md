#!/usr/bin/env python3
"""핸드북 사례 ↔ 도쓰 민소 논점 대응 — 글자 8개 묶음(8-gram) 겹침으로 짝을 찾는다.

    python 대응.py 2-5-3          그 사례와 가장 많이 겹치는 도쓰 자료 블록(논점 · [쟁점] · 두문자) 5개
    python 대응.py --논점 관할     도쓰 논점 이름에 「관할」이 든 블록마다 겹치는 핸드북 사례 3개

재료: ../OCR/핸드북/*.md (핸드북.py) · ../도쓰/[민소법] 안쓰 도쓰 자료.md.
핸드북 노트 암기장의 「도쓰 …」 줄과 도쓰 복사본의 「→ 핸드북 [사례 …] 〔+〕」 역링크를 다는 데 쓴다.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

여기 = Path(__file__).resolve().parent
민소법 = 여기.parent
N = 8


def 묶음(t):
    t = re.sub(r"[^가-힣]", "", t)
    return {t[i:i + N] for i in range(len(t) - N + 1)}


def 핸드북사례():
    사례 = {}
    for p in sorted((민소법 / "OCR" / "핸드북").glob("*.md")):
        cur = None
        for l in p.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^## \[사례 ([^\]]+)\]\s*(.*)$", l)
            if m:
                cur = m.group(1)
                사례[cur] = {"제목": m.group(2), "글": ""}
                continue
            if cur:
                m2 = re.match(r"<!-- p\.(\d+)", l)
                if m2 and "쪽" not in 사례[cur]:
                    사례[cur]["쪽"] = m2.group(1)
                사례[cur]["글"] += l
    return 사례


def 도쓰블록():
    """도쓰 자료 → [(논점, 쟁점 머리줄, 글)] — 쟁점 머리 = `[..]` 또는 `(..)` 로 시작하는 줄."""
    p = 민소법 / "도쓰" / "[민소법] 안쓰 도쓰 자료.md"
    블록, 논점, 머리, 글 = [], "", "", ""
    for l in p.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^#### (<[^>]+>)", l)
        if m or re.match(r"^\*{0,2}[\[(（{]", l):
            if 글:
                블록.append((논점, 머리, 글))
            if m:
                논점, 머리, 글 = m.group(1), "", ""
            else:
                머리, 글 = l.strip()[:60], ""
            continue
        글 += l
    if 글:
        블록.append((논점, 머리, 글))
    return 블록


def main(argv):
    사례 = 핸드북사례()
    블록 = 도쓰블록()
    if "--논점" in argv:
        k = argv[argv.index("--논점") + 1]
        사례묶음 = {n: 묶음(v["글"]) for n, v in 사례.items()}
        for 논점, 머리, 글 in 블록:
            if k not in 논점:
                continue
            g = 묶음(글)
            순 = sorted(((len(g & s), n) for n, s in 사례묶음.items()), reverse=True)[:3]
            print(f"{논점} {머리[:40]}  →  " + " · ".join(f"[{n}] p.{사례[n].get('쪽', '?')}({c})" for c, n in 순 if c))
        return
    n = argv[0]
    if n not in 사례:
        sys.exit(f"[사례 {n}] 이 OCR 원문에 없다 — 핸드북 목차에서 시작 쪽을 못 찾은 사례일 수 있다")
    s = 묶음(사례[n]["글"])
    순 = sorted(((len(s & 묶음(글)), 논점, 머리) for 논점, 머리, 글 in 블록), reverse=True)[:5]
    print(f"[사례 {n}] {사례[n]['제목']} (p.{사례[n].get('쪽', '?')})")
    for c, 논점, 머리 in 순:
        print(f"  {c:4d}  {논점} {머리}")


if __name__ == "__main__":
    main(sys.argv[1:])
