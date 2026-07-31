"""테스트용 PDF 만들기 (개발 도구).

산출물은 test/fixtures/ 에 커밋되어 있으므로 평소에는 실행할 필요가 없다.
테스트 문서를 바꿀 때만 돌린다.

    pip install pymupdf
    python test/make-fixtures.py
"""

from __future__ import annotations

import os
import struct
import zlib

import pymupdf

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
KO, EN, ENB, ENI, MONO = "korea-s", "helv", "hebo", "heit", "cour"


def png(w: int = 80, h: int = 60, shade: int = 180) -> bytes:
    raw = b"".join(b"\x00" + bytes([shade] * (w * 3)) for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def basic() -> pymupdf.Document:
    """제목·문단·목록·표·강조·코드·링크·이미지·머리말/꼬리말·하이픈."""
    doc = pymupdf.open()

    page = doc.new_page()
    page.insert_text((55, 70), "보고서 제목", fontname=KO, fontsize=20)
    page.insert_text((55, 120), "1. 개요", fontname=KO, fontsize=15)
    page.insert_text((55, 145), "첫 줄이 여기서 끊기고 다음", fontname=KO, fontsize=10.5)
    page.insert_text((55, 161), "줄로 이어진다.", fontname=KO, fontsize=10.5)
    page.insert_text((60, 200), "• 첫째 항목", fontname=KO, fontsize=10.5)
    page.insert_text((82, 218), "• 둘째 항목", fontname=KO, fontsize=10.5)
    page.insert_text((60, 236), "1) 번호 항목", fontname=KO, fontsize=10.5)

    x0, y0, cw, rh = 55, 270, 120, 22
    for r in range(3):
        page.draw_line((x0, y0 + r * rh), (x0 + 2 * cw, y0 + r * rh), width=0.7)
    for c in range(3):
        page.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + 2 * rh), width=0.7)
    for r, row in enumerate([["항목", "값"], ["매출", "100"]]):
        for c, val in enumerate(row):
            page.insert_text((x0 + c * cw + 5, y0 + r * rh + 15), val, fontname=KO, fontsize=10)
    page.insert_text((270, 800), "- 1 -", fontname=EN, fontsize=9)

    page = doc.new_page()
    page.insert_text((55, 45), "반복 머리말", fontname=KO, fontsize=9)
    page.insert_text((55, 110), "Plain ", fontname=EN, fontsize=10.5)
    page.insert_text((92, 110), "bold", fontname=ENB, fontsize=10.5)
    page.insert_text((116, 110), " and ", fontname=EN, fontsize=10.5)
    page.insert_text((143, 110), "slanted", fontname=ENI, fontsize=10.5)
    page.insert_text((55, 140), "a word split deliber-", fontname=EN, fontsize=10.5)
    page.insert_text((55, 156), "ately here.", fontname=EN, fontsize=10.5)
    page.insert_text((55, 190), "run(x)", fontname=MONO, fontsize=9.5)
    page.insert_text((55, 204), "run(y)", fontname=MONO, fontsize=9.5)
    page.insert_image(pymupdf.Rect(55, 240, 175, 320), stream=png())
    page.insert_text((55, 360), "linked text", fontname=EN, fontsize=10.5)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(55, 350, 130, 364),
                      "uri": "https://example.com/"})
    page.insert_text((270, 800), "- 2 -", fontname=EN, fontsize=9)

    page = doc.new_page()
    page.insert_text((55, 45), "반복 머리말", fontname=KO, fontsize=9)
    page.insert_text((55, 110), "마지막 페이지 본문.", fontname=KO, fontsize=10.5)
    page.insert_text((270, 800), "- 3 -", fontname=EN, fontsize=9)
    return doc


def header_in_body() -> pymupdf.Document:
    """머리말과 같은 문구가 본문에도 나오는 경우."""
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((55, 45), "제3장 위험 관리", fontname=KO, fontsize=9)
        page.insert_text((55, 120), f"{i + 1}쪽 본문.", fontname=KO, fontsize=10.5)
        if i == 2:
            page.insert_text((55, 200), "제3장 위험 관리", fontname=KO, fontsize=10.5)
        page.insert_text((280, 800), f"- {i + 1} -", fontname=EN, fontsize=9)
    return doc


def repeated_label() -> pymupdf.Document:
    """매 페이지 반복되지만 같은 줄에 내용이 이어지는 본문 말머리."""
    doc = pymupdf.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((55, 110), f"{i + 1}쪽 본문.", fontname=KO, fontsize=10.5)
        page.insert_text((55, 740), "추천 대상:", fontname=KO, fontsize=10)
        page.insert_text((130, 740), f"{i + 1}번 분야", fontname=KO, fontsize=10)
        page.insert_text((280, 780), f"- {i + 1} -", fontname=EN, fontsize=9)
    return doc


def indented_code() -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, (x, text) in enumerate([(55, "def f(x):"), (73, "if x:"),
                                   (91, "return 1"), (55, "f(2)")]):
        page.insert_text((x, 120 + i * 14), text, fontname=MONO, fontsize=9.5)
    return doc


def repeated_image() -> pymupdf.Document:
    doc = pymupdf.open()
    blob = png()
    for i in range(5):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(55, 100, 135, 160), stream=blob)
        page.insert_text((55, 300), f"{i + 1}쪽 내용.", fontname=KO, fontsize=10.5)
    return doc


def two_columns() -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((55, 70), "전폭 제목", fontname=KO, fontsize=18)
    left = ["왼쪽 단의 첫 문장이다.", "왼쪽 단의 둘째 줄이다.", "왼쪽 단의 마지막이다."]
    right = ["오른쪽 단의 첫 문장이다.", "오른쪽 단의 둘째 줄이다.", "오른쪽 단의 마지막이다."]
    for i, text in enumerate(left):
        page.insert_text((55, 140 + i * 16), text, fontname=KO, fontsize=10.5)
    for i, text in enumerate(right):
        page.insert_text((320, 140 + i * 16), text, fontname=KO, fontsize=10.5)
    return doc


def scanned() -> pymupdf.Document:
    doc = pymupdf.open()
    blob = png(400, 300, 200)
    for _ in range(2):
        doc.new_page().insert_image(pymupdf.Rect(50, 50, 545, 420), stream=blob)
    return doc


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, builder in [
        ("basic", basic), ("header-in-body", header_in_body),
        ("repeated-label", repeated_label), ("indented-code", indented_code),
        ("repeated-image", repeated_image), ("two-columns", two_columns),
        ("scanned", scanned),
    ]:
        doc = builder()
        doc.save(os.path.join(OUT, f"{name}.pdf"))
        doc.close()
        print(f"  {name}.pdf")

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "secret", fontsize=12)
    doc.save(os.path.join(OUT, "encrypted.pdf"),
             encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    doc.close()
    print("  encrypted.pdf")

    with open(os.path.join(OUT, "broken.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4\nthis is not a valid pdf body\n")
    print("  broken.pdf")


if __name__ == "__main__":
    main()
