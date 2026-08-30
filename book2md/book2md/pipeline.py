"""파이프라인 (§3.3): 진단 → 추출 → 정규화 → 구조화 → 분할 → 검증 → 리포트.

각 단계 결과를 중간 파일로 남긴다. 실패하면 그 단계부터 다시 돌릴 수 있다.
페이지 단위로 흘려보내므로 200MB·수천 쪽이어도 통째로 메모리에 올리지 않는다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from . import diagnose as diag_mod
from .color import Palette, report as palette_report, to_rgb
from .emphasis import crops as emphasis_crops
from .footnotes import FootnoteCollector
from .model import Page, dump_pages, load_pages
from .normalize import Normalizer
from .parsers import get_parser
from .patterns import Patterns
from .split import split, write as write_parts
from .structure import Structurer, Block, render
from .validate import validate, reports as validation_reports, load_baseline

STAGES = ["extract", "normalize", "structure", "split", "validate"]


def _emphasis_by_page(blocks, cfg) -> tuple[dict, list]:
    """쪽마다 강조(==)가 몇 군데인지, 표준판례가 있는 쪽은 어디인지 (§V3).

    저자는 표준판례 판시를 색으로 칠해 두었다. 그 쪽에 강조가 거의 없으면
    색을 못 읽은 것이다 — 본문은 멀쩡해 보여도 답안 현출부가 통째로 사라진
    셈이라 그냥 넘어가면 안 된다.
    """
    mark = cfg["preserve"]["color"].get("markup", {}).get("emphasis", "==")
    rx = re.compile(re.escape(mark) + r".+?" + re.escape(mark), re.S)
    emph: dict[str, int] = {}
    standard: set[int] = set()
    for b in blocks:
        page = int(b.page or 0)
        if not page:
            continue
        n = len(rx.findall(b.text or ""))
        if n:
            emph[str(page)] = emph.get(str(page), 0) + n
        if any(c.get("standard") for c in (b.cases or [])):
            standard.add(page)
    return emph, sorted(standard)


def _removed_report(dropped, changes_path) -> str:
    """§P2-1 — 버린 줄을 전부 적는다.

    프로그램이 무엇을 버렸는지 사람이 볼 수 없으면, 본문 한 절이 꼬리말로
    오인돼 사라져도 알 길이 없다. 판정이 맞았는지는 사람이 본다.
    """
    L = ["# 버린 줄 (§P2-1)", "",
         "본문에서 빼기로 판정한 줄을 전부 적는다. **여기 본문이 섞여 있으면**",
         "`running.*` 또는 `legend.sidenote.pattern` 을 고쳐야 한다.", ""]
    by_kind: dict[str, list] = {}
    for page, kind, text in dropped:
        if text:
            by_kind.setdefault(kind, []).append((page, text))
    gone = []
    try:
        with open(changes_path, encoding="utf-8") as fh:
            for row in fh:
                if not row.strip():
                    continue
                ch = json.loads(row)
                if ch.get("kind") == "drop":
                    gone.append((ch.get("page", 0), ch.get("before", "")))
    except FileNotFoundError:
        pass
    if gone:
        by_kind["정규화 뒤 빈 줄"] = gone
    if not by_kind:
        L.append("없음")
    for kind, items in by_kind.items():
        L.append(f"## {kind} — {len(items)}줄")
        L.append("")
        seen: dict[str, int] = {}
        for _, text in items:
            seen[text] = seen.get(text, 0) + 1
        L.append("| 줄 | 횟수 | 처음 나온 쪽 |")
        L.append("|---|---:|---:|")
        first = {}
        for page, text in items:
            first.setdefault(text, page)
        for text, n in sorted(seen.items(), key=lambda kv: -kv[1])[:300]:
            L.append(f"| `{text[:90]}` | {n} | {first[text]} |")
        if len(seen) > 300:
            L.append(f"| … 외 {len(seen) - 300}종 | | |")
        L.append("")
    return "\n".join(L) + "\n"


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
                # 리포트가 쪽 그림을 뜨려면 원본을 다시 열어야 한다 (§P1-3)
                "source_path": str(Path(self.pdf).resolve()),
                "partial": self.pages is not None}
        try:
            import pymupdf
            with pymupdf.open(self.pdf) as doc:
                idx = range(doc.page_count) if self.pages is None else \
                    [i for i in self.pages if 0 <= i < doc.page_count]
                stars = cases = mnem = 0
                for i in idx:
                    text = doc[i].get_text("text")
                    stars += len(self.pat.case_star_loose.findall(text))
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
        dropped: list[tuple[int, str, str]] = []
        for page in load_pages(self.normalized):
            # 본문에서 빠지는 줄을 먼저 적어 둔다 (§P2-1). 머리말·꼬리말로 본
            # 판정이 틀렸다면 본문 한 절이 통째로 사라진 것이라 눈으로 봐야 한다.
            for line in page.lines:
                if line.zone == "header":
                    dropped.append((page.number, "머리말·꼬리말", line.text.strip()))
            for note in (page.sidenotes or []):
                if not note.get("kept", True):
                    dropped.append((page.number, "옆번호", str(note.get("text", ""))))
            found = collector.process(page)
            st.feed(page, found)
            pages += 1
        (self.reports / "removed_lines.md").write_text(
            _removed_report(dropped, self.changes), encoding="utf-8")
        blocks = st.finish()
        emph, standard = _emphasis_by_page(blocks, self.cfg)
        self._update_baseline(absorbed=st.absorbed_chars, line_chars=st.seen_chars,
                              emphasis_by_page=emph, standard_pages=standard)
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
        self._emphasis_fallback(res, base)
        # 프론트매터의 validation 값을 실제 판정으로 되쓴다
        for path in self.out.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("validation: PENDING",
                                         f"validation: {res.verdict}", 1), encoding="utf-8")
        self.log(f"[검증] {res.verdict} (FAIL {res.failed}, WARN {res.warned}) "
                 f"→ {self.reports}")
        return res.verdict

    def _emphasis_fallback(self, res, base) -> None:
        """§V3 가 얇다고 짚은 쪽의 표준판례 판시를 그림으로 떠 둔다 (§P0-2 폴백).

        색을 못 읽었을 때 전부를 포기하더라도 표준판례만은 확보해야 한다.
        판정은 하지 않는다 — 사람이 그림을 보고 손으로 표시한다.
        """
        if not res.counts.get("emphasis_thin_pages"):
            return
        emph = (base or {}).get("emphasis_by_page") or {}
        need = int(self.cfg["validation"].get("fail_on", {})
                   .get("emphasis_per_standard_page", 5))
        thin = [p for p in ((base or {}).get("standard_pages") or [])
                if emph.get(str(p), 0) < need]
        try:
            blocks = self._load_blocks()
        except FileNotFoundError:
            return
        made, index = emphasis_crops(blocks, (base or {}).get("source_path"),
                                     self.reports / "emphasis_check", self.cfg,
                                     pages=thin)
        if made:
            self.log(f"[강조 폴백] 표준판례 판시 {made}곳을 그림으로 떴다 → {index}")

    # ── 전체 ────────────────────────────────────────────────────
    def run(self, start: str = "extract") -> str:
        """start 단계부터 끝까지. 돌아온 값은 최종 판정(PASS/WARN/FAIL)."""
        verdict = "PASS"
        for stage in STAGES[STAGES.index(start):]:
            result = getattr(self, stage)()
            if stage == "validate":
                verdict = result
        return verdict
