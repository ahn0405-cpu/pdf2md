"""MinerU 어댑터 (§3.2 2단 조판·한자 강함).

CLI 를 부른다. 파이썬 API 가 판올림마다 흔들려서, 오히려 CLI 쪽이 안정적이다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .markdown_base import MarkdownParser

_PAGE_BREAK = re.compile(r"\n-{3,}\n")


class MinerUParser(MarkdownParser):
    name = "mineru"
    install_hint = "pip install mineru  (또는 magic-pdf)"

    def _exe(self):
        return shutil.which("mineru") or shutil.which("magic-pdf")

    def available(self):
        exe = self._exe()
        if not exe:
            return False, "mineru / magic-pdf 실행 파일을 찾을 수 없다"
        return True, ""

    def _pages(self, pdf_path, pages, profile):
        exe = self._exe()
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [exe, "-p", str(pdf_path), "-o", tmp]
            if pages is not None:
                cmd += ["-s", str(pages.start), "-e", str(pages.stop - 1)]
            subprocess.run(cmd, check=True, capture_output=True)
            mds = sorted(Path(tmp).rglob("*.md"))
            if not mds:
                raise RuntimeError(f"MinerU 가 마크다운을 내놓지 않았다: {cmd}")
            text = mds[0].read_text(encoding="utf-8")
        first = (pages.start + 1) if pages is not None else 1
        for k, part in enumerate(_PAGE_BREAK.split(text)):
            yield first + k, part
