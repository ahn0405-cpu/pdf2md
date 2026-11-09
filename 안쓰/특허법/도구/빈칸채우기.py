#!/usr/bin/env python3
"""[특허법] 안쓰 GS 자료.md → 빈칸채우기 + 빈칸정답 (둘 다 뽑는 파일 — 손으로 고치지 않는다).

    python 빈칸채우기.py           뽑는다
    python 빈칸채우기.py --검사    빈칸 없는 판례 문장 · 60자 넘는 빈칸 · 빈칸 ↔ 정답 개수
    python 빈칸채우기.py --자료 "<…/[민소법] 안쓰 핸드북 자료.md>"   다른 자료(이름의 「자료」를 「빈칸채우기」「빈칸정답」으로 바꿔 쓴다)
    판례 줄에 `<!-- … 빈칸 없음 -->` 이 있으면 검사에서 뺀다(민소 핸드북: 도쓰·★·표준에 해당하지 않는 판례).
    python 빈칸채우기.py --번호머리 5 --자료 "<…/[민소법] 안쓰 핸드북 자료 제2편.md>"
                                  민소 핸드북 — 번호를 `##` ～ `#####`(사례·설문·<도쓰> 칸) 머리마다 ❶부터. 기본은 3(`##`·`###`, GS).

- 자료의 **굵은 말**(= GS 판례·조문·취지 형광펜 구절)을 ❶(＿＿＿ ＿)로 가린다 — 정답 글자 수만큼 ＿, 띄어쓰기는 그대로(단어 수가 보이게, 필기할 자리). 번호는 설문(`###`)마다 ❶부터.
- 정답은 **따로** `[특허법] 안쓰 GS 빈칸정답.md` 에 같은 문제·설문 머리 아래 — 빈칸채우기에는 정답이 없다(먼저 보지 않게).
- 문장에 〔두음〕(기본서 두음)이 없으면 빈칸 머리글자로 힌트 〔…〕 를 붙인다.
- 굵은 말이 통째로 `(…)` 인 두문자 표지(도쓰 `**(지변정)**`)는 빈칸이 아니라 힌트 〔지변정〕 로 바꾼다.
- 검사에서 `<도쓰>` 칸(도쓰 원문을 그대로 옮긴 곳)의 굵은 말 없는 판례 줄은 세지 않는다.
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
_두음 = re.compile(r"〔([^〕]+)〕")
최대 = 60
번호머리 = 3          # 이 단계 이하의 머리(## ～ #×번호머리)에서 번호를 ❶부터 다시 센다
_표지 = re.compile(r"\*\*\(([^*()]+)\)\*\*")
_빈칸 = re.compile(r"\([＿ ]+\)")


def 밑줄(w):
    """정답 글자 수만큼 ＿(전각) — 단어 사이 띄어쓰기는 그대로."""
    return " ".join("＿" * len(t) for t in w.split())


def 머리인가(line):
    m = re.match(r"^(#{2,6}) ", line)
    return bool(m) and len(m.group(1)) <= 번호머리


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
                return f"{표(n)}({밑줄(m.group(1))})"
            line = _굵.sub(가림, line)
            if not _두음.search(line):
                line = line.rstrip() + f" 〔{힌트}〕"
        문.append(line)
    정답내기()
    머리 = lambda 이름, 설명: f"# {이름}\n\n{설명}\n\n<!-- 빈칸채우기.py 가 「{자료.name}」에서 뽑는다 — 손으로 고치지 않는다. -->\n\n"
    문서 = 머리(빈칸.stem,
              f"자료의 굵은 말을 가렸다. ＿ 하나 = 한 글자, 띄어쓰기 = 단어 사이. 〔 〕 = 힌트(두음 또는 빈칸 머리글자). **정답은 `{정답.name}`** 에.") + "\n".join(문)
    답서 = 머리(정답.stem, f"`{빈칸.name}` 의 정답 — " + ("설문마다 ❶부터." if 번호머리 == 3 else "머리(사례·설문·<도쓰> 칸)마다 ❶부터.")) + "\n".join(답)
    정리 = lambda s: re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"
    return 정리(문서), 정리(답서)


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
    답수 = sum(len(re.findall(r"[❶-❿⓫-⓴]|\(\d+\)", l)) for l in 본답.split("\n") if not l.startswith("#"))
    if 빈 != 답수:
        print(f"  빈칸 {빈} ↔ 정답 {답수} — 개수가 다르다")
        문제 += 1
    print(f"검사 {문제}건 (빈칸 {빈})")
    return 문제


def main(argv):
    global 자료, 빈칸, 정답, 번호머리
    if "--번호머리" in argv:
        번호머리 = int(argv[argv.index("--번호머리") + 1])
    if "--자료" in argv:
        자료 = Path(argv[argv.index("--자료") + 1]).resolve()
        빈칸 = 자료.with_name(자료.name.replace("자료", "빈칸채우기"))
        정답 = 자료.with_name(자료.name.replace("자료", "빈칸정답"))
    본문 = 자료.read_text(encoding="utf-8")
    if "--검사" in argv:
        sys.exit(1 if 검사(본문) else 0)
    문서, 답서 = 뽑기(본문)
    빈칸.write_text(문서, encoding="utf-8", newline="\n")
    정답.write_text(답서, encoding="utf-8", newline="\n")
    print(f"{빈칸.name}  빈칸 {len(_빈칸.findall(문서))}개\n{정답.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
