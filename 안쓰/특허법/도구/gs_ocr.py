#!/usr/bin/env python3
"""박형준 기초 GS PDF → 쪽 그림 → Windows OCR(한국어) JSON + 형광펜 사각형 JSON.

GS PDF 는 HWP 를 「Microsoft Print to PDF」로 찍은 것이라 글자가 벡터 그림이다(뽑을 글자 없음).
형광펜은 벡터 사각형이라 색과 자리를 정확히 읽는다.

    python gs_ocr.py               전 쪽 (이미 있는 쪽은 건너뜀)
    python gs_ocr.py 2-30          쪽 범위만

산물(안쓰/_work/박형준/, 커밋하지 않음)
    p###.png    250dpi 흑백 — 형광펜 바탕을 흰색으로 지워 OCR 을 돕는다
    p###.json   OCR 줄·낱말·상자(화소)        ← ocr.ps1
    p###.hl.json 형광펜 사각형 [{색, x0,y0,x1,y1}] (화소)
"""
import json
import subprocess
import sys
from pathlib import Path

import fitz

여기 = Path(__file__).resolve().parent
특허법 = 여기.parent
후보 = [특허법 / "원본" / "26년 박형준 기초 gs.pdf", 특허법.parent.parent / "도쓰" / "26년 박형준 기초 gs.pdf"]
PDF = next((p for p in 후보 if p.exists()), 후보[0])
작업 = 특허법.parent / "_work" / "박형준"

DPI = 250
Z = DPI / 72
흑백 = bytes((0 if v < 150 else 255) for v in range(256))

# 형광펜 색(채움 RGB, 소수 둘째 자리) → 이름
색이름 = {
    (0.93, 0.83, 0.79): "판례",      # 살구
    (0.8, 0.95, 0.89): "조문",       # 연두
    (0.87, 0.9, 0.97): "취지",       # 하늘 — 취지·학설·검토
    (0.92, 0.87, 0.95): "사안",      # 보라
    (1.0, 0.94, 0.6): "머리",        # 노랑 — 번호 목차
    (1.0, 0.91, 0.4): "머리",
    (1.0, 0.97, 0.8): "머리2",       # 연노랑
}


def 범위(argv):
    for a in argv:
        if "-" in a and a.replace("-", "").isdigit():
            s, e = a.split("-")
            return range(int(s), int(e) + 1)
    return None


def 렌더(doc, 쪽들):
    작업.mkdir(parents=True, exist_ok=True)
    n = 0
    for no in 쪽들:
        png = 작업 / f"p{no:03d}.png"
        hl = 작업 / f"p{no:03d}.hl.json"
        page = doc[no - 1]
        if not png.exists():
            pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
            fitz.Pixmap(fitz.csGRAY, pix.width, pix.height, pix.samples.translate(흑백), False).save(png)
            n += 1
        if not hl.exists():
            칸 = []
            for dr in page.get_drawings():
                f = dr.get("fill")
                if not f:
                    continue
                이름 = 색이름.get(tuple(round(x, 2) for x in f))
                r = dr["rect"]
                if 이름 and r.width > 3 and r.height > 3:
                    칸.append({"색": 이름, "x0": r.x0 * Z, "y0": r.y0 * Z, "x1": r.x1 * Z, "y1": r.y1 * Z})
            # 테두리 상자(문제 머리·키워드 상자) — 채움 없는 사각형 선
            상자 = []
            for dr in page.get_drawings():
                r = dr["rect"]
                if not dr.get("fill") and dr.get("color") is not None and r.width > 200 and 15 < r.height < 200:
                    상자.append({"x0": r.x0 * Z, "y0": r.y0 * Z, "x1": r.x1 * Z, "y1": r.y1 * Z})
            hl.write_text(json.dumps({"형광": 칸, "상자": 상자}, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"렌더 {n}쪽 → {작업}")


def ocr():
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(여기 / "ocr.ps1"), "-Dir", str(작업)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip(), r.stderr.strip()[:500])


def main(argv):
    doc = fitz.open(PDF)
    쪽들 = 범위(argv) or range(1, doc.page_count + 1)
    렌더(doc, 쪽들)
    ocr()


if __name__ == "__main__":
    main(sys.argv[1:])
