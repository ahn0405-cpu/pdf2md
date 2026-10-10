"""도구들이 함께 쓰는 경로. 폴더를 옮기면 여기만 고친다.

    특허법/
    ├── 출력/기본서 · 사례집 · 추록 · 정오표   소스 (book2md 의 산물)
    ├── 노트/목차집                          결과물
    └── 작업/                               references · 도구(여기)

논점은 번호로 준다. 둘 다 받는다.

    python3 목차재료.py 011        책 전체 순번 (기본서 파일 이름 앞 세 자리)
    python3 목차재료.py 2-07       장-장내번호 (책에 찍힌 번호)
"""
import csv
import os
import sys
from pathlib import Path

도구 = Path(__file__).resolve().parent
작업 = 도구.parent
특허법 = 작업.parent

기본서 = 특허법 / "출력" / "기본서"
사례집 = 특허법 / "출력" / "사례집"
추록 = 특허법 / "출력" / "추록"
정오표 = 특허법 / "출력" / "정오표"
목차집 = 특허법 / "노트" / "목차집"          # 손으로 쓴다 — 목차재료.py 가 재료·검사
references = 작업 / "references"
목차표 = references / "기본서목차.tsv"       # 목차표.py 가 만든다


def 논점표():
    """기본서목차.tsv → 행 목록. 순번·장·장제목·장내번호·논점·PDF시작·PDF끝·책쪽."""
    with open(목차표, encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def 찾기(인자):
    """'011' 또는 '2-07' 을 목차표 행으로."""
    표 = 논점표()
    if "-" in 인자:
        장, 번 = 인자.split("-", 1)
        hit = [r for r in 표 if int(r["장"]) == int(장) and int(r["장내번호"]) == int(번)]
    else:
        hit = [r for r in 표 if r["순번"] == f"{int(인자):03d}"]
    if not hit:
        sys.exit(f"논점을 못 찾음: {인자}")
    return hit[0]


def 기본서파일(행):
    cands = sorted(기본서.glob(f"{행['순번']}_*.md"))
    if not cands:
        sys.exit(f"기본서 파일이 없다: {행['순번']}")
    return cands[0]


def 상대(p):
    """돌린 자리에서 본 상대 경로 — `경로:행` 을 편집기에서 바로 열 수 있게."""
    try:
        return os.path.relpath(p)
    except ValueError:          # Windows 에서 드라이브가 다르면
        return str(p)
