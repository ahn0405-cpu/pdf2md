"""도구들이 함께 쓰는 경로. 폴더를 옮기면 여기만 고친다.

    민소법/
    ├── 출력/기본서 · 사례집     소스
    ├── 노트/단권화 · 암기노트 · 목차집   결과물
    └── 작업/                   SKILL.md · references · samples · 도구(여기)

노트 인자는 경로 그대로 주어도 되고 번호만 주어도 된다.

    python3 전말덤프.py 058
    python3 전말덤프.py ../../노트/단권화/058_변론의개시진행종결재개.md
"""
import glob
import os
import sys
from pathlib import Path

도구 = Path(__file__).resolve().parent
작업 = 도구.parent
민소법 = 작업.parent

기본서 = 민소법 / "출력" / "기본서"
사례집 = 민소법 / "출력" / "사례집"
노트 = 민소법 / "노트" / "단권화"
암기노트 = 민소법 / "노트" / "암기노트"
목차집 = 민소법 / "노트" / "목차집"          # 손으로 쓴다 — 목차재료.py 가 재료·검사
references = 작업 / "references"
samples = 작업 / "samples"


def 노트들(인자=None):
    """인자(경로·글롭·번호)를 노트 경로 목록으로 푼다. 비었으면 노트 전부."""
    인자 = sys.argv[1:] if 인자 is None else 인자
    인자 = [a for a in 인자 if not a.startswith("--")]
    if not 인자:
        return [_상대(p) for p in sorted(노트.glob("*.md"))]
    out = []
    for a in 인자:
        if Path(a).exists():
            out.append(a)
        elif glob.glob(a):
            out.extend(sorted(glob.glob(a)))
        else:
            찾음 = sorted(노트.glob(f"{a}*.md"))
            if not 찾음:
                sys.exit(f"노트를 못 찾음: {a}")
            out.extend(str(p) for p in 찾음)
    return [_상대(p) for p in out]


def _상대(p):
    """돌린 자리에서 본 상대 경로 — `경로:행` 을 편집기에서 바로 열 수 있게."""
    try:
        return os.path.relpath(p)
    except ValueError:          # Windows 에서 드라이브가 다르면
        return str(p)


def 이름(p):
    """출력용 — 경로를 떼고 파일 이름만."""
    return Path(p).name
