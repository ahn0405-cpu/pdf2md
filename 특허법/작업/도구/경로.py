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

# ── 원본 PDF (리포에 없다 — *.pdf 는 커밋하지 않는다) ─────────────────
# 두문자·판시가 OCR 로 깨졌을 때 원본 쪽을 잘라 읽는 데 쓴다(두문자원본.py).
# PC 마다 위치가 다르면 환경변수로 덮는다. 폴더 하나로 줄 때는 TEMA_PDF_DIR,
# 파일마다 줄 때는 TEMA_TEXTBOOK · TEMA_CASEBOOK · TEMA_ADDENDUM · TEMA_ERRATA
# (기본서·사례집·추록·정오표 — bash 는 한글 변수 이름을 못 쓴다).
#
#     set TEMA_PDF_DIR=D:\자료\테마특허법          (Windows)
#     export TEMA_PDF_DIR=~/자료/테마특허법          (bash)
#
# 폴더로 줄 때는 아래 「파일 이름」 중 하나와 같은 이름의 PDF 를 찾는다.
_원본 = {
    # 이 PC(사장님 PC)의 위치. Windows 도 '/' 로 적어도 된다.
    "기본서": (["F:/GoogleDrive/00-안-개인/03. 변시/01. 특허법/01. 26년 테마 특허법/테마 특허법.pdf",
               "F:/GoogleDrive/00-안-개인/02. 특허법/06. 테마 특허법/특허_테마_기본서.pdf"],
              ["테마 특허법.pdf", "특허_테마_기본서.pdf"]),
    "사례집": (["F:/GoogleDrive/00-안-개인/03. 변시/01. 특허법/01. 26년 테마 특허법/테마 특허법 사례집.pdf"],
              ["테마 특허법 사례집.pdf", "특허_테마_사례_압축.pdf"]),
    "추록": (["F:/GoogleDrive/00-안-개인/02. 특허법/06. 테마 특허법/[A4_양면_한쪽]_박지환T_테마특허법_9판_1차추록(특강).pdf"],
            ["[A4_양면_한쪽]_박지환T_테마특허법_9판_1차추록(특강).pdf"]),
    "정오표": (["F:/GoogleDrive/00-안-개인/02. 특허법/06. 테마 특허법/테마 사례집_5판_정오표.pdf"],
              ["테마 사례집_5판_정오표.pdf"]),
}


_변수 = {"기본서": "TEXTBOOK", "사례집": "CASEBOOK", "추록": "ADDENDUM", "정오표": "ERRATA"}


def 원본PDF(책="기본서"):
    """원본 PDF 경로. 못 찾으면 어디를 봤는지 알리고 멈춘다.

    사례집 압축본(「특허_테마_사례_압축.pdf」)도 626쪽, 쪽 배치가 같아 대신 쓸 수 있다(그림 해상도는 낮을 수 있다).
    """
    기본, 이름들 = _원본[책]
    변수 = "TEMA_" + _변수[책]
    후보 = []
    if os.environ.get(변수):
        후보.append(Path(os.environ[변수]))
    if os.environ.get("TEMA_PDF_DIR"):
        후보 += [Path(os.environ["TEMA_PDF_DIR"]) / n for n in 이름들]
    후보 += [Path(p) for p in 기본]
    for p in 후보:
        if p.is_file():
            return p
    본곳 = "\n  ".join(map(str, 후보))
    sys.exit(f"{책} 원본 PDF 를 못 찾음. 본 곳:\n  {본곳}\n"
             f"환경변수 TEMA_PDF_DIR(폴더) 또는 {변수}(파일)로 위치를 알려 줄 것.")


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
