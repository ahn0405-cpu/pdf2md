"""pymupdf4llm 어댑터 (§3.2 텍스트 레이어 2순위, 경량)."""
from __future__ import annotations

from .markdown_base import MarkdownParser


class PyMuPDF4LLMParser(MarkdownParser):
    name = "pymupdf4llm"
    install_hint = "pip install pymupdf4llm"

    def available(self):
        try:
            import pymupdf4llm  # noqa: F401
        except Exception as exc:
            return False, f"import 실패: {exc}"
        return True, ""

    def _pages(self, pdf_path, pages, profile):
        import pymupdf4llm
        kwargs = {"page_chunks": True, "write_images": False}
        if pages is not None:
            kwargs["pages"] = list(pages)
        chunks = pymupdf4llm.to_markdown(pdf_path, **kwargs)
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            number = int(meta.get("page", 0)) or (chunks.index(chunk) + 1)
            yield number, chunk.get("text", "")
