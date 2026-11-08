#!/usr/bin/env python3
"""박형준GS/자료.md → 박형준GS/빈칸채우기.md. 자료의 **굵은 말**을 ❶(＿＿)로 가린다(손으로 고치지 않는다).

    python 빈칸채우기.py           뽑는다
    python 빈칸채우기.py --검사    빈칸 없는 판례 문장 · 15자 넘는 빈칸 · 〔두음〕 ↔ 빈칸 머리글자 어긋남

- 번호는 설문(`###`)마다 ❶부터. 설문 끝에 정답.
- 빈칸이 있는 문장 끝에 〔두음〕 이 없으면 빈칸 머리글자로 만든 힌트 〔…〕 를 붙인다.
- `<!-- … -->` 주석은 뺀다.
"""
import re
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
폴더 = 여기.parent / "박형준GS"
자료 = 폴더 / "자료.md"
출력 = 폴더 / "빈칸채우기.md"

번호 = "❶❷❸❹❺❻❼❽❾❿⓫⓬⓭⓮⓯⓰⓱⓲⓳⓴"
_굵 = re.compile(r"\*\*([^*]+)\*\*")
_두음 = re.compile(r"〔([가-힣]+)〕")


def 표(n):
    return 번호[n - 1] if n <= len(번호) else f"({n})"


def 뽑기(본문):
    out, 답, n = [], [], 0

    def 정답내기():
        if 답:
            out.extend(["", "> 정답 " + " · ".join(f"{표(i)} {w}" for i, w in 답), ""])

    머리끝 = False
    for line in 본문.split("\n"):
        line = re.sub(r"\s*<!--.*?-->", "", line)
        if line.startswith("# "):
            out.append("# 박형준 기초 GS · 빈칸채우기")
            continue
        if not 머리끝:
            if line.startswith("## "):
                머리끝 = True
                out += ["", "`자료.md` 의 굵은 말을 가렸다. `빈칸채우기.py` 가 뽑는다 — 손으로 고치지 않는다. 〔 〕 = 두음 힌트.", ""]
            else:
                continue
        if line.startswith(("## ", "### ")):
            정답내기()
            답, n = [], 0
            out.append(line)
            continue
        낱말 = _굵.findall(line)
        if 낱말:
            힌트 = "".join(w[0] for w in 낱말)

            def 가림(m):
                nonlocal n
                n += 1
                답.append((n, m.group(1)))
                return f"{표(n)}(＿＿)"
            line = _굵.sub(가림, line)
            if not _두음.search(line):
                line = line.rstrip() + f" 〔{힌트}〕"
        out.append(line)
    정답내기()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"


def 검사(본문):
    문제 = 0
    for no, line in enumerate(본문.split("\n"), 1):
        line = re.sub(r"<!--.*?-->", "", line)
        낱말 = _굵.findall(line)
        if line.startswith("判例") and not 낱말:
            print(f"  {no}: 빈칸 없는 판례 문장 — {line[:50]}")
            문제 += 1
        for w in 낱말:
            if len(w) > 15:
                print(f"  {no}: 15자 넘는 빈칸 — {w}")
                문제 += 1
        m = _두음.search(line)
        if m and 낱말:
            머리 = [w[0] for w in 낱말]
            무리 = list(m.group(1))
            k = 0                                   # 빈칸 머리글자가 두음 글자들의 부분열인지
            for c in 머리:
                while k < len(무리) and 무리[k] != c:
                    k += 1
                if k == len(무리):
                    break
                k += 1
            else:
                continue
            print(f"  {no}: 두음 〔{m.group(1)}〕 ↔ 빈칸 머리 「{''.join(머리)}」 — 어긋남")
            문제 += 1
    print(f"검사 {문제}건")
    return 문제


def main(argv):
    본문 = 자료.read_text(encoding="utf-8")
    if "--검사" in argv:
        sys.exit(1 if 검사(본문) else 0)
    결과 = 뽑기(본문)
    출력.write_text(결과, encoding="utf-8", newline="\n")
    print(f"{출력}  빈칸 {결과.count('(＿＿)')}개")


if __name__ == "__main__":
    main(sys.argv[1:])
