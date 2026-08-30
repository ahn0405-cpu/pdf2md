"""CLI (§7).

    convert diagnose 기본서.pdf
    convert run 기본서.pdf --pages 120-145 --profile textbook
    convert run 기본서.pdf --profile textbook --out output/기본서/
    convert validate output/
    convert crosscheck output/기본서/ output/사례집/

§8 의 개발 순서를 강제한다. 진단 없이 run 을 부르면 막는다. 진단이 파서 선택의
근거이기 때문이고, 진단을 건너뛴 전체 변환은 문제가 나면 처음부터 다시 해야
하기 때문이다. 정말 급하면 --force 로 넘길 수 있다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import diagnose as diag_mod
from .config import load_config, profile as get_profile
from .crosscheck import crosscheck
from .parsers import availability, get_parser, pick_parser
from .pipeline import Pipeline, STAGES
from .validate import validate as run_validate, reports as validation_reports, load_baseline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="convert", description="민사소송법 기본서·사례집 PDF → Markdown")
    ap.add_argument("--config", help="config.yaml 경로")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diagnose", help="사전 진단 (§3.1). 변환 전 반드시 먼저.")
    d.add_argument("pdf")
    d.add_argument("--out", default="output", help="출력 루트 (기본 output)")
    d.add_argument("--sample", type=int, default=24, help="표본 쪽수 (기본 24)")
    d.add_argument("--layout-pages", type=int, default=3,
                   help="조판을 상세히 볼 쪽수 (§3.1-2, 기본 3)")
    d.add_argument("--pages", help="조판을 볼 쪽을 직접 지정. 예: 120-122")

    r = sub.add_parser("run", help="변환 (§3.3)")
    r.add_argument("pdf")
    r.add_argument("--profile", required=True, help="textbook | casebook")
    r.add_argument("--out", help="기본 output/<프로파일 이름>/")
    r.add_argument("--pages", help="1-based 범위. 예: 120-145")
    r.add_argument("--parser", help="파서 이름. 없으면 진단 결과로 고른다")
    r.add_argument("--from", dest="start", choices=STAGES, default="extract",
                   help="이 단계부터 다시 (중간 파일 재사용)")
    r.add_argument("--force", action="store_true", help="진단 없이 강행")
    r.add_argument("--emphasis", choices=["on", "off"], help="색상 → 강조 마크업")

    v = sub.add_parser("validate", help="검증만 다시 (§5)")
    v.add_argument("dir")
    v.add_argument("--baseline", help="baseline.json 경로")

    c = sub.add_parser("crosscheck", help="두 소스 교차 검증 (§5.3)")
    c.add_argument("dir_a")
    c.add_argument("dir_b")
    c.add_argument("--labels", default="기본서,사례집")

    sub.add_parser("parsers", help="쓸 수 있는 파서 보기")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    return globals()[f"_cmd_{args.cmd}"](args, cfg)


# ── diagnose ────────────────────────────────────────────────────
def _cmd_diagnose(args, cfg) -> int:
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"파일이 없다: {pdf}", file=sys.stderr)
        return 2
    reports = Path(args.out) / "_reports"
    print(f"[진단] {pdf} …")
    d = diag_mod.run(str(pdf), cfg, sample=args.sample,
                     layout_pages=args.layout_pages,
                     layout_range=_page_range(getattr(args, "pages", None)))
    d["profile_hint"] = _guess_profile(d, cfg)
    md, js = diag_mod.save(d, cfg, reports)
    print(diag_mod.report(d, cfg))
    print(f"→ {md}\n→ {js}")
    if not d["text_layer"]:
        print("\n※ 텍스트 레이어가 없다. OCR 파서로 가야 한다 (§3.2).")
    return 0


def _guess_profile(d: dict, cfg: dict) -> str:
    """문제 번호(E-5)가 보이면 사례집으로 본다."""
    import re
    joined = " ".join(" ".join(p["cases"]) for p in d["pages_detail"])
    text_hint = d.get("sidenote", {}).get("found", 0)
    if text_hint:
        return "textbook"
    return "casebook" if re.search(r"\b[A-Z]-\d+\.", joined) else "textbook"


# ── run ─────────────────────────────────────────────────────────
def _cmd_run(args, cfg) -> int:
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"파일이 없다: {pdf}", file=sys.stderr)
        return 2
    prof = get_profile(cfg, args.profile)
    if args.emphasis:
        prof["emphasis"] = args.emphasis == "on"

    out = Path(args.out) if args.out else Path("output") / prof.get("label", args.profile)
    root = out.parent
    reports = root / "_reports"
    work = root / "_work" / pdf.stem

    diagnosis = _load_diagnosis(reports, pdf)
    if diagnosis is None and not args.force and args.start == "extract":
        print(f"진단 결과가 없다. 먼저 이것부터 돌릴 것 (§3.1, §8):\n"
              f"  convert diagnose {pdf} --out {root}\n"
              f"정말 건너뛰려면 --force", file=sys.stderr)
        return 2

    parser_name = args.parser
    if not parser_name:
        parser_name = pick_parser(cfg, diagnosis or {}).name
    pages = _page_range(args.pages)

    pipe = Pipeline(pdf, cfg, prof, out, reports, work, parser_name, pages)
    verdict = pipe.run(args.start)
    print(f"\n판정: {verdict}")
    if verdict == "FAIL":
        print(f"FAIL 이 있다. {reports / 'warnings.md'} 를 보고 config.yaml 을 고친 뒤 "
              f"다시 돌릴 것 (§5.8). 다음 단계로 넘어가지 말 것.", file=sys.stderr)
        return 1
    return 0


def _load_diagnosis(reports: Path, pdf: Path):
    for path in (reports / f"diagnosis-{pdf.stem}.json", reports / "diagnosis.json"):
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if Path(d.get("file", "")).name == pdf.name:
            return d
    return None


def _page_range(spec):
    if not spec:
        return None
    if "-" in spec:
        a, b = spec.split("-", 1)
    else:
        a = b = spec
    return range(int(a) - 1, int(b))          # 1-based 포함 범위 → 0-based


# ── validate ────────────────────────────────────────────────────
def _cmd_validate(args, cfg) -> int:
    root = Path(args.dir)
    reports = root / "_reports" if (root / "_reports").exists() else root.parent / "_reports"
    baseline = load_baseline(args.baseline) if args.baseline else \
        _merge_baselines(root)
    res = run_validate(root, cfg, baseline)
    reports.mkdir(parents=True, exist_ok=True)
    for name, text in validation_reports(res, cfg).items():
        (reports / name).write_text(text, encoding="utf-8")
    print((reports / "validation.md").read_text(encoding="utf-8"))
    print(f"→ {reports}")
    return 1 if res.verdict == "FAIL" else 0


def _merge_baselines(root: Path) -> dict | None:
    """_work/*/baseline.json 을 합친다. 여러 소스를 한꺼번에 검증할 때."""
    files = sorted((root / "_work").glob("*/baseline.json")) if (root / "_work").exists() \
        else sorted(root.glob("_work/*/baseline.json"))
    if not files:
        files = sorted(root.parent.glob("_work/*/baseline.json"))
    if not files:
        return None
    merged: dict = {}
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for k, v in d.items():
            if isinstance(v, (int, float)):
                merged[k] = merged.get(k, 0) + v
            else:
                merged.setdefault(k, v)
    return merged


# ── crosscheck ──────────────────────────────────────────────────
def _cmd_crosscheck(args, cfg) -> int:
    la, lb = (args.labels.split(",") + ["A", "B"])[:2]
    text, mismatches = crosscheck(args.dir_a, args.dir_b, cfg, la, lb)
    root = Path(args.dir_a).parent
    reports = root / "_reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "crosscheck.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"→ {reports / 'crosscheck.md'}")
    if mismatches:
        print(f"\n두문자 불일치 의심 {mismatches}건. 사람이 판단할 것 (§2.2). "
              f"자동 교정하지 않았다.", file=sys.stderr)
        return 1
    return 0


# ── parsers ─────────────────────────────────────────────────────
def _cmd_parsers(args, cfg) -> int:
    print(f"{'파서':<14}{'가능':<6}{'좌표/색':<8}사유")
    for name, ok, why, layout in availability():
        print(f"{name:<14}{'○' if ok else '×':<6}{'○' if layout else '-':<8}{why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
