#!/usr/bin/env python3
"""[특허법] 안쓰 GS 자료.md → 빈칸채우기 + 빈칸정답 (둘 다 뽑는 파일 — 손으로 고치지 않는다).

    python 빈칸채우기.py           뽑는다
    python 빈칸채우기.py --검사    빈칸 없는 판례 문장 · 45자 넘는 빈칸

- 자료의 **굵은 말**(= GS 판례·조문·취지 형광펜 구절)을 ❶(＿＿)로 가린다. 번호는 설문(`###`)마다 ❶부터.
- 정답은 **따로** `[특허법] 안쓰 GS 빈칸정답.md` 에 같은 문제·설문 머리 아래 — 빈칸채우기에는 정답이 없다(먼저 보지 않게).
- 문장에 〔두음〕(기본서 두음)이 없으면 빈칸 머리글자로 힌트 〔…〕 를 붙인다.
- `<!-- … -->` 주석은 뺀다.
"""
import re
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
폴더 = 여기.parent / "박형준GS"
자료 = 폴더 / "[특허법] 안쓰 GS 자료.md"
빈칸 = 폴더 / "[특허법] 안쓰 GS 빈칸채우기.md"
정답 = 폴더 / "[특허법] 안쓰 GS 빈칸정답.md"

번호 = "❶❷❸❹❺❻❼❽❾❿⓫⓬⓭⓮⓯⓰⓱⓲⓳⓴"
_굵 = re.compile(r"\*\*([^*]+)\*\*")
_두음 = re.compile(r"〔([가-힣]+)〕")
최대 = 45


def 표(n):
    return 번호[n - 1] if n <= len(번호) else f"({n})"


def 뽑기(본문):
    문, 답 = [], []
    설문답, n = [], 0
    머리끝 = False

    def 정답내기():
        if 설문답:
            답.extend([" · ".join(f"{표(i)} {w}" for i, w in 설문답), ""])

    for line in 본문.split("\n"):
        line = re.sub(r"\s*<!--.*?-->", "", line)
        if not 머리끝:
            if line.startswith("## "):
                머리끝 = True
            else:
                continue
        if line.startswith(("## ", "### ")):
            정답내기()
            설문답, n = [], 0
            문.append(line)
            답.append(line)
            if line.startswith("## "):
                답.append("")
            continue
        낱말 = _굵.findall(line)
        if 낱말:
            힌트 = "".join(w.lstrip("(法 ")[0] for w in 낱말)

            def 가림(m):
                nonlocal n
                n += 1
                설문답.append((n, m.group(1)))
                return f"{표(n)}(＿＿)"
            line = _굵.sub(가림, line)
            if not _두음.search(line):
                line = line.rstrip() + f" 〔{힌트}〕"
        문.append(line)
    정답내기()
    머리 = lambda 이름, 설명: f"# {이름}\n\n{설명}\n\n<!-- ../도구/빈칸채우기.py 가 「[특허법] 안쓰 GS 자료.md」에서 뽑는다 — 손으로 고치지 않는다. -->\n\n"
    문서 = 머리("[특허법] 안쓰 GS 빈칸채우기",
              "GS 판례·조문·취지 형광펜 구절을 가렸다. 〔 〕 = 힌트(기본서 두음 또는 빈칸 머리글자). **정답은 `[특허법] 안쓰 GS 빈칸정답.md`** 에.") + "\n".join(문)
    답서 = 머리("[특허법] 안쓰 GS 빈칸정답", "`[특허법] 안쓰 GS 빈칸채우기.md` 의 정답 — 설문마다 ❶부터.") + "\n".join(답)
    정리 = lambda s: re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"
    return 정리(문서), 정리(답서)


def 검사(본문):
    문제 = 0
    for no, line in enumerate(본문.split("\n"), 1):
        line = re.sub(r"<!--.*?-->", "", line)
        낱말 = _굵.findall(line)
        if line.startswith("判例") and not 낱말:
            print(f"  {no}: 빈칸 없는 판례 문장 — {line[:50]}")
            문제 += 1
        for w in 낱말:
            if len(w) > 최대:
                print(f"  {no}: {최대}자 넘는 빈칸 — {w}")
                문제 += 1
    문서, 답서 = 뽑기(본문)
    빈 = 문서.count("(＿＿)")
    본답 = 답서[답서.index("\n## "):] if "\n## " in 답서 else ""
    답수 = sum(len(re.findall(r"[❶-❿⓫-⓴]|\(\d+\)", l)) for l in 본답.split("\n") if not l.startswith("#"))
    if 빈 != 답수:
        print(f"  빈칸 {빈} ↔ 정답 {답수} — 개수가 다르다")
        문제 += 1
    print(f"검사 {문제}건 (빈칸 {빈})")
    return 문제


def main(argv):
    본문 = 자료.read_text(encoding="utf-8")
    if "--검사" in argv:
        sys.exit(1 if 검사(본문) else 0)
    문서, 답서 = 뽑기(본문)
    빈칸.write_text(문서, encoding="utf-8", newline="\n")
    정답.write_text(답서, encoding="utf-8", newline="\n")
    print(f"{빈칸.name}  빈칸 {문서.count('(＿＿)')}개\n{정답.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
