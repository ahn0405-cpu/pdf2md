#!/usr/bin/env python3
"""안쓰 노트 마크다운 형식 점검 — VS Code 미리보기(CommonMark)에서 이상하게 보일 곳을 찾는다.

    python 형식점검.py                     안쓰/ 아래 노트 전부(`[과목] 안쓰 … .md`, 빈칸채우기·빈칸정답 제외)
    python 형식점검.py <파일> [<파일> …]   그 파일만
    python 형식점검.py --자세히 …          규칙마다 모든 줄을 보인다(기본은 5줄까지)

찾는 것 (오 = 고쳐야 함, 주의 = 보고 판단):
  오   붙음        빈 줄 없이 이어진 글 줄 — 미리보기에서 앞 줄과 한 문단(한 줄)로 붙는다
  오   6단계머리   `######` — 본문보다 작고 흐리게 나온다
  오   빈줄여럿    빈 줄 두 개 이상 — 쓸데없는 간격
  오   줄끝공백    줄 끝 공백·탭
  오   코드블록    목록 밖에서 4칸 이상 들여쓴 줄 — 회색 코드 상자로 나온다
  주의 머리단계    같은 역할의 머리([사례 …] · <도쓰> · 설문(n) · 2-N 주제)가 파일 안에서 다른 단계 — 같은 것이 다른 크기
  주의 건너뜀      머리 단계를 건너뛴다(## 다음 ####). 같은 논점 머리를 같은 단계로 두려고 일부러 건너뛴 것이면 그대로 둔다
  주의 긴머리      머리 글자가 50자를 넘는다(기출 [..] · 〔..〕 · (p.) 는 빼고) — 문장이 큰 굵은 글씨로 나온다(소제목은 짧게, 문장은 본문으로)
  주의 넓은목록    같은 `-` 목록 항목 사이 빈 줄 — 항목마다 문단 간격이 생겨 벌어진다
고칠 때 도쓰 원문을 그대로 옮긴 칸(<!-- … 그대로 옮김 … --> 아래)은 내용은 그대로 두고 간격만 고친다.
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

여기 = Path(__file__).resolve().parent
안쓰 = 여기.parent.parent

머리식 = re.compile(r"^(#{1,6})\s+(.*)$")
글머리식 = re.compile(r"^(\s*)([-*+])(\s+)(.*)$")
번호식 = re.compile(r"^(\s*)(\d{1,9})([.)])(\s+)(.*)$")
긴머리 = 50


def 종류(제목):
    if re.match(r"\[사례 ", 제목):
        return "[사례 …]"
    if 제목.startswith("<도쓰>"):
        return "<도쓰>"
    if re.match(r"설문\s*\(?\d", 제목):
        return "설문(n)"
    if re.match(r"\d-\d+ ", 제목):
        return "2-N 주제"
    return None


def 점검(p):
    줄들 = p.read_text(encoding="utf-8").split("\n")
    문제 = defaultdict(list)
    앞 = "빈"            # 빈 · 머리 · 글 · 목록 · 인용 · 표 · 주석
    목록 = []            # 열린 목록 항목들의 (들여쓰기, 내용 시작 칸)
    빈줄수 = 0
    울타리 = False
    주석중 = False
    머리단계 = 0
    종류단계 = defaultdict(set)
    빈뒤목록 = None      # 빈 줄 바로 앞이 목록 항목이었으면 그 들여쓰기

    for 번, 줄 in enumerate(줄들, 1):
        if 줄.rstrip() != 줄:
            문제["줄끝공백"].append(번)
        if 줄.strip().startswith("```"):
            울타리 = not 울타리
            앞, 빈줄수 = "글", 0
            continue
        if 울타리:
            continue
        if 주석중:
            if "-->" in 줄:
                주석중 = False
            continue
        if not 줄.strip():
            빈줄수 += 1
            if 빈줄수 == 2:
                문제["빈줄여럿"].append(번)
            if 앞 == "목록":
                빈뒤목록 = 목록[-1][0] if 목록 else None
            elif 앞 != "빈":
                빈뒤목록 = None
            앞 = "빈" if 앞 != "목록" else "빈(목록 뒤)"
            continue
        뒤가빈 = 앞.startswith("빈")
        빈줄수 = 0
        들여 = len(줄) - len(줄.lstrip(" "))

        if 줄.lstrip().startswith("<!--"):
            if "-->" not in 줄:
                주석중 = True
            앞 = "주석"
            continue

        m = 머리식.match(줄)
        if m and 들여 < 4:
            단 = len(m.group(1))
            제목 = re.sub(r"[*`]", "", m.group(2)).strip()
            본제목 = re.sub(r"\[[^\]]*\]|〔[^〕]*〕|\(p\.[^)]*\)", "", 제목).strip()   # 기출·표시·쪽은 빼고 잰다
            if 단 == 6:
                문제["6단계머리"].append(번)
            if 머리단계 and 단 > 머리단계 + 1:
                문제["건너뜀"].append(번)
            if len(본제목) > 긴머리:
                문제["긴머리"].append(번)
            k = 종류(제목)
            if k:
                종류단계[k].add((단, 번))
            머리단계 = 단
            앞, 목록 = "머리", []
            continue

        if 줄.lstrip().startswith(">"):
            앞, 목록 = "인용", []
            continue
        if 줄.lstrip().startswith("|"):
            앞 = "표"
            continue

        g = 글머리식.match(줄)
        n = 번호식.match(줄)
        if g or n:
            if n:
                마크폭 = len(n.group(2)) + 1
                내용칸 = 들여 + 마크폭 + min(len(n.group(4)), 4)
                if 앞 == "글" and n.group(2) != "1" and not 목록:
                    문제["붙음"].append(번)      # 1 이 아닌 번호 목록은 문단을 끊지 못한다
                    continue
            else:
                내용칸 = 들여 + 1 + min(len(g.group(3)), 4)
            while 목록 and 들여 < 목록[-1][0]:      # 더 얕으면 깊은 항목을 닫는다
                목록.pop()
            if 목록 and 들여 < 목록[-1][1]:          # 내용 칸보다 얕으면 형제 항목
                if 뒤가빈 and 빈뒤목록 is not None and g:      # 「1) … 2) …」 번호 문단은 일부러 띄운 꼴
                    문제["넓은목록"].append(번)
                목록[-1] = (들여, 내용칸)
            elif 목록 and 들여 >= 목록[-1][1] + 4:
                문제["코드블록"].append(번)
            elif 목록:                                # 내용 칸 이상이면 하위 항목
                목록.append((들여, 내용칸))
            else:
                if 들여 >= 4:
                    문제["코드블록"].append(번)
                목록.append((들여, 내용칸))
            앞 = "목록"
            continue

        # 보통 글 줄
        if not 목록 and 들여 >= 4 and 뒤가빈:
            문제["코드블록"].append(번)
        이어씀 = 목록 and 들여 >= 목록[-1][1]          # 목록 항목을 들여서 이어 쓴 줄 — 일부러 줄바꿈한 것
        if 앞 in ("글", "목록") and not 이어씀 and not 줄들[번 - 2].endswith(("  ", "\\")):
            문제["붙음"].append(번)
        if 뒤가빈 and 목록 and 들여 < 목록[-1][1]:
            목록 = []
        앞 = "글"

    for k, s in 종류단계.items():
        단들 = {단 for 단, _ in s}
        if len(단들) > 1:
            많은 = max(단들, key=lambda d: sum(1 for x, _ in s if x == d))
            문제["머리단계"] += [번 for 단, 번 in s if 단 != 많은]
            문제.setdefault("_머리단계설명", []).append(f"{k}: " + " · ".join(f"{'#' * d} {sum(1 for x, _ in s if x == d)}개" for d in sorted(단들)))
    return 줄들, 문제


순서 = ["붙음", "6단계머리", "빈줄여럿", "줄끝공백", "코드블록", "건너뜀", "머리단계", "긴머리", "넓은목록"]
주의 = {"건너뜀", "머리단계", "긴머리", "넓은목록"}


def main(argv):
    자세히 = "--자세히" in argv
    파일 = [Path(a) for a in argv if not a.startswith("--")]
    if not 파일:
        파일 = sorted(p for p in 안쓰.rglob("*.md")
                    if re.match(r"\[.+\] 안쓰 ", p.name) and "빈칸" not in p.name and "_work" not in p.parts)
    오합 = 0
    for p in 파일:
        줄들, 문제 = 점검(p)
        오 = sum(len(문제[k]) for k in 순서 if k not in 주의)
        주 = sum(len(문제[k]) for k in 주의)
        오합 += 오
        print(f"{'✗' if 오 else ('△' if 주 else '✓')} {p.relative_to(안쓰) if p.is_relative_to(안쓰) else p}  오 {오} · 주의 {주}")
        for k in 순서:
            if not 문제[k]:
                continue
            표 = "주의" if k in 주의 else "오"
            print(f"    {표} {k} {len(문제[k])}")
            if k == "머리단계":
                for s in 문제["_머리단계설명"]:
                    print(f"        {s}")
            for 번 in (문제[k] if 자세히 else 문제[k][:5]):
                print(f"        {번:>5}: {줄들[번 - 1][:70]}")
            if not 자세히 and len(문제[k]) > 5:
                print(f"        … {len(문제[k]) - 5}줄 더 (--자세히)")
    sys.exit(1 if 오합 else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
