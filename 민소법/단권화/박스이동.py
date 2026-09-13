#!/usr/bin/env python3
"""노트 말미에 모여 있는 ☑ 박스를 소스의 자리로 되돌린다.

    from 박스이동 import 구조, 이동
    구조('output/045_소송물이론.md')                     현재 헤딩과 박스 위치
    이동('output/045_소송물이론.md', '예시', '## 3. 검토')  그 헤딩 블록 뒤로 옮긴다

- 박스 블록은 `#{1,3} ☑` 줄부터 **같거나 얕은 레벨의 다음 헤딩** 직전까지.
- 각주 정의(`[^N]:`)는 파일 끝에 남는다. 박스를 그 앞에서 떼어낸다.
- 옮긴 자리의 레벨에 맞게 박스와 그 안 헤딩을 함께 올리거나 내린다.
"""
import re
import sys

_H = re.compile(r"^(#{1,6})\s")
_각주 = re.compile(r"^\[\^[^\]]+\]:")


def _줄(path):
    return open(path, encoding="utf-8").read().split("\n")


def 구조(path):
    for i, l in enumerate(_줄(path), 1):
        if _H.match(l) or _각주.match(l):
            print(f"{i:5} {l[:88]}")


def _블록(L, start):
    """start 헤딩부터 같거나 얕은 다음 헤딩 직전까지."""
    lvl = len(_H.match(L[start]).group(1))
    j = start + 1
    while j < len(L):
        m = _H.match(L[j])
        if m and len(m.group(1)) <= lvl:
            break
        if _각주.match(L[j]):
            break
        j += 1
    # 뒤쪽 빈 줄과 구분선 정리
    while j - 1 > start and L[j - 1].strip() in ("", "---"):
        j -= 1
    return start, j, lvl


def 이동(path, 박스키, 앵커, 레벨=None):
    """박스키를 제목에 담은 ☑ 박스를 앵커 헤딩 블록 뒤로 옮긴다."""
    L = _줄(path)
    bi = [i for i, l in enumerate(L) if _H.match(l) and "☑" in l and 박스키 in l]
    if len(bi) != 1:
        print(f"❌ {path}: 박스 「{박스키}」 {len(bi)}개 — 키를 좁히십시오")
        return False
    bs, be, blvl = _블록(L, bi[0])
    블록 = L[bs:be]

    ai = [i for i, l in enumerate(L) if l.startswith(앵커)]
    if len(ai) != 1:
        print(f"❌ {path}: 앵커 「{앵커}」 {len(ai)}개")
        return False
    a = ai[0]
    if bs < a:
        print(f"❌ {path}: 박스가 앵커보다 앞에 있습니다")
        return False
    _, ae, alvl = _블록(L, a)

    새레벨 = 레벨 if 레벨 else alvl
    d = 새레벨 - blvl
    if d:
        블록 = [("#" * max(1, len(m.group(1)) + d) + l[len(m.group(1)):]) if (m := _H.match(l)) else l
                for l in 블록]

    # 떼어내고 끼워 넣는다 (뒤에서부터)
    나머지 = L[:bs] + L[be:]
    # 떼어낸 뒤 남은 구분선·빈 줄 정리
    while len(나머지) > bs and 나머지[bs].strip() == "" and bs > 0 and 나머지[bs - 1].strip() == "":
        del 나머지[bs]
    if bs < len(나머지) and 나머지[bs].strip() == "---" and bs > 0 and 나머지[bs - 1].strip() == "":
        # 박스만 있던 말미 섹션이면 앞 구분선도 지운다
        if bs + 1 >= len(나머지) or _각주.match(나머지[bs + 1].strip()) or 나머지[bs + 1].strip() == "":
            del 나머지[bs]
    새 = 나머지[:ae] + [""] + 블록 + 나머지[ae:]
    open(path, "w", encoding="utf-8").write("\n".join(새))
    print(f"✔ {path}: ☑{박스키} → {앵커} 뒤 (레벨 {blvl}→{새레벨})")
    return True


if __name__ == "__main__":
    구조(sys.argv[1])
