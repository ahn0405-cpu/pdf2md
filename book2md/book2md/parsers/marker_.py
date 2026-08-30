"""Marker 어댑터 (§3.2 텍스트 레이어 1순위, 각주·구조 처리 우수).

Marker 는 판올림마다 진입점이 바뀌어 왔다. 아래 두 갈래를 모두 시도하고
둘 다 안 되면 무엇이 없는지 그대로 알려 준다. 조용히 다른 파서로 넘어가지
않는다 — 파서가 바뀌면 결과가 바뀌고, 그건 사람이 알아야 한다.
"""
from __future__ import annotations

import re

from .markdown_base import MarkdownParser

_PAGE_BREAK = re.compile(r"\n-{3,}\n|\{\d+\}-{5,}")


class MarkerParser(MarkdownParser):
    name = "marker"
    install_hint = "pip install marker-pdf"

    def available(self):
        try:
            import marker  # noqa: F401
        except Exception as exc:
            return False, f"import 실패: {exc}"
        return True, ""

    def _pages(self, pdf_path, pages, profile):
        text = self._convert(pdf_path, pages)
        parts = _PAGE_BREAK.split(text)
        first = (pages.start + 1) if pages is not None else 1
        for k, part in enumerate(parts):
            yield first + k, part

    def _convert(self, pdf_path, pages) -> str:
        page_range = None
        if pages is not None:
            page_range = ",".join(str(p) for p in pages)
        try:                                   # marker 1.x
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.output import text_from_rendered
            config = {"paginate_output": True}
            if page_range:
                config["page_range"] = page_range
            converter = PdfConverter(artifact_dict=create_model_dict(), config=config)
            text, _, _ = text_from_rendered(converter(pdf_path))
            return text
        except ImportError:
            pass
        from marker.convert import convert_single_pdf   # marker 0.x
        from marker.models import load_all_models
        text, _, _ = convert_single_pdf(pdf_path, load_all_models())
        return text
