#!/usr/bin/env python3
"""판례 블록마다 쓸 수 있는 사실관계를 모아 보여 준다.

「상황」은 甲·乙·목적물·청구가 있어야 사례가 된다(SKILL.md §① 작성 요령).
기본서에는 사실관계가 거의 없다. 실제로 있는 곳은 세 군데다.

    1 사례집 문제 지문   뱃지가 가리키는 문제의 첫 단락. **진짜 사실관계**다
    2 기본서 각주        사실관계를 각주로 내린 자리
    3 판시 자체          위 둘이 없을 때 요건에서 역구성한다

    python3 사실관계.py output/052_처분권주의.md
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
사례집 = HERE.parent / "출력" / "사례집"

_뱃지 = re.compile(r"`([A-Q]-\d+)`")
_사건번호 = re.compile(r"^#{2,6}\s+(?:\d\)\s*)?((?:19|20)?\d{2}(?:다카|다|카|그|초|오|므|두|누|마|헌마)\d+)")


def _담는다(표, 번호, 파일, 제목, 지문):
    """같은 문제번호가 목차와 본문에 두 번 나온다. 지문이 있는 쪽을 남긴다."""
    기존 = 표.get(번호)
    if 기존 and len(기존[2]) >= len(지문):
        return
    표[번호] = (파일, 제목, 지문)


def 문제모음():
    """사례집 문제번호 → 지문(첫 단락)."""
    표 = {}
    for p in sorted(사례집.glob("*.md")):
        번호 = None
        모음 = []
        for line in p.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^##\s+([A-Q]-\d+)\.\s*(.*)$", line)
            if m:
                if 번호:
                    _담는다(표, 번호, p.name, 제목, " ".join(모음).strip())
                번호, 제목, 모음 = m.group(1), m.group(2), []
                continue
            if 번호 is None:
                continue
            if line.startswith("###"):      # 답안 본문이 시작되면 지문은 끝이다
                _담는다(표, 번호, p.name, 제목, " ".join(모음).strip())
                번호 = None
                continue
            if line.strip():
                모음.append(line.strip())
        if 번호:
            _담는다(표, 번호, p.name, 제목, " ".join(모음).strip())
    return 표


def _쓸만한가(지문):
    """목차 쪼가리를 걸러 낸다 — 점선과 쪽번호만 있는 줄이다."""
    if len(지문) < 40:
        return False
    return 지문.count(".") < len(지문) / 12


def 본다(노트, 표):
    L = Path(노트).read_text(encoding="utf-8").split("\n")
    현재 = None
    for i, line in enumerate(L):
        알맹이 = re.sub(r"^[>\s]*", "", line)
        m = _사건번호.match(알맹이)
        if m:
            현재 = (m.group(1), i + 1)
            뱃지 = []
            for j in range(i + 1, min(i + 5, len(L))):
                뱃지 += _뱃지.findall(L[j])
            print(f"\n■ {현재[0]}  ({노트}:{현재[1]})  뱃지 {뱃지 or '없음'}")
            for b in 뱃지:
                if b in 표:
                    f, 제목, 지문 = 표[b]
                    print(f"  └ {b} {제목}  [{f}]")
                    print(f"    {지문[:700]}")
                else:
                    print(f"  └ {b} — 사례집에서 문제를 못 찾음")


if __name__ == "__main__":
    표 = 문제모음()
    if not sys.argv[1:]:
        print(f"사례집 문제 {len(표)}개 색인")
        sys.exit()
    for 노트 in sys.argv[1:]:
        본다(노트, 표)
