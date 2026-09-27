#!/usr/bin/env python3
"""한 노트의 「① 사건의 전말」을 고치는 데 필요한 것을 한자리에 모은다.

블록마다 (가) 지금 쓰인 상황과 주장 (나) 사례집 지문 (다) 판시를 함께 낸다.
상황을 고치려면 세 개를 같이 봐야 한다.

    python3 전말덤프.py output/052_처분권주의.md
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 사실관계 import 문제모음, _뱃지, _사건번호

벗김 = lambda l: re.sub(r"^[>\s]*>", "", l) if l.lstrip().startswith(">") else l


def 본다(노트, 표, 폭=600):
    L = Path(노트).read_text(encoding="utf-8").split("\n")
    현재, 뱃지 = "?", []
    for i, line in enumerate(L):
        알맹이 = re.sub(r"^[>\s]*", "", line)
        m = _사건번호.match(알맹이)
        if m:
            현재 = m.group(1)
            뱃지 = []
            for j in range(i + 1, min(i + 5, len(L))):
                뱃지 += _뱃지.findall(L[j])
        if "**상황" not in line:
            continue
        blk = [벗김(line)]
        j = i + 1
        while j < len(L) and 벗김(L[j]).startswith("  ") and not re.match(r"\s*-\s\*\*", 벗김(L[j])):
            blk.append(벗김(L[j]))
            j += 1
        print(f"\n━━━ {현재}  {노트}:{i+1}  뱃지 {뱃지 or '없음'}")
        print("[지금]", " ".join(x.strip() for x in blk))
        for b in 뱃지:
            if b in 표 and len(표[b][2]) > 200:
                print(f"[지문 {b}] {표[b][2][:폭]}")
        판시 = []
        k = j
        while k < len(L) and k < j + 30:
            t = 벗김(L[k]).strip()
            if t.startswith(">") and not t.lstrip("> ").startswith("|"):
                판시.append(t.lstrip("> "))
            elif 판시 and t:
                break
            k += 1
        if 판시:
            print("[판시]", " ".join(판시)[:500])


if __name__ == "__main__":
    표 = 문제모음()
    for 노트 in sys.argv[1:]:
        본다(노트, 표)
