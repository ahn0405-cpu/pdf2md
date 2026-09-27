#!/usr/bin/env python3
"""소스에서 ☑ 박스가 어느 절·항목 뒤에 있었는지 읽는다.

노트의 박스를 원래 자리로 되돌리려면 소스의 순서를 알아야 한다.
소스는 박스를 `> ### ☑ 제목` 으로 두고, 그 앞뒤에 절 번호가 있다.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
기본서 = HERE.parent / "출력" / "기본서"
_절 = re.compile(r"^#{3,4}\s+([IVX]+\.\s*[^\n]+)")
_항 = re.compile(r"^\*\*(\d+\.\s*[^*]+)\*\*|^==?\*?\*?(\d+\.\s*[^=*]+)")
_박스 = re.compile(r"^>?\s*#{3,4}\s*☑\s*(.+)")


def 읽기(논점: str):
    cands = sorted(기본서.glob(f"*_{논점}*.md"))
    if not cands:
        return None
    p = cands[0]
    out = []
    위치 = "(논점 머리)"
    for line in p.read_text(encoding="utf-8").splitlines():
        st = re.sub(r"==|\*\*", "", line).strip()
        m = _절.match(line) or _절.match("### " + st if re.match(r"^[IVX]+\.", st) else "")
        if m:
            위치 = m.group(1).strip()
            continue
        m2 = re.match(r"^(\d+\.\s*\S[^\n]{0,40})", st)
        if m2 and not st.startswith("☑"):
            절 = 위치.split(" › ")[0]
            위치 = f"{절} › {m2.group(1).strip()}"
            continue
        b = _박스.match(line)
        if b:
            out.append((b.group(1).strip(), 위치, len(out), None))
    # 박스 뒤에 절이 더 나오는지 — 나오면 말미가 아니라 그 자리로 옮겨야 한다
    절순서 = []
    박스순서 = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
        st = re.sub(r"==|\*\*", "", line).strip()
        if re.match(r"^#{3,4}\s+[IVX]+\.", line) or re.match(r"^[IVX]+\.\s", st):
            절순서.append(n)
        if _박스.match(line):
            박스순서.append(n)
    res = []
    for k, (제목, 위치, _, _) in enumerate(out):
        ln = 박스순서[k] if k < len(박스순서) else 10**9
        뒤절 = sum(1 for x in 절순서 if x > ln)
        res.append((제목, 위치, 뒤절))
    return p.name, res


def main(논점들):
    for 논점 in 논점들:
        r = 읽기(논점)
        if not r:
            print(f"## {논점} — 소스 없음")
            continue
        이름, boxes = r
        print(f"## {논점}  ({이름})")
        if not boxes:
            print("  (소스에 ☑ 박스가 잡혀 있지 않음 — 표지 손상 가능)")
        for 제목, 위치, 뒤절 in boxes:
            표 = "말미 그대로" if 뒤절 == 0 else f"옮김 (뒤에 절 {뒤절}개)"
            print(f"  ☑ {제목[:40]:42} ← {위치[:48]:50} {표}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["045"])
