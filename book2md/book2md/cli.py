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
from .crosscheck import crosscheck, read_decisions, merge_corrections
from . import mapping as map_mod
from .parsers import availability, get_parser, pick_parser
from .pipeline import Pipeline, STAGES
from .validate import validate as run_validate, reports as validation_reports, load_baseline


def _force_utf8() -> None:
    """콘솔 인코딩 때문에 리포트 출력이 죽지 않게 한다.

    Windows 기본 콘솔은 cp949 라서 리포트의 `☑ ⚠️ ✅` 에서 UnicodeEncodeError 로
    멈춘다. 파일은 어차피 UTF-8 로 쓰므로, 화면 출력만 UTF-8 로 돌리고
    그래도 못 찍는 글자는 대체 문자로 흘려보낸다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                      # pragma: no cover - 아주 오래된 파이썬
            pass


def main(argv=None) -> int:
    _force_utf8()
    ap = argparse.ArgumentParser(
        prog="convert", description="민사소송법 기본서·사례집 PDF → Markdown")
    ap.add_argument("--config", help="config.yaml 경로")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diagnose", help="사전 진단 (§3.1). 변환 전 반드시 먼저.")
    d.add_argument("pdf", help="PDF 파일, 또는 PDF 가 든 폴더(안의 PDF 를 모두 진단)")
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

    ad = sub.add_parser("apply-decisions",
                        help="두문자 결정표(§P1-3)에 표시한 대로 config.yaml 을 고친다")
    ad.add_argument("decisions", help="_reports/mnemonic_conflicts.md")
    ad.add_argument("--dry-run", action="store_true", help="무엇이 들어갈지만 보여준다")

    al = sub.add_parser("all", help="폴더 안 PDF 를 진단→변환→검증→교차검증까지 한 번에")
    al.add_argument("pdf_dir", help="PDF 가 든 폴더 (또는 PDF 파일 하나)")
    al.add_argument("--out", default="output", help="출력 루트 (기본 output)")
    al.add_argument("--pages", help="시험 삼아 이 범위만. 예: 168-178")
    al.add_argument("--parser", help="파서 이름 (기본: 진단 결과로 고름)")
    al.add_argument("--profile", help="모든 파일에 이 프로파일을 쓴다 (기본: 파일마다 추정)")

    pr = sub.add_parser("probe", help="원문 증거 뜨기. 진단이 '없다'고 할 때 확인용.")
    pr.add_argument("pdf")
    pr.add_argument("--find", help="이 글자가 몇 쪽에 있는지 (변환할 장 고를 때)")
    pr.add_argument("--page", type=int, help="이 쪽의 span·도형을 전부 덤프")
    pr.add_argument("--color", type=int, metavar="쪽",
                    help="이 쪽의 낱말마다 유채색 비율 (강조 임계값 정할 때)")
    pr.add_argument("--image", metavar="PNG",
                    help="--color 와 함께: 판정 결과를 쪽 그림에 네모로 그려 저장")
    pr.add_argument("--sample", type=int, default=40, help="훑을 쪽 수 (기본 40)")
    pr.add_argument("--pages", help="훑을 쪽을 직접 지정. 예: 120-160")
    pr.add_argument("--lines", action="store_true",
                    help="줄마다 무엇으로 읽혔는지 (헤딩이 안 잡힐 때)")
    pr.add_argument("--profile", default="textbook", help="--lines 에 쓸 프로파일")
    pr.add_argument("--out", help="결과를 이 파일로 저장 (기본: 화면)")

    mp = sub.add_parser("mapping", help="기본서 ↔ 사례집 매핑 (mapping_생성지침.md)")
    msub = mp.add_subparsers(dest="sub", required=True)
    mb = msub.add_parser("build", help="근거를 세어 mapping.yaml 을 만든다")
    mb.add_argument("dirs", nargs="+",
                    help="변환 결과 폴더. 출력 루트 하나만 줘도 된다 — "
                         "기본서·사례집은 프론트매터 source: 로 가른다")
    mb.add_argument("-o", "--out", default="mapping.yaml")
    mr = msub.add_parser("review", help="승인 대기 목록")
    mr.add_argument("path", nargs="?", default="mapping.yaml")
    mr.add_argument("--out", help="파일로 저장 (기본: 화면)")
    mc = msub.add_parser("confirm", help="사람이 검토한 매핑에 confirmed: true 를 찍는다")
    mc.add_argument("path", nargs="?", default="mapping.yaml")
    mc.add_argument("--all", dest="all_", action="store_true", help="전부 승인")
    mc.add_argument("--section", help="이 절만 승인. 예: \"IV. 시효중단\"")
    mv = msub.add_parser("validate", help="M1~M4 검증")
    mv.add_argument("path", nargs="?", default="mapping.yaml")

    sub.add_parser("parsers", help="쓸 수 있는 파서 보기")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    return globals()[f"_cmd_{args.cmd.replace('-', '_')}"](args, cfg)


# ── mapping (mapping_생성지침.md) ────────────────────────────────
def _cmd_mapping(args, cfg) -> int:
    return globals()[f"_map_{args.sub}"](args, cfg)


def _map_build(args, cfg) -> int:
    dirs = [Path(d) for d in args.dirs]
    for d in dirs:
        if not d.is_dir():
            print(f"폴더가 없다: {d}", file=sys.stderr)
            here = d.parent if d.parent.is_dir() else Path(".")
            subs = [p.name for p in sorted(here.iterdir()) if p.is_dir()]
            if subs:
                print(f"`{here}` 안에 있는 폴더: " +
                      ", ".join(f'"{x}"' for x in subs), file=sys.stderr)
            return 2
    data = map_mod.build(dirs, cfg)
    files = data["files"]
    if not files["textbook"] or not files["casebook"]:
        print("기본서 {}개 · 사례집 {}개 — 한쪽이 비었다.".format(
            len(files["textbook"]), len(files["casebook"])), file=sys.stderr)
        print("변환 결과의 프론트매터 `source:` 로 가른다. 두 책을 다 담은 "
              "출력 루트를 주었는지 확인할 것.", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.parent != Path(""):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(map_mod.to_yaml(data), encoding="utf-8")
    strong = sum(1 for ms in data["matches"].values()
                 if max(m.score for m in ms) >= 2)
    weak = len(data["matches"]) - strong
    print(f"기본서 md {len(files['textbook'])}개 → 절 {len(data['sections'])}개 · "
          f"사례집 md {len(files['casebook'])}개 → 문제 {len(data['problems'])}개")
    if files["other"]:
        print(f"※ source: 를 알아볼 수 없어 건너뛴 파일 {len(files['other'])}개")
    print(f"매핑 {strong}건 · 후보 {weak}건 → {out}")
    print("**아직 하나도 승인되지 않았다.** `mapping review` 로 보고 "
          "`mapping confirm` 으로 승인할 것.")
    return 0


def _map_review(args, cfg) -> int:
    doc = map_mod.load(args.path)
    text = map_mod.review(doc)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)
    return 0


def _map_confirm(args, cfg) -> int:
    if not args.all_ and not args.section:
        print("--all 이나 --section 중 하나가 있어야 한다.", file=sys.stderr)
        return 2
    n = map_mod.confirm(args.path, section=args.section, all_=args.all_)
    print(f"{n}건을 승인했다 → {args.path}")
    return 0


def _map_validate(args, cfg) -> int:
    fails, warns = map_mod.validate(map_mod.load(args.path))
    for f in fails:
        print(f"[FAIL] {f}")
    for w in warns:
        print(f"[WARN] {w}")
    print(f"\n판정: {'FAIL' if fails else ('WARN' if warns else 'PASS')}")
    return 1 if fails else 0


# ── diagnose ────────────────────────────────────────────────────
def _cmd_diagnose(args, cfg) -> int:
    target = Path(args.pdf)
    if not target.exists():
        print(f"경로가 없다: {target}", file=sys.stderr)
        return 2
    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    if not pdfs:
        print(f"폴더에 PDF 가 없다: {target}", file=sys.stderr)
        return 2

    reports = Path(args.out) / "_reports"
    index, rc = [], 0
    for pdf in pdfs:
        print(f"[진단] {pdf} …")
        try:
            d = diag_mod.run(str(pdf), cfg, sample=args.sample,
                             layout_pages=args.layout_pages,
                             layout_range=_page_range(getattr(args, "pages", None)))
        except Exception as exc:
            print(f"  ! 읽지 못했다: {exc}", file=sys.stderr)
            rc = 2
            continue
        d["profile_hint"] = _guess_profile(d, cfg)
        md, js = diag_mod.save(d, cfg, reports)
        if len(pdfs) == 1:
            print(diag_mod.report(d, cfg))
        else:
            print(f"  {d['pages']:,}쪽 · "
                  f"{'텍스트' if d['text_layer'] else '스캔'} · {d['columns']}단 · "
                  f"색 {d['color']['distinct_colors']}종 · "
                  f"옆번호 {d['sidenote']['found']}건 · "
                  f"권장 프로파일 {d['profile_hint']}")
        print(f"  → {md}")
        index.append(d)
        if not d["text_layer"]:
            print("  ※ 텍스트 레이어가 없다. OCR 파서로 가야 한다 (§3.2).")

    if len(index) > 1:
        path = reports / "diagnosis-index.md"
        path.write_text(_index_report(index), encoding="utf-8")
        print(f"\n요약 → {path}")
    return rc


def _index_report(items) -> str:
    """여러 PDF 를 한꺼번에 진단했을 때의 한눈 표."""
    L = ["# 진단 요약 (§3.1)", "",
         "| 파일 | 크기 | 쪽 | 레이어 | 단 | 색 | 옆번호 | 별표 | 두문자 | 권장 프로파일 |",
         "|---|---:|---:|---|---:|---:|---:|---:|---:|---|"]
    for d in items:
        import os
        L.append(
            f"| `{os.path.basename(d['file'])}` "
            f"| {d['size_bytes'] / 1024 / 1024:.0f} MB "
            f"| {d['pages']:,} "
            f"| {'텍스트' if d['text_layer'] else '**스캔**'} "
            f"| {d['columns']} "
            f"| {d['color']['distinct_colors']} "
            f"| {d['sidenote']['found']} "
            f"| {d['cases']['stars_in_sample']} "
            f"| {len(d['mnemonics'])} "
            f"| `{d['profile_hint']}` |")
    L += ["", "쪽수·별표·두문자는 **표본 기준**이다. 전수가 아니다.",
          "파일별 상세는 같은 폴더의 `diagnosis-<파일이름>.md` 를 볼 것."]
    return "\n".join(L) + "\n"


def _guess_profile(d: dict, cfg: dict) -> str:
    """어느 프로파일로 볼지 추정한다. 어디까지나 추정이라 리포트에만 쓴다.

    가장 확실한 단서는 문제 번호(`E-5.`)와 옆번호(`sE-8`)다. 둘 다 없으면
    파일 이름을 본다.
    """
    if len(d.get("problem_numbers") or []) >= 2:
        return "casebook"
    if d.get("sidenote", {}).get("found", 0):
        return "textbook"
    name = Path(d["file"]).name
    return "casebook" if ("사례" in name or "casebook" in name.lower()) else "textbook"


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
    root = Path(args.dir_a).parent
    reports = root / "_reports"
    reports.mkdir(parents=True, exist_ok=True)
    text, mismatches, decisions = crosscheck(args.dir_a, args.dir_b, cfg, la, lb,
                                             reports_dir=reports)
    (reports / "crosscheck.md").write_text(text, encoding="utf-8")
    (reports / "mnemonic_conflicts.md").write_text(decisions, encoding="utf-8")
    print(text)
    print(f"→ {reports / 'crosscheck.md'}")
    print(f"→ {reports / 'mnemonic_conflicts.md'} (네모에 표시한 뒤 "
          f"convert apply-decisions)")
    if mismatches:
        print(f"\n두문자 불일치 의심 {mismatches}건. 사람이 판단할 것 (§2.2). "
              f"자동 교정하지 않았다.", file=sys.stderr)
        return 1
    return 0


# ── apply-decisions (§P1-3) ─────────────────────────────────────
def _cmd_apply_decisions(args, cfg) -> int:
    """결정표의 네모를 config.yaml 의 corrections 로 옮긴다.

    사람이 손으로 옮겨 적는 동안 한 글자가 틀어지는 것이 이 문서에서 가장
    무서운 사고다. 그래서 옮겨 적기만 기계가 한다 — 판단은 사람이 한 그대로다.
    """
    src = Path(args.decisions)
    if not src.exists():
        print(f"파일이 없다: {src}", file=sys.stderr)
        return 2
    decisions = read_decisions(src)
    if not decisions:
        print("표시된 결정이 없다. 네모에 `x` 를 넣고 저장한 뒤 다시 부를 것.")
        return 0
    for d in decisions:
        print(f"  {d['id']}  [{d['find']}] → [{d['to']}]")
    if args.dry_run:
        print(f"\n--dry-run 이라 아무것도 쓰지 않았다. {len(decisions)}건.")
        return 0
    target = Path(args.config) if args.config else \
        Path(__file__).resolve().parent.parent / "config.yaml"
    added, dupes = merge_corrections(target, decisions)
    print(f"\n{target} 에 {added}건 추가 (이미 있던 것 {dupes}건).")
    if added:
        print("이제 변환을 다시 돌릴 것: convert run … --from normalize")
    return 0


# ── all ─────────────────────────────────────────────────────────
def _cmd_all(args, cfg) -> int:
    """§8 의 순서를 한 번에 돌린다. 판정은 파일마다 따로 낸다.

    FAIL 이 나도 나머지 파일을 계속 돌린다. 리포트를 다 모아 놓아야 어디가
    어긋났는지 한눈에 견줄 수 있기 때문이다. 대신 마지막 요약에서 FAIL 을
    분명히 세우고, 하나라도 있으면 종료 코드 1 을 낸다 (§5.8).
    """
    target = Path(args.pdf_dir)
    if not target.exists():
        print(f"경로가 없다: {target}", file=sys.stderr)
        return 2
    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]
    if not pdfs:
        print(f"폴더에 PDF 가 없다: {target}", file=sys.stderr)
        return 2

    root = Path(args.out)
    reports = root / "_reports"
    pages = _page_range(args.pages)
    results, dirs = [], {}

    for k, pdf in enumerate(pdfs, 1):
        print(f"\n=== [{k}/{len(pdfs)}] {pdf.name} " + "=" * 20)
        try:
            d = diag_mod.run(str(pdf), cfg)
        except Exception as exc:
            print(f"  ! 진단 실패: {exc}", file=sys.stderr)
            results.append((pdf.name, "-", "진단실패"))
            continue
        d["profile_hint"] = _guess_profile(d, cfg)
        diag_mod.save(d, cfg, reports)
        name = args.profile or d["profile_hint"]
        print(f"[진단] {d['pages']:,}쪽 · "
              f"{'텍스트' if d['text_layer'] else '스캔'} · {d['columns']}단 · "
              f"색 {'그림' if d['color'].get('source') == 'image' else '글자'} · "
              f"프로파일 {name}")

        prof = get_profile(cfg, name)
        parser_name = args.parser or pick_parser(cfg, d).name
        out = root / pdf.stem
        pipe = Pipeline(pdf, cfg, prof, out, reports, root / "_work" / pdf.stem,
                        parser_name, pages)
        try:
            verdict = pipe.run("extract")
        except Exception as exc:
            print(f"  ! 변환 실패: {exc}", file=sys.stderr)
            results.append((pdf.name, name, "변환실패"))
            continue
        results.append((pdf.name, name, verdict))
        dirs.setdefault(name, []).append(out)
        # 리포트가 파일마다 덮이지 않게 이름을 붙여 사본을 남긴다
        for fname in ("validation.md", "warnings.md", "caselist.txt",
                      "mnemonics.txt", "palette.md"):
            src = reports / fname
            if src.exists():
                stem, ext = fname.rsplit(".", 1)
                (reports / f"{stem}-{pdf.stem}.{ext}").write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8")

    # §5.3 교차 검증: 기본서 ↔ 사례집
    books = dirs.get("textbook", [])
    cases = dirs.get("casebook", [])
    for a in books:
        for b in cases:
            text, mismatch, decisions = crosscheck(a, b, cfg, a.name, b.name,
                                                   reports_dir=reports)
            path = reports / f"crosscheck-{a.name}-{b.name}.md"
            path.write_text(text, encoding="utf-8")
            dpath = reports / f"mnemonic_conflicts-{a.name}-{b.name}.md"
            dpath.write_text(decisions, encoding="utf-8")
            print(f"\n[교차검증] {a.name} ↔ {b.name}: 두문자 불일치 의심 "
                  f"{mismatch}건 → {path.name}")
            print(f"           결정표 → {dpath.name} "
                  f"(네모 표시 후 convert apply-decisions)")

    print("\n" + "=" * 52)
    print(f"{'파일':<34}{'프로파일':<12}판정")
    for name, prof_name, verdict in results:
        print(f"{name[:32]:<34}{prof_name:<12}{verdict}")
    print(f"\n리포트: {reports}")
    failed = [r for r in results if r[2] not in ("PASS", "WARN")]
    if failed:
        print(f"\nFAIL 이 {len(failed)}건 있다. warnings-<파일>.md 를 보고 "
              f"config.yaml 을 고친 뒤 다시 돌릴 것 (§5.8).", file=sys.stderr)
        return 1
    print("\n사람이 눈으로 확인할 것: caselist-*.txt, mnemonics-*.txt, "
          "crosscheck-*.md (§5.1, §5.3)")
    return 0


# ── probe ───────────────────────────────────────────────────────
def _cmd_probe(args, cfg) -> int:
    from . import probe as probe_mod
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"파일이 없다: {pdf}", file=sys.stderr)
        return 2
    if args.color:
        text = probe_mod.color(str(pdf), cfg, args.color, args.image)
    elif args.lines:
        rng = _page_range(args.pages)
        text = probe_mod.lines(str(pdf), cfg, get_profile(cfg, args.profile),
                               list(rng) if rng else None)
    elif args.find:
        text = probe_mod.find(str(pdf), args.find)
    elif args.page:
        text = probe_mod.page(str(pdf), args.page)
    else:
        rng = _page_range(args.pages)
        text = probe_mod.scan(str(pdf), cfg, args.sample, list(rng) if rng else None)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)
    return 0


# ── parsers ─────────────────────────────────────────────────────
def _cmd_parsers(args, cfg) -> int:
    print(f"{'파서':<14}{'가능':<6}{'좌표/색':<8}사유")
    for name, ok, why, layout in availability():
        print(f"{name:<14}{'○' if ok else '×':<6}{'○' if layout else '-':<8}{why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
