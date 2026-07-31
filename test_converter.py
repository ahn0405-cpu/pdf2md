"""converter 회귀 테스트.

    python pdf2md/test_converter.py
    python -m unittest discover pdf2md
"""

from __future__ import annotations

import os
import struct
import sys
import threading
import unittest
import zlib

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import converter  # noqa: E402

KO, EN, ENB, ENI, MONO = "korea-s", "helv", "hebo", "heit", "cour"


def _png(w: int = 60, h: int = 40) -> bytes:
    raw = b"".join(b"\x00" + bytes([180] * (w * 3)) for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def _sample_pdf() -> bytes:
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
    page.insert_image(pymupdf.Rect(55, 240, 175, 320), stream=_png())
    page.insert_text((55, 360), "linked text", fontname=EN, fontsize=10.5)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(55, 350, 130, 364),
                      "uri": "https://example.com/"})
    page.insert_text((270, 800), "- 2 -", fontname=EN, fontsize=9)

    page = doc.new_page()
    page.insert_text((55, 45), "반복 머리말", fontname=KO, fontsize=9)
    page.insert_text((55, 110), "마지막 페이지 본문.", fontname=KO, fontsize=10.5)
    page.insert_text((270, 800), "- 3 -", fontname=EN, fontsize=9)

    return doc.tobytes()


class ConverterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pdf = _sample_pdf()
        cls.md = converter.convert(cls.pdf, "sample.pdf").markdown

    def test_headings(self) -> None:
        self.assertIn("# 보고서 제목", self.md)
        self.assertIn("## 1. 개요", self.md)

    def test_paragraph_lines_are_joined(self) -> None:
        self.assertIn("첫 줄이 여기서 끊기고 다음 줄로 이어진다.", self.md)

    def test_hyphenated_word_is_rejoined(self) -> None:
        self.assertIn("deliberately here.", self.md)

    def test_list_and_nesting(self) -> None:
        self.assertIn("- 첫째 항목", self.md)
        self.assertIn("  - 둘째 항목", self.md)
        self.assertIn("1. 번호 항목", self.md)

    def test_table(self) -> None:
        self.assertIn("| 항목 | 값 |", self.md)
        self.assertIn("| 매출 | 100 |", self.md)

    def test_inline_styles(self) -> None:
        self.assertIn("**bold**", self.md)
        self.assertIn("*slanted*", self.md)
        self.assertIn("```", self.md)

    def test_link_and_image(self) -> None:
        self.assertIn("(https://example.com/)", self.md)
        self.assertIn("![", self.md)

    def test_header_and_footer_removed(self) -> None:
        self.assertNotIn("반복 머리말", self.md)
        self.assertNotIn("- 1 -", self.md)

    def test_options_are_honoured(self) -> None:
        plain = converter.convert(self.pdf, "sample.pdf", {
            "detect_headings": False, "detect_lists": False,
            "inline_styles": False, "images": "skip", "tables": "skip",
        }).markdown
        self.assertNotIn("# 보고서 제목", plain)
        self.assertNotIn("**bold**", plain)
        self.assertNotIn("![", plain)

        base64_md = converter.convert(self.pdf, "sample.pdf", {"images": "base64"})
        self.assertIn("data:image/png;base64,", base64_md.markdown)
        self.assertEqual(base64_md.assets, [])

    def test_encrypted_pdf_raises(self) -> None:
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 100), "secret", fontsize=12)
        blob = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                           user_pw="pw", owner_pw="pw")
        with self.assertRaises(ValueError):
            converter.convert(blob, "enc.pdf")

    def test_broken_input_raises(self) -> None:
        with self.assertRaises(ValueError):
            converter.convert(b"definitely not a pdf", "bad.pdf")

    def test_concurrent_conversions_are_consistent(self) -> None:
        """MuPDF 컨텍스트가 하나뿐이라 동시 변환이 서로를 오염시키면 안 된다."""
        results: list[str] = []
        lock = threading.Lock()

        def run() -> None:
            out = converter.convert(self.pdf, "sample.pdf").markdown
            with lock:
                results.append(out)

        threads = [threading.Thread(target=run) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0], self.md)


class MarkdownEscapeTest(unittest.TestCase):
    """Markdown 로 옮길 때 문법이 깨지지 않는지."""

    def test_leading_number_escape_position(self) -> None:
        # `\1.` 은 Markdown 이스케이프가 아니라 역슬래시가 그대로 보인다
        self.assertEqual(converter._escape_leading("1. 본문"), "1\\. 본문")
        self.assertEqual(converter._escape_leading("2) 본문"), "2\\) 본문")
        self.assertEqual(converter._escape_leading("# 본문"), "\\# 본문")
        self.assertEqual(converter._escape_leading("보통 문장"), "보통 문장")

    def test_outer_emphasis_only_when_single_run(self) -> None:
        self.assertEqual(converter._strip_outer_emphasis("**제목**"), "제목")
        self.assertEqual(converter._strip_outer_emphasis("***제목***"), "제목")
        # 강조가 여러 개면 벗기면 안 된다
        self.assertEqual(converter._strip_outer_emphasis("**A** **B**"), "**A** **B**")

    def test_html_table_escapes_cells(self) -> None:
        html = converter._table_to_html([["<img src=x onerror=y>", "a&b"], ["c", "d"]])
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        self.assertIn("a&amp;b", html)

    def test_markdown_table_escapes_cells(self) -> None:
        md = converter._table_to_markdown([["a|b", "c*d*e"], ["줄1\n줄2", "x"]])
        self.assertIn("a\\|b", md)
        self.assertIn("c\\*d\\*e", md)
        self.assertIn("줄1<br>줄2", md)

    def test_code_span_keeps_inner_backticks(self) -> None:
        renderer = converter._Renderer(converter.Options(), 10.0, {}, [])
        span = converter.Span("`x`", 10, False, False, True, False, (0, 0, 0, 0))
        self.assertEqual(renderer.render_inline([span]), "`` `x` ``")


class LayoutTest(unittest.TestCase):
    def test_running_header_removed_only_at_page_edge(self) -> None:
        """머리말과 같은 문구가 본문에 있으면 본문 쪽은 남아야 한다."""
        doc = pymupdf.open()
        for i in range(4):
            page = doc.new_page()
            page.insert_text((55, 45), "제3장 위험 관리", fontname=KO, fontsize=9)
            page.insert_text((55, 120), f"{i + 1}쪽 본문.", fontname=KO, fontsize=10.5)
            if i == 2:
                page.insert_text((55, 200), "제3장 위험 관리", fontname=KO, fontsize=10.5)
            page.insert_text((280, 800), f"- {i + 1} -", fontname=EN, fontsize=9)

        md = converter.convert(doc.tobytes(), "t.pdf").markdown
        self.assertEqual(md.count("제3장 위험 관리"), 1)   # 본문 1회, 머리말 4회는 제거
        self.assertNotIn("- 1 -", md)

    def test_code_block_keeps_indentation(self) -> None:
        doc = pymupdf.open()
        page = doc.new_page()
        for i, (x, text) in enumerate([(55, "def f(x):"), (73, "if x:"),
                                       (91, "return 1"), (55, "f(2)")]):
            page.insert_text((x, 120 + i * 14), text, fontname=MONO, fontsize=9.5)

        md = converter.convert(doc.tobytes(), "c.pdf").markdown
        body = md.split("```")[1]
        self.assertIn("\ndef f(x):", body)
        indents = [len(l) - len(l.lstrip()) for l in body.strip("\n").split("\n")]
        self.assertEqual(indents[0], 0)
        self.assertLess(indents[0], indents[1])
        self.assertLess(indents[1], indents[2])
        self.assertEqual(indents[3], 0)

    def test_repeated_image_is_stored_once(self) -> None:
        blob = _png(80, 60)
        doc = pymupdf.open()
        for i in range(5):
            page = doc.new_page()
            page.insert_image(pymupdf.Rect(55, 100, 135, 160), stream=blob)
            page.insert_text((55, 300), f"{i + 1}쪽 내용.", fontname=KO, fontsize=10.5)

        result = converter.convert(doc.tobytes(), "logo.pdf")
        self.assertEqual(result.markdown.count("!["), 5)   # 나온 자리마다 참조는 유지
        self.assertEqual(len(result.assets), 1)            # 파일은 하나만


if __name__ == "__main__":
    unittest.main(verbosity=2)
