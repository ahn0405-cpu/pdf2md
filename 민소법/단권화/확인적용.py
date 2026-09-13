#!/usr/bin/env python3
"""references/확인목록.md 의 「확정값」을 노트에 반영한다.

사용자가 원본 책을 보고 확정값 칸을 채우면, 그 줄만 골라
output/*.md 의 해당 행에서 사건번호를 바꾸고 `<!-- 확인필요: … -->` 주석을 지운다.

    python3 확인적용.py           반영
    python3 확인적용.py --검사    무엇이 바뀔지만 보여 준다

행 번호는 노트가 고쳐지면 밀리므로 **행 번호로 찾지 않는다.**
그 행의 `확인필요` 주석과 「노트에 적은 값」으로 자리를 찾는다.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
목록 = HERE / "references" / "확인목록.md"
_행 = re.compile(r"^\|\s*(\d{3}_[^|]+?)\s*\|\s*(\d+)\s*\|[^|]*\|\s*([^|]*?)\s*\|[^|]*\|\s*([^|]*?)\s*\|\s*$")


def 읽기():
    """확정값이 채워진 줄만 돌려준다."""
    out = []
    for line in 목록.read_text(encoding="utf-8").splitlines():
        m = _행.match(line)
        if not m:
            continue
        파일, _, 적은값, 확정값 = m.groups()
        확정값 = 확정값.strip().strip("`").strip()
        if not 확정값 or 확정값.startswith("**"):
            continue
        out.append((파일, 적은값.strip().strip("`").strip(), 확정값))
    return out


def main():
    검사 = "--검사" in sys.argv
    항목 = 읽기()
    if not 항목:
        print("확정값이 채워진 줄이 없습니다. references/확인목록.md 의 「확정값」 칸을 채우십시오.")
        return 0

    적용 = 미매칭 = 0
    for 파일, 적은값, 확정값 in 항목:
        cands = sorted((HERE / "output").glob(f"{파일.split('_')[0]}_*.md"))
        if not cands:
            print(f"❌ 파일 없음: {파일}")
            미매칭 += 1
            continue
        p = cands[0]
        s = p.read_text(encoding="utf-8")
        # 확인필요 주석이 달린 줄들 중에서 「적은 값」을 담은 줄을 찾는다
        새 = []
        hit = False
        for line in s.split("\n"):
            if "확인필요" in line and (not 적은값 or 적은값 in line):
                before = line
                if 적은값:
                    line = line.replace(적은값, 확정값, 1)
                line = re.sub(r"\s*<!--\s*확인필요:.*?-->", "", line)
                if line != before:
                    hit = True
                    print(f"  {p.name}\n    - {before.strip()[:100]}\n    + {line.strip()[:100]}")
            새.append(line)
        if not hit:
            print(f"❌ 자리 못 찾음: {p.name} 「{적은값}」 — 이미 고쳤거나 값이 다릅니다")
            미매칭 += 1
            continue
        if not 검사:
            p.write_text("\n".join(새), encoding="utf-8")
        적용 += 1

    말 = "반영" if not 검사 else "반영 예정"
    print(f"\n{말} {적용}건" + (f"  ❌미매칭 {미매칭}건" if 미매칭 else ""))
    if 검사:
        print("(--검사 라서 파일은 바꾸지 않았습니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
