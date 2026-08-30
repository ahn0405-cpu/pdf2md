"""파이프라인 (§3.3): 진단 → 추출 → 정규화 → 구조화 → 분할 → 검증 → 리포트.

각 단계 결과를 중간 파일로 남긴다. 실패하면 그 단계부터 다시 돌릴 수 있다.
페이지 단위로 흘려보내므로 200MB·수천 쪽이어도 통째로 메모리에 올리지 않는다.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import diagnose as diag_mod
from .color import Palette, report as palette_report, to_rgb
from .footnotes import FootnoteCollector
from .model import Page, dump_pages, load_pages
from .normalize import Normalizer
from .parsers import get_parser
from .patterns import Patterns
from .split import split, write as write_parts
from .structure import Structurer, Block, render
from .validate import validate, reports as validation_reports, load_baseline

STAGES = ["extract", "normalize", "structure", "split", "validate"]


class Pipeline:
    def __init__(self, pdf_path, cfg, prof, out_dir, reports_dir, work_dir,
                 parser_name, pages=None, log=print):
        self.pdf = str(pdf_path)
        self.cfg = cfg
        self.prof = dict(prof)
        self.prof["_config"] = cfg
        self.pat = Patterns.build(cfg)
        self.out = Path(out_dir)
        self.reports = Path(reports_dir)
        self.work = Path(work_dir)
        self.parser_name = parser_name
        self.pages = pages
        self.log = log
        for d in (self.out, self.reports, self.work):
            d.mkdir(parents=True, exist_ok=True)

    # 중간 파일
    @property
    def raw(self): return self.work / "01_raw.jsonl"
    @property
    def baseline(self): return self.work / "baseline.json"
    @property
    def normalized(self): return self.work / "02_normalized.jsonl"
    @property
    def changes(self): return self.work / "02_changes.jsonl"
    @property
    def blocks_file(self): return self.work / "03_blocks.jsonl"
    @property
    def structured(self): return self.work / "03_structured.md"

    # ── 1. 추출 ─────────────────────────────────────────────────
    def extract(self) -> None:
        parser = get_parser(self.parser_name)
        parser.require()
        self.log(f"[추출] 파서={parser.name}")
        n = dump_pages(parser.parse(self.pdf, self.pages, self.prof), self.raw)
        base = self._baseline(n)
        if getattr(parser, "palette", None):
            pal = parser.palette
            base["colored_spans"] = pal.colored_spans
            base["colored_chars"] = sum(pal.chars.values())
            base["total_spans"] = pal.total_spans
            base["distinct_colors"] = len(pal.counts)
            base["color_source"] = getattr(parser, "color_source", "span")
            (self.reports / "palette.md").write_text(palette_report(pal), encoding="utf-8")
        self.baseline.write_text(json.dumps(base, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        self.log(f"[추출] {n}쪽 → {self.raw.name}, 별표 {base.get('stars')}건")

    def _baseline(self, page_count: int) -> dict:
        """§5.2 대조용 원본 카운트.

        파서와 무관한 별도 추출(PyMuPDF 원문)로 센다. 파서가 뭔가를 흘리면
        여기서 드러나야 하기 때문이다.
        """
        base = {"pages": page_count, "source": Path(self.pdf).name,
                "partial": self.pages is not None}
        try:
            import pymupdf
            with pymupdf.open(self.pdf) as doc:
                idx = range(doc.page_count) if self.pages is None else \
                    [i for i in self.pages if 0 <= i < doc.page_count]
                stars = cases = mnem = 0
                for i in idx:
                    text = doc[i].get_text("text")
                    stars += len(self.pat.case_star.findall(text))
                    cases += len(self.pat.case_loose.findall(text))
                    mnem += len(self.pat.find_mnemonics(text))
                base.update(stars=stars, cases=cases, mnemonics=mnem,
                            baseline_source="pymupdf get_text (파서와 독립)")
        except Exception as exc:                       # pragma: no cover
            base["baseline_error"] = str(exc)
        return base

    # ── 2. 정규화 ───────────────────────────────────────────────
    def normalize(self) -> None:
        norm = Normalizer(self.cfg, self.pat)
        changes = 0
        with open(self.changes, "w", encoding="utf-8") as log:
            def gen():
                nonlocal changes
                for page in load_pages(self.raw):
                    for ch in norm.normalize_page(page):
                        log.write(json.dumps(asdict(ch), ensure_ascii=False) + "\n")
                        changes += 1
                    yield page
            n = dump_pages(gen(), self.normalized)
        self.log(f"[정규화] {n}쪽, 손댄 자리 {changes}곳 → {self.changes.name}")

    # ── 3. 구조화 ───────────────────────────────────────────────
    def structure(self) -> None:
        collector = FootnoteCollector(self.cfg, self.pat)
        st = Structurer(self.cfg, self.prof, self.pat)
        pages = 0
        for page in load_pages(self.normalized):
            found = collector.process(page)
            st.feed(page, found)
            pages += 1
        blocks = st.finish()
        self._update_baseline(absorbed=st.absorbed_chars, line_chars=st.seen_chars)
        with open(self.blocks_file, "w", encoding="utf-8") as fh:
            for b in blocks:
                fh.write(json.dumps(asdict(b), ensure_ascii=False) + "\n")
        self.structured.write_text(render(blocks), encoding="utf-8")
        heads = sum(1 for b in blocks if b.kind == "heading")
        fns = sum(1 for b in blocks if b.kind == "footnotes")
        self.log(f"[구조화] {pages}쪽 → 블록 {len(blocks)} (헤딩 {heads}, 각주블록 {fns})")

    def _update_baseline(self, **fields) -> None:
        """뒤 단계에서 알게 된 값을 baseline 에 적어 둔다."""
        if not self.baseline.exists():
            return
        data = json.loads(self.baseline.read_text(encoding="utf-8"))
        data.update(fields)
        self.baseline.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    # ── 4. 분할 ─────────────────────────────────────────────────
    def split(self) -> list[str]:
        blocks = self._load_blocks()
        parts = split(blocks, self.prof)
        written, removed = write_parts(parts, self.out, self.prof,
                                       self.parser_name, "PENDING")
        note = f", 지난 결과 {len(removed)}개 지움" if removed else ""
        self.log(f"[분할] 파일 {len(written)}개 → {self.out}{note}")
        if removed:
            self.log("        " + ", ".join(removed[:8]) +
                     (" …" if len(removed) > 8 else ""))
        return written

    def _load_blocks(self) -> list[Block]:
        out = []
        with open(self.blocks_file, encoding="utf-8") as fh:
            for row in fh:
                if row.strip():
                    out.append(Block(**json.loads(row)))
        return out

    # ── 5. 검증 ─────────────────────────────────────────────────
    def validate(self) -> str:
        base = load_baseline(self.baseline)
        res = validate(self.out, self.cfg, base)
        for name, text in validation_reports(res, self.cfg).items():
            (self.reports / name).write_text(text, encoding="utf-8")
        # 프론트매터의 validation 값을 실제 판정으로 되쓴다
        for path in self.out.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("validation: PENDING",
                                         f"validation: {res.verdict}", 1), encoding="utf-8")
        self.log(f"[검증] {res.verdict} (FAIL {res.failed}, WARN {res.warned}) "
                 f"→ {self.reports}")
        return res.verdict

    # ── 전체 ────────────────────────────────────────────────────
    def run(self, start: str = "extract") -> str:
        """start 단계부터 끝까지. 돌아온 값은 최종 판정(PASS/WARN/FAIL)."""
        verdict = "PASS"
        for stage in STAGES[STAGES.index(start):]:
            result = getattr(self, stage)()
            if stage == "validate":
                verdict = result
        return verdict
