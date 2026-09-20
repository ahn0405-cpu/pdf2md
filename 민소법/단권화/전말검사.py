#!/usr/bin/env python3
"""「① 사건의 전말」이 제 몫을 하는지 검사한다.

세 가지를 본다.
  ①없음     ② 판례의 태도 앞에 ①이 아예 없다 (골격 위반)
  甲乙없음   상황에 등장인물이 없다 → 사례가 아니라 요건 서술이다
  안나뉨     「상황」과 「주장과 소 제기」를 한 항목에 합쳤다
"""
import re
import sys
import glob

벗김 = lambda l: re.sub(r"^[>\s]*>", "", l) if l.lstrip().startswith(">") else l
_태도 = re.compile(r"^[>\s]*(#{2,6})\s*②\s*판례의 태도")
_헤딩 = re.compile(r"^[>\s]*(#{2,6})\s")


def 본다(p):
    L = open(p, encoding="utf-8").read().split("\n")
    없음, 무인물, 안나뉨 = [], [], []
    for i, l in enumerate(L):
        m = _태도.match(l)
        if not m:
            continue
        # ②와 같거나 얕은 헤딩까지 거슬러 올라간다 — 그 사이가 이 판례의 ①이다
        j = i - 1
        while j >= 0:
            h = _헤딩.match(L[j])
            if h and len(h.group(1)) <= len(m.group(1)) and "①" not in L[j]:
                break
            j -= 1
        구역 = L[j + 1 : i]
        if not any("① 사건의 전말" in x for x in 구역):
            없음.append(i + 1)
            continue
        상황 = [k for k, x in enumerate(구역) if re.search(r"\*\*상황(과 주장)?\*\*", x)]
        if not 상황:
            없음.append(i + 1)
            continue
        k = 상황[0]
        blk = [벗김(구역[k])]
        n = k + 1
        while n < len(구역) and 벗김(구역[n]).startswith("  ") and not re.match(r"\s*-\s\*\*", 벗김(구역[n])):
            blk.append(벗김(구역[n]))
            n += 1
        t = " ".join(blk)
        if not re.search(r"[甲乙丙丁戊ABKXY]", t):
            무인물.append(i + 1)
        if "**상황과 주장**" in t:
            안나뉨.append(i + 1)
    return 없음, 무인물, 안나뉨


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(glob.glob("output/*.md"))
    합 = [0, 0, 0, 0]
    print(f'{"파일":36} 판례  ①없음  甲乙없음  안나뉨')
    for p in files:
        없음, 무인물, 안나뉨 = 본다(p)
        n = len(없음) + sum(1 for _ in re.finditer(r"② 판례의 태도", open(p, encoding="utf-8").read()))
        cnt = sum(1 for l in open(p, encoding="utf-8") if _태도.match(l))
        합[0] += cnt; 합[1] += len(없음); 합[2] += len(무인물); 합[3] += len(안나뉨)
        if 없음 or 무인물 or 안나뉨:
            print(f'{p.replace("output/","")[:34]:36} {cnt:4} {len(없음):6} {len(무인물):8} {len(안나뉨):7}')
    print(f'\n합계  판례 {합[0]}  ①없음 {합[1]}  甲乙없음 {합[2]}  안나뉨 {합[3]}')
