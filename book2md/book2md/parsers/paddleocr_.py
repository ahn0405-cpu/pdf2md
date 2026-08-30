"""PaddleOCR 어댑터 (§3.2 스캔본 1순위, 한중일 인식률).

페이지를 300dpi 로 렌더링해 OCR 에 넣는다. 줄 순서는 y → x 로 세운다.
스캔본은 좌표가 있어도 글자 크기가 믿을 게 못 되므로 markdown 취급한다.
"""
from __future__ import annotations

from .markdown_base import MarkdownParser


class PaddleOCRParser(MarkdownParser):
    name = "paddleocr"
    install_hint = "pip install paddleocr paddlepaddle"

    def available(self):
        try:
            import paddleocr  # noqa: F401
            import pymupdf    # noqa: F401
        except Exception as exc:
            return False, f"import 실패: {exc}"
        return True, ""

    def _pages(self, pdf_path, pages, profile):
        import pymupdf
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(use_angle_cls=True, lang="korean", show_log=False)
        with pymupdf.open(pdf_path) as doc:
            idx = range(doc.page_count) if pages is None else pages
            for i in idx:
                if not (0 <= i < doc.page_count):
                    continue
                pix = doc[i].get_pixmap(dpi=300)
                result = ocr.ocr(pix.tobytes("png"), cls=True)
                rows = []
                for block in (result or []):
                    for box, (text, conf) in (block or []):
                        y = min(p[1] for p in box)
                        x = min(p[0] for p in box)
                        rows.append((round(y / 10), x, text))
                rows.sort()
                yield i + 1, "\n".join(t for _, _, t in rows)
