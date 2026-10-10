#!/usr/bin/env python3
"""목차집(`노트/목차집/CH*.md`)의 논점을 쓸 재료를 한자리에 모으고, 쓴 것을 검사한다.

목차집은 장 파일에 손으로 쓴다 — 개조식 목차(학설·判·두문자)와 사례 줄(사례집 목차 순서·배점).
작성 원칙은 `작업/references/목차집.md`. 재료는 네 군데에 흩어져 있다.

    1 노트 목차       판례 블록을 뺀 헤딩 트리. 기출·두문자·☑, 아래 판례의 뱃지
    2 의의            I. 의의 의 인용문 (기본서 원문)
    3 학설            학설 절 표의 견해 칸
    4 사례집 답안 목차 뱃지가 가리키는 문제의 ###·#### 헤딩과 배점

사례집은 **목차 제목과 배점만** 본다. 답안 본문은 읽지 않는다(SKILL.md 와 같은 선).

    python3 목차재료.py 046        재료
    python3 목차재료.py --검사     목차집에 없는 논점 · 노트에 없는 두문자
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 기본서, 사례집, 노트, 목차집, 노트들

_헤딩 = re.compile(r"^(#{1,6})\s+(.*)$")
_뱃지 = re.compile(r"`([A-Q]-\d+)`")
_사건 = re.compile(r"\d{2,4}\s?[가-힣]{1,3}\s?\d{1,6}")
_번호머리 = re.compile(r"^(?:[ivx]+\)|\d+\)|\(\d+\)|\d+\.|[IVX]+\.|[①-⑳])\s*")


def 판례헤딩(t):
    """사건번호만 남는 헤딩 — `#### i) [일반] 84다552` 따위."""
    t = re.sub(r"<!--.*?-->|`[^`]*`|\[[^\]]*\]|☑", "", t)
    t = _번호머리.sub("", t.strip()).strip()
    return bool(_사건.fullmatch(t))


def 목차(L):
    """판례 블록을 뺀 헤딩 트리. 판례의 뱃지는 가장 가까운 남은 조상에 붙인다."""
    줄 = []          # [수준, 글, 뱃지 목록]
    스택 = []        # 남은 헤딩의 (수준, 줄 번호)
    for i, l in enumerate(L):
        m = _헤딩.match(l)
        if not m:
            continue
        lv, t = len(m.group(1)), m.group(2).strip()
        if t[:1] in "①②③":
            continue
        if 판례헤딩(t):
            뱃지 = [b for x in L[i + 1:i + 5] for b in _뱃지.findall(x)]
            while 스택 and 스택[-1][0] >= lv:
                스택.pop()
            if 스택 and 뱃지:
                줄[스택[-1][1]][2] += [b for b in 뱃지 if b not in 줄[스택[-1][1]][2]]
            continue
        while 스택 and 스택[-1][0] >= lv:
            스택.pop()
        스택.append((lv, len(줄)))
        줄.append([lv, re.sub(r"<!--.*?-->", "", t).strip(), []])
    for lv, t, 뱃지 in 줄:
        print(f"{'  ' * (lv - 1)}{t}" + (f"   ← {' '.join(뱃지)}" if 뱃지 else ""))


def 의의(L):
    """제목에 「의의」가 든 절의 첫 인용 블록. 인용이 없으면 첫 문단."""
    for i, l in enumerate(L):
        m = _헤딩.match(l)
        if not (m and "의의" in m.group(2)):
            continue
        절 = []
        for x in L[i + 1:]:
            if _헤딩.match(x):
                break
            절.append(x)
        블록 = []
        for x in 절:
            if x.startswith(">"):
                블록.append(x.lstrip("> ").rstrip())
            elif 블록:
                break
        if not 블록:
            for x in 절:
                if x.strip():
                    블록.append(x.strip())
                elif 블록:
                    break
        if 블록:
            print(f"[{m.group(2).strip()}]")
            print("  " + " ".join(블록))


def 학설(L):
    """학설 절 표의 견해 칸 — 판례가 어느 견해인지는 노트의 判例 절로 맞춘다."""
    for i, l in enumerate(L):
        m = _헤딩.match(l)
        if not (m and "학설" in m.group(2)):
            continue
        견해 = []
        for x in L[i + 1:]:
            if _헤딩.match(x):
                break
            if x.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", x):
                칸 = [c.strip() for c in x.strip("|").split("|")]
                if 칸[0] and 칸[0] not in ("견해", "학설", ""):
                    견해.append(칸[0])
        print(f"[{i + 1}행 {m.group(2).strip()}] " + (" / ".join(견해) if 견해 else "(표 없음)"))


def 답안목차표():
    """사례집 문제번호 → (파일, 제목, [목차 헤딩]). 목차 쪽과 본문 쪽 중 헤딩이 많은 것."""
    표 = {}
    for p in sorted(사례집.glob("*.md")):
        번호 = None
        for l in p.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^##\s+([A-Q]-\d+)\.\s*(.*)$", l)
            if m:
                번호 = m.group(1)
                지금 = (p.name, m.group(2).strip(), [])
                if 번호 not in 표 or not 표[번호][2]:
                    표[번호] = 지금
                continue
            # 「⑴ 학설 i) …」처럼 헤딩이 본문 줄로 흘러내린 목차가 있다 — 제목 한 낱말만 잡는다
            흘림 = re.match(r"^([⑴-⒇])\s*(\S+)", l) if 번호 else None
            if 번호 and (re.match(r"^#{3,4}\s", l) or 흘림):
                if 흘림:
                    l = f"#### ({ord(흘림.group(1)) - 0x2473}) {흘림.group(2)} …"
                if 표[번호] is not 지금 and len(지금[2]) >= len(표[번호][2]):
                    표[번호] = 지금
                지금[2].append(l)
    return 표


def 사례(L, 표):
    본것 = []
    for l in L:
        본것 += [b for b in _뱃지.findall(l) if b not in 본것]
    if not 본것:
        print("(뱃지 없음 — 사례 줄은 쓰지 않는다)")
    for b in 본것:
        if b not in 표:
            print(f"\n{b}  (사례집에 없음)")
            continue
        파일, 제목, 헤딩 = 표[b]
        print(f"\n{b}  {제목}  [{파일}]")
        for h in 헤딩:
            lv = len(h) - len(h.lstrip("#"))
            print(f"{'  ' * (lv - 2)}{h.lstrip('#').strip()}")


def 머리말(번호):
    cands = sorted(기본서.glob(f"*_{번호}*.md"))
    if not cands:
        return
    s = cands[0].read_text(encoding="utf-8")[:4000]
    for 키 in ("chapter", "exam_years", "outline", "mnemonics", "articles", "bonus_topics"):
        m = re.search(rf"^{키}:\s*(.*)$", s, re.M)
        if m:
            print(f"{키:12} {m.group(1)}")


def 본다(노트, 표):
    L = Path(노트).read_text(encoding="utf-8").split("\n")
    번호 = Path(노트).name[:3]
    print(f"\n{'━' * 60}\n{Path(노트).name}\n{'━' * 60}")
    print("\n── 기본서 머리말")
    머리말(번호)
    print("\n── 1 노트 목차 (판례 블록 제외, ← 아래 판례의 뱃지)")
    목차(L)
    print("\n── 2 의의")
    의의(L)
    print("\n── 3 학설")
    학설(L)
    print("\n── 4 사례집 답안 목차 (제목과 배점만)")
    사례(L, 표)


def 검사():
    """목차집에 아직 없는 논점, 목차집의 두문자 중 단권화 노트에 없는 것(오기를 잡는다)."""
    from 암기노트 import 장
    _두문자 = re.compile(r"`(\[[^\]`]+\])`")
    쓴것 = {}
    for p in sorted(목차집.glob("CH*.md")):
        조각 = re.split(r"^# (\d{3})\b", p.read_text(encoding="utf-8"), flags=re.M)
        for n, 글 in zip(조각[1::2], 조각[2::2]):
            쓴것[n] = (p.name, 글)
    없음 = 0
    for 번, _, 첫, 끝 in 장:
        for q in sorted(노트.glob("*.md")):
            n = q.name[:3]
            if not (n.isdigit() and 첫 <= int(n) <= 끝):
                continue
            if n not in 쓴것:
                print(f"  없음     {n}  (CH{번})")
                없음 += 1
                continue
            본문 = re.sub(r"\s", "", q.read_text(encoding="utf-8"))
            for d in _두문자.findall(쓴것[n][1]):
                if re.sub(r"\s", "", d) not in 본문:
                    print(f"  두문자?  {n}  {d}  ({쓴것[n][0]} — 노트에 없다)")
    print(f"\n목차집 논점 {len(쓴것)}  ·  아직 없음 {없음}")


if __name__ == "__main__":
    if "--검사" in sys.argv:
        검사()
    else:
        표 = 답안목차표()
        for p in 노트들():
            본다(p, 표)
