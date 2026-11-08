"""Upstage Document Parse 어댑터 (§3.2 스캔본 2순위).

문서를 외부 서비스로 보낸다. 그래서 기본값은 꺼져 있고, 환경변수
UPSTAGE_API_KEY 가 있을 때만 쓸 수 있다. 자료를 밖으로 내보내도 되는지
먼저 판단할 것.
"""
from __future__ import annotations

import os

from .markdown_base import MarkdownParser

_URL = "https://api.upstage.ai/v1/document-digitization"


class UpstageParser(MarkdownParser):
    name = "upstage"
    install_hint = "pip install requests  +  환경변수 UPSTAGE_API_KEY 설정"

    def available(self):
        if not os.environ.get("UPSTAGE_API_KEY"):
            return False, "UPSTAGE_API_KEY 가 없다 (문서를 외부로 보내는 파서다)"
        try:
            import requests  # noqa: F401
        except Exception as exc:
            return False, f"import 실패: {exc}"
        return True, ""

    def _pages(self, pdf_path, pages, profile):
        import requests

        with open(pdf_path, "rb") as fh:
            resp = requests.post(
                _URL,
                headers={"Authorization": f"Bearer {os.environ['UPSTAGE_API_KEY']}"},
                files={"document": fh},
                data={"model": "document-parse", "output_formats": '["markdown"]'},
                timeout=600,
            )
        resp.raise_for_status()
        data = resp.json()
        by_page: dict[int, list[str]] = {}
        for el in data.get("elements", []):
            by_page.setdefault(int(el.get("page", 1)), []).append(
                el.get("content", {}).get("markdown", "")
            )
        for number in sorted(by_page):
            if pages is not None and (number - 1) not in pages:
                continue
            yield number, "\n".join(by_page[number])
