#!/usr/bin/env python3
"""[특허법] 안쓰 GS 자료.md → 빈칸채우기 + 빈칸정답 + 플래시카드(.txt) (모두 뽑는 파일 — 손으로 고치지 않는다).

    python 빈칸채우기.py           뽑는다
    python 빈칸채우기.py --검사    빈칸 없는 판례 문장 · 60자 넘는 빈칸 · 빈칸 ↔ 정답 개수
    python 빈칸채우기.py --자료 "<…/[민소법] 안쓰 핸드북 자료.md>"   다른 자료(이름의 「자료」를 「빈칸채우기」「빈칸정답」「플래시카드」로 바꿔 쓴다)
    판례 줄에 `<!-- … 빈칸 없음 -->` 이 있으면 검사에서 뺀다(민소 핸드북: 도쓰·★·표준에 해당하지 않는 판례).
    python 빈칸채우기.py --번호머리 5 --자료 "<…/[민소법] 안쓰 핸드북 자료 제2편.md>"
                                  민소 핸드북 — 번호를 `##` ～ `#####`(사례·설문·<도쓰> 칸) 머리마다 1부터. 기본은 3(`##`·`###`, GS).

- 자료의 **굵은 말**(= GS 판례·조문·취지 형광펜 구절)을 (1 ＿＿＿ ＿)로 가린다 — 괄호 안 맨 앞이 빈칸 번호(본문 목록 ①과 겹치지 않게, 흰 바탕), 정답 글자 수만큼 ＿, 띄어쓰기는 그대로(단어 수가 보이게, 필기할 자리). 번호는 설문(`###`)마다 1부터.
- 정답은 **따로** `[특허법] 안쓰 GS 빈칸정답.md` 에 같은 문제·설문 머리 아래 — 빈칸채우기에는 정답이 없다(먼저 보지 않게).
- 문장에 〔두음〕(기본서 두음)이 없으면 빈칸 머리글자로 힌트 〔…〕 를 붙인다.
- 굵은 말이 통째로 `(…)` 인 두문자 표지(도쓰 `**(지변정)**`)는 빈칸이 아니라 힌트 〔지변정〕 로 바꾼다.
- 검사에서 `<도쓰>` 칸(도쓰 원문을 그대로 옮긴 곳)의 굵은 말 없는 판례 줄은 세지 않는다.
- `<!-- … -->` 주석은 뺀다.
- 플래시카드 = 휴대폰 앱 Flashcards Deluxe 덱(탭 구분 UTF-8 .txt, 머리줄 `Text 1 Text 2 Category 1 Category 2`).
  소제목(가장 깊은 `#` 머리 · `▸ …` · `[논점]`) 하나 = 카드 한 장. 앞 = 빈칸(카드마다 1부터), 뒤 = 정답 <b>굵게</b>.
  분류1 = `##`(회차·문제 / 장), 분류2 = `###`(설문 / 절). `|` = 앱의 줄바꿈.
"""
import re
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
폴더 = 여기.parent / "박형준GS"
자료 = 폴더 / "[특허법] 안쓰 GS 자료.md"
빈칸 = 폴더 / "[특허법] 안쓰 GS 빈칸채우기.md"
정답 = 폴더 / "[특허법] 안쓰 GS 빈칸정답.md"
카드 = 폴더 / "[특허법] 안쓰 GS 플래시카드.txt"

_굵 = re.compile(r"\*\*([^*]+)\*\*")
_두음 = re.compile(r"〔([^〕]+)〕")
최대 = 60
번호머리 = 3          # 이 단계 이하의 머리(## ～ #×번호머리)에서 번호를 1부터 다시 센다
_표지 = re.compile(r"\*\*\(([^*()]+)\)\*\*")
_빈칸 = re.compile(r"\(\d+ [＿ ]+\)")


def 밑줄(w):
    """정답 글자 수만큼 ＿(전각) — 단어 사이 띄어쓰기는 그대로."""
    return " ".join("＿" * len(t) for t in w.split())


def 머리인가(line):
    m = re.match(r"^(#{2,6}) ", line)
    return bool(m) and len(m.group(1)) <= 번호머리


def 뽑기(본문):
    문, 답 = [], []
    설문답, n = [], 0
    머리끝 = False

    def 정답내기():
        if 설문답:
            답.extend([" · ".join(f"{i} {w}" for i, w in 설문답), ""])

    for line in 본문.split("\n"):
        line = re.sub(r"\s*<!--.*?-->", "", line)
        if not 머리끝:
            if line.startswith("## "):
                머리끝 = True
            else:
                continue
        if 머리인가(line):
            정답내기()
            설문답, n = [], 0
            문.append(line)
            답.append(line)
            if line.startswith("## "):
                답.append("")
            continue
        line = _표지.sub(lambda m: f"〔{m.group(1)}〕", line)
        낱말 = _굵.findall(line)
        if 낱말:
            힌트 = "".join(w.lstrip("(法 ")[0] for w in 낱말)

            def 가림(m):
                nonlocal n
                n += 1
                설문답.append((n, m.group(1)))
                return f"({n} {밑줄(m.group(1))})"
            line = _굵.sub(가림, line)
            if not _두음.search(line):
                line = line.rstrip() + f" 〔{힌트}〕"
        문.append(line)
    정답내기()
    머리 = lambda 이름, 설명: f"# {이름}\n\n{설명}\n\n<!-- 빈칸채우기.py 가 「{자료.name}」에서 뽑는다 — 손으로 고치지 않는다. -->\n\n"
    문서 = 머리(빈칸.stem,
              f"자료의 굵은 말을 가렸다. ＿ 하나 = 한 글자, 띄어쓰기 = 단어 사이. 〔 〕 = 힌트(두음 또는 빈칸 머리글자). **정답은 `{정답.name}`** 에.") + "\n".join(문)
    답서 = 머리(정답.stem, f"`{빈칸.name}` 의 정답 — " + ("설문마다 1부터." if 번호머리 == 3 else "머리(사례·설문·<도쓰> 칸)마다 1부터.")) + "\n".join(답)
    정리 = lambda s: re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"
    return 정리(문서), 정리(답서)


def 소제목인가(line):
    """머리 말고 카드를 나누는 줄 — 핸드북 `▸ …` 소제목, 도쓰 칸 `[논점]` 표지."""
    return line.startswith("▸ ") or bool(re.match(r"^\[[^\]]+\]", line))


def 카드글(s):
    """Flashcards Deluxe 가 태그·줄바꿈으로 읽는 글자를 피한다(| = 줄바꿈, <…> = 태그)."""
    return s.replace("\t", " ").replace("|", "∣").replace("<", "＜").replace(">", "＞")


def 카드뽑기(본문):
    """소제목 하나 = 카드 한 장. [앞, 뒤, 분류1, 분류2] 를 돌려준다.
    소제목 = 가장 깊은 `#` 머리(GS `####`) 또는 `▸ …` · `[논점]` 줄. 빈칸 없는 카드는 뺀다.
    앞 = 위 머리 경로 · 소제목(굵게) · 빈칸 낸 본문(번호는 카드마다 1부터), 뒤 = 같은 본문에 정답 <b>굵게</b>."""
    카드 = []
    머리들 = {}            # 단계 → 머리 글
    제목, 앞줄, 뒷줄, 빈수 = "", [], [], 0
    머리끝 = False

    def 내기():
        if 빈수:
            경로 = " › ".join(카드글(머리들[k]) for k in sorted(머리들) if 머리들[k] != 제목)
            위 = f"{경로}|<b>{카드글(제목)}</b>||" if 제목 else f"{경로}||"
            카드.append([위 + "|".join(앞줄), 위 + "|".join(뒷줄),
                       카드글(머리들.get(2, "")), 카드글(머리들.get(3, ""))])

    for line in 본문.split("\n"):
        line = re.sub(r"\s*<!--.*?-->", "", line).rstrip()
        if not 머리끝:
            if line.startswith("## "):
                머리끝 = True
            else:
                continue
        m = re.match(r"^(#{2,6}) (.*)", line)
        if m or 소제목인가(line):
            내기()
            앞줄, 뒷줄, 빈수 = [], [], 0
            if m:
                k = len(m.group(1))
                머리들 = {j: t for j, t in 머리들.items() if j < k}
                머리들[k] = 제목 = m.group(2)
            else:
                제목 = _표지.sub(lambda m: f"〔{m.group(1)}〕", line.removeprefix("▸ "))
            continue
        if not line:
            continue
        line = _표지.sub(lambda m: f"〔{m.group(1)}〕", line)
        조각 = _굵.split(카드글(line))        # 짝수 = 그냥 글, 홀수 = 굵은 말
        앞, 뒤, 낱말 = [], [], 조각[1::2]
        for i, t in enumerate(조각):
            if i % 2:
                빈수 += 1
                앞.append(f"({빈수} {밑줄(t)})")
                뒤.append(f"<b>{t}</b>")
            else:
                앞.append(t)
                뒤.append(t)
        앞 = "".join(앞)
        if 낱말 and not _두음.search(앞):
            앞 += " 〔" + "".join(w.lstrip("(法 ")[0] for w in 낱말) + "〕"
        앞줄.append(앞)
        뒷줄.append("".join(뒤))
    내기()
    return 카드


def 카드파일(카드):
    머리줄 = "Text 1\tText 2\tCategory 1\tCategory 2"
    return "\n".join([머리줄] + ["\t".join(c) for c in 카드]) + "\n"


def 검사(본문):
    문제 = 0
    도쓰안 = False
    for no, line in enumerate(본문.split("\n"), 1):
        if re.match(r"^#{1,6} ", line):
            if "<도쓰>" in line:
                도쓰안 = True
            elif re.match(r"^#{1,4} ", line):
                도쓰안 = False
        면제 = "빈칸 없음" in line or 도쓰안
        line = _표지.sub("", re.sub(r"<!--.*?-->", "", line))
        낱말 = _굵.findall(line)
        if line.startswith("判例") and not 낱말 and not 면제:
            print(f"  {no}: 빈칸 없는 판례 문장 — {line[:50]}")
            문제 += 1
        for w in 낱말:
            if len(w) > 최대:
                print(f"  {no}: {최대}자 넘는 빈칸 — {w}")
                문제 += 1
    문서, 답서 = 뽑기(본문)
    빈 = len(_빈칸.findall(문서))
    본답 = 답서[답서.index("\n## "):] if "\n## " in 답서 else ""
    답수 = sum(len(re.findall(r"(?:^| · )\d+ ", l)) for l in 본답.split("\n") if not l.startswith("#"))
    if 빈 != 답수:
        print(f"  빈칸 {빈} ↔ 정답 {답수} — 개수가 다르다")
        문제 += 1
    카드빈 = sum(len(_빈칸.findall(c[0])) for c in 카드뽑기(본문))
    if 빈 != 카드빈:
        print(f"  빈칸 {빈} ↔ 플래시카드 빈칸 {카드빈} — 개수가 다르다")
        문제 += 1
    print(f"검사 {문제}건 (빈칸 {빈})")
    return 문제


def main(argv):
    global 자료, 빈칸, 정답, 카드, 번호머리
    if "--번호머리" in argv:
        번호머리 = int(argv[argv.index("--번호머리") + 1])
    if "--자료" in argv:
        자료 = Path(argv[argv.index("--자료") + 1]).resolve()
        빈칸 = 자료.with_name(자료.name.replace("자료", "빈칸채우기"))
        정답 = 자료.with_name(자료.name.replace("자료", "빈칸정답"))
        카드 = 자료.with_name(자료.name.replace("자료", "플래시카드")).with_suffix(".txt")
    본문 = 자료.read_text(encoding="utf-8")
    if "--검사" in argv:
        sys.exit(1 if 검사(본문) else 0)
    문서, 답서 = 뽑기(본문)
    빈칸.write_text(문서, encoding="utf-8", newline="\n")
    정답.write_text(답서, encoding="utf-8", newline="\n")
    장 = 카드뽑기(본문)
    카드.write_text(카드파일(장), encoding="utf-8-sig", newline="\n")   # BOM — 앱이 UTF-8 로 읽게
    print(f"{빈칸.name}  빈칸 {len(_빈칸.findall(문서))}개\n{정답.name}\n{카드.name}  카드 {len(장)}장")


if __name__ == "__main__":
    main(sys.argv[1:])
