"""파서 레지스트리. 설정에서 이름으로 고른다 (§3.2)."""
from __future__ import annotations

from .base import Parser, ParserUnavailable
from .marker_ import MarkerParser
from .mineru_ import MinerUParser
from .paddleocr_ import PaddleOCRParser
from .pymupdf4llm_ import PyMuPDF4LLMParser
from .pymupdf_native import PyMuPDFParser
from .textfile import TextFileParser
from .upstage_ import UpstageParser

REGISTRY: dict[str, type[Parser]] = {
    p.name: p for p in (
        PyMuPDFParser, PyMuPDF4LLMParser, MarkerParser,
        MinerUParser, PaddleOCRParser, UpstageParser, TextFileParser,
    )
}


def get_parser(name: str) -> Parser:
    if name not in REGISTRY:
        raise SystemExit(f"모르는 파서 '{name}'. 쓸 수 있는 것: {', '.join(REGISTRY)}")
    return REGISTRY[name]()


def pick_parser(cfg: dict, diagnosis: dict) -> Parser:
    """진단 결과에 맞는 파서 중 실제로 설치돼 있는 첫 번째를 고른다."""
    key = diagnosis.get("parser_key", "text_single_column")
    order = cfg["parsers"]["by_diagnosis"].get(key, ["pymupdf"])
    tried = []
    for name in order:
        parser = get_parser(name)
        ok, why = parser.available()
        if ok:
            return parser
        tried.append(f"{name}({why})")
    raise SystemExit(
        "쓸 수 있는 파서가 없다. 시도: " + ", ".join(tried) +
        "\n  requirements.txt 의 주석을 보고 필요한 파서를 설치할 것."
    )


def availability() -> list[tuple[str, bool, str, bool]]:
    """(이름, 쓸 수 있나, 사유, 좌표 파서인가)"""
    rows = []
    for name, cls in REGISTRY.items():
        parser = cls()
        ok, why = parser.available()
        rows.append((name, ok, why or "", parser.layout_aware))
    return rows
