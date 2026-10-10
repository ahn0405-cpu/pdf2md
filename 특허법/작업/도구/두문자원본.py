#!/usr/bin/env python3
"""원본 PDF 에서 두문자·판시 줄을 잘라 그림으로 저장한다 — OCR 로 깨진 글자를 눈으로 읽기 위해.

기본서는 스캔 + OCR 이라 두문자가 자주 깨진다(「[기모자연동]」 ← 원본 [기모자연통],
「[필허 . 기 .특공해」 ← [필허기특공하]). 변환물 글자를 그대로 옮기지 말고, 이 도구로
원본 쪽을 잘라 읽은 뒤 쓴다. 깨져 있던 것은 references/두문자확인.md 에 한 줄씩 더한다.

원본 PDF 위치는 경로.py 의 원본PDF() — PC 마다 다르면 환경변수 TEMA_PDF_DIR 로 준다.
_work/ 중간 파일은 필요 없다(PDF 의 OCR 글자층을 직접 읽는다).

    python3 두문자원본.py CH02               장 전체의 두문자 줄
    python3 두문자원본.py 2-07 2-08          논점별
    python3 두문자원본.py 2-07 --찾기 구별되어야 효과의 현저성    그 글자가 든 줄(+아래 60pt)
    python3 두문자원본.py --쪽 162 166       기본서 그 쪽 전체 (PDF 쪽 번호)
    python3 두문자원본.py --책 추록 --쪽 4    추록·정오표·사례집 쪽 보기

그림은 임시 폴더(<temp>/특허법_원본/)에 12줄씩 묶어 저장하고 경로를 찍는다. --out 으로 바꾼다.
그림을 열어(Claude 는 Read 로) 읽고, 목차집에는 원본대로 쓴다.
"""
import math
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 논점표, 찾기, 원본PDF

# 두문자로 보지 않을 대괄호 머리말 (각주 라벨과 그 OCR 변형)
_라벨 = ("부연", "참고", "사실관계", "참조", "참괴", "부엔", "부옌", "부옙", "창고", "찹고", "입법례")
_괄호 = re.compile(r"[\[［【]([^\]］】\n]{1,25})")
_한글 = re.compile(r"[가-힣]")


def _pymupdf():
    try:
        import pymupdf
    except ImportError:
        sys.exit("PyMuPDF 가 없다: pip install PyMuPDF")
    pymupdf.TOOLS.mupdf_display_errors(False)      # 'HiddenHorzOCR' 폰트 경고 숨김
    return pymupdf


def 줄들(page):
    """쪽의 줄 (y0, y1, 글자 크기, 글자). 같은 높이의 조각은 한 줄로 잇는다."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if t:
                out.append([l["bbox"][1], l["bbox"][3], max(s["size"] for s in l["spans"]), t])
    out.sort(key=lambda r: (round(r[0] / 3), r[0]))
    merged = []
    for r in out:
        if merged and abs(merged[-1][0] - r[0]) < 3:
            m = merged[-1]
            m[1], m[2], m[3] = max(m[1], r[1]), max(m[2], r[2]), m[3] + " " + r[3]
        else:
            merged.append(r)
    return merged


def 두문자줄(t):
    for m in _괄호.finditer(t):
        안 = m.group(1)
        if len(_한글.findall(안)) >= 2 and not any(k in 안 for k in _라벨):
            return True
    return False


def 범위(인자들):
    """인자 → [(이름, 첫 쪽, 끝 쪽)]. CH02 · 장2 · 2-07 · 011."""
    표 = 논점표()
    out = []
    for a in 인자들:
        m = re.fullmatch(r"(?:CH|장)?0?(\d)", a, re.I) if not re.fullmatch(r"\d{3}", a) else None
        if m and ("-" not in a):
            rs = [r for r in 표 if int(r["장"]) == int(m.group(1))]
            out += [(f"{int(r['장'])}-{r['장내번호']}", int(r["PDF시작"]), int(r["PDF끝"])) for r in rs]
        else:
            r = 찾기(a)
            out.append((f"{int(r['장'])}-{r['장내번호']}", int(r["PDF시작"]), int(r["PDF끝"])))
    return out


def 저장(조각, out, 이름):
    """[(설명, pixmap)] 을 12개씩 세로로 붙여 PNG 로. 저장한 경로 목록."""
    pymupdf = _pymupdf()
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    per = 12
    for k in range(math.ceil(len(조각) / per)):
        chunk = 조각[k * per:(k + 1) * per]
        H = sum(p.height for _, p in chunk) + 18 * len(chunk)
        W = max(p.width for _, p in chunk)
        c = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, W, H), False)
        c.set_rect(c.irect, (255, 255, 255))
        y = 0
        for _, p in chunk:
            p = p if p.n == 3 and not p.alpha else pymupdf.Pixmap(pymupdf.csRGB, p)
            p.set_origin(0, y + 14)
            c.copy(p, p.irect)
            y += p.height + 18
        path = out / f"{이름}_{k + 1:02d}.png"
        c.save(str(path))
        paths.append((path, [d for d, _ in chunk]))
    return paths


def main(argv):
    pymupdf = _pymupdf()
    out = Path(tempfile.gettempdir()) / "특허법_원본"
    책, 찾을, 쪽들, 아래, 인자들 = "기본서", [], [], 60, []
    it = iter(argv)
    for a in it:
        if a == "--out":
            out = Path(next(it))
        elif a == "--책":
            책 = next(it)
        elif a == "--아래":
            아래 = float(next(it))
        elif a == "--찾기":
            찾을 = [x for x in it]
        elif a == "--쪽":
            쪽들 = [int(x) for x in it]
        else:
            인자들.append(a)
    doc = pymupdf.open(원본PDF(책))

    if 쪽들:                                   # 쪽 전체
        조각 = [(f"{책} {n}쪽", doc[n - 1].get_pixmap(dpi=100)) for n in 쪽들]
        for path, ds in 저장(조각, out, f"{책}_쪽"):
            print(f"{path}   {' · '.join(ds)}")
        return
    if not 인자들:
        sys.exit(__doc__)

    조각 = []
    for 이름, 첫, 끝 in 범위(인자들):
        for n in range(첫, 끝 + 1):
            page = doc[n - 1]
            W = page.rect.width
            for y0, y1, size, t in 줄들(page):
                if 찾을:
                    if not any(k.replace(" ", "") in t.replace(" ", "") for k in 찾을):
                        continue
                    clip = pymupdf.Rect(20, max(0, y0 - 6), W - 15, y1 + 아래)
                elif 두문자줄(t) and size < 12.5:
                    clip = pymupdf.Rect(20, max(0, y0 - 4), W - 15, y1 + 5)
                else:
                    continue
                d = f"{이름} p{n}  {t[:60]}"
                조각.append((d, page.get_pixmap(dpi=110, clip=clip)))
                print(d)
    if not 조각:
        print("(잘라낼 줄이 없다)")
        return
    tag = re.sub(r"[^\w-]", "", "_".join(인자들))[:30]
    print()
    for path, ds in 저장(조각, out, tag + ("_찾기" if 찾을 else "")):
        print(f"{path}   ({len(ds)}줄: {ds[0].split('  ')[0]} ~ {ds[-1].split('  ')[0]})")


if __name__ == "__main__":
    main(sys.argv[1:])
