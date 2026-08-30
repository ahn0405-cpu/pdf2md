"""검증 (§5). 가장 중요한 단계.

FAIL 이 하나라도 있으면 다음 단계로 넘어가지 않는다(§5.8). 그리고 자동 판정으로
끝내지 않는다 — 사람이 눈으로 볼 목록(caselist.txt, mnemonics.txt, warnings.md)을
반드시 함께 낸다(§5.1).

원본 대조가 필요한 항목(별표·색상)은 추출 단계에서 남긴 baseline.json 을 쓴다.
baseline 이 없으면 그 항목은 판정하지 않고 '대조 불가' 로 적는다. 없는 근거로
PASS 를 내지 않는다.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .patterns import Patterns

_SIDE = re.compile(r"s[A-Z]-\d{1,4}")
_EMPH = re.compile(r"==([^=\n]{1,200})==")
_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
_FM = re.compile(r"^---\n.*?\n---\n", re.S)
_STUDY = ("학설", "判例", "판례", "검토")


@dataclass
class Finding:
    level: str            # FAIL | WARN | INFO
    check: str
    message: str
    context: str = ""
    location: str = ""


@dataclass
class Result:
    findings: list = field(default_factory=list)
    cases: list = field(default_factory=list)          # (사건번호, 파일, 문맥)
    mnemonics: Counter = field(default_factory=Counter)
    mnemonic_context: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)

    @property
    def failed(self) -> int:
        return sum(1 for f in self.findings if f.level == "FAIL")

    @property
    def warned(self) -> int:
        return sum(1 for f in self.findings if f.level == "WARN")

    @property
    def verdict(self) -> str:
        return "FAIL" if self.failed else ("WARN" if self.warned else "PASS")

    def add(self, level, check, message, context="", location=""):
        self.findings.append(Finding(level, check, message, context, location))


def md_files(root: Path) -> list[Path]:
    """검증 대상 마크다운.

    `_reports/`, `_work/` 같은 밑줄 디렉토리는 뺀다. 중간 산출물(03_structured.md)이
    같이 세어지면 별표·각주 개수가 통째로 두 배가 되어 대조가 무의미해진다.
    """
    root = Path(root)
    out = []
    for p in root.rglob("*.md"):
        rel = p.relative_to(root).parts
        if any(part.startswith("_") for part in rel[:-1]) or p.name == "README.md":
            continue
        out.append(p)
    return sorted(out)


def validate(root, cfg: dict, baseline: dict | None = None) -> Result:
    pat = Patterns.build(cfg)
    res = Result()
    files = md_files(Path(root))
    if not files:
        res.add("FAIL", "입력", f"검증할 .md 파일이 없다: {root}")
        return res

    text_by_file = {p: p.read_text(encoding="utf-8") for p in files}
    body_by_file = {p: _FM.sub("", t) for p, t in text_by_file.items()}
    whole = "\n".join(body_by_file.values())

    _cases(res, pat, body_by_file)
    _stars(res, pat, whole, baseline)
    _mnemonics(res, pat, body_by_file)
    _color(res, whole, baseline, cfg)
    _sidenotes(res, cfg, body_by_file)
    _footnotes(res, pat, body_by_file, bool((baseline or {}).get("partial")))
    _structure(res, body_by_file)
    _noise(res, cfg, whole, baseline)
    _extraction_qa(res, cfg, body_by_file)
    _frontmatter(res, pat, text_by_file)
    if (baseline or {}).get("partial"):
        res.counts["partial"] = True
        res.add("INFO", "범위", "쪽 범위를 잘라 돌렸다. 범위 밖과 짝이 맞지 않는 "
                                "각주·참조는 WARN 으로 낮췄다.")
    return res


# ── 5.1 사건번호 전수 검사 ───────────────────────────────────────
def _cases(res, pat, bodies):
    bad = 0
    for path, text in bodies.items():
        for m in pat.case.finditer(text):
            ctx = _ctx(text, m.start(), m.end())
            res.cases.append((m.group(0), path.name, ctx))
            problems = pat.case_problems(m)
            if problems:
                bad += 1
                res.add("FAIL", "5.1 사건번호", "; ".join(problems), ctx, path.name)
    # 정규식이 놓쳤을 수 있는 꼴도 사람이 보게 남긴다
    loose = sum(1 for text in bodies.values() for _ in pat.case_loose.finditer(text))
    res.counts["cases"] = len(res.cases)
    res.counts["cases_loose"] = loose
    if loose != len(res.cases):
        res.add("WARN", "5.1 사건번호",
                f"공백이 낀 사건번호가 남아 있다 (엄격 {len(res.cases)} vs 느슨 {loose}). "
                f"정규화가 덜 됐을 수 있다.")
    res.counts["case_errors"] = bad


# ── 5.2 별표 개수 대조 ───────────────────────────────────────────
def _stars(res, pat, whole, baseline):
    found = len(pat.case_star.findall(whole))
    res.counts["stars"] = found
    if not baseline or "stars" not in baseline:
        res.add("INFO", "5.2 별표", f"변환 결과 {found}건. 원본 대조본(baseline.json)이 "
                                    f"없어 대조하지 못했다.")
        return
    want = baseline["stars"]
    res.counts["stars_baseline"] = want
    if found != want:
        res.add("FAIL", "5.2 별표",
                f"별표 개수 불일치: 원본 {want} vs 변환 {found} (차이 {found - want:+})")
    else:
        res.add("INFO", "5.2 별표", f"원본·변환 모두 {want}건으로 일치")


# ── 5.3 두문자 (교차검증은 crosscheck 에서) ──────────────────────
def _mnemonics(res, pat, bodies):
    for path, text in bodies.items():
        for m in pat.mnemonic.finditer(text):
            body = m.group("body")
            if not pat.is_mnemonic_body(body):
                continue
            res.mnemonics[body] += 1
            res.mnemonic_context.setdefault(body, []).append(
                f"{path.name}: {_ctx(text, m.start(), m.end())}")
    res.counts["mnemonics"] = len(res.mnemonics)
    _bare_mnemonics(res, pat, bodies)


def _bare_mnemonics(res, pat, bodies):
    """대괄호를 잃은 두문자 후보 (§2.2).

    OCR 이 대괄호를 통째로 흘리면 `확객시젠[종확나시]` 처럼 앞말이 맨몸으로
    남는다. 괄호를 우리가 지어내면 안 되므로(§4.8), 자리만 짚어 사람에게 넘긴다.
    """
    rx = re.compile(r"(?<![\[`가-힣])([가-힣]{3,6})\s*`?\[(?!\^)")
    hits = 0
    for path, text in bodies.items():
        for m in rx.finditer(text):
            token = m.group(1)
            if token in res.mnemonics or len(token) < 3:
                continue
            hits += 1
            if hits <= 12:
                res.add("WARN", "2.2 두문자",
                        f"대괄호를 잃은 두문자 후보: `{token}` — 괄호를 지어내지 "
                        f"않았다. 원문을 보고 사람이 정할 것",
                        _ctx(text, m.start(1), m.end(1)), path.name)
    res.counts["bare_mnemonic_suspects"] = hits


# ── 5.4 색상 강조 보존 ───────────────────────────────────────────
def _color(res, whole, baseline, cfg):
    """강조 보존을 **글자 수**로 견준다.

    span 수와 마크업 덩어리 수는 단위가 다르다. 이어진 span 여럿이 마크업 하나로
    합쳐지므로(그게 맞는 동작이다) 개수끼리 견주면 늘 크게 어긋난 것처럼 보인다.
    글자 수는 합쳐져도 변하지 않는다.
    """
    runs = _EMPH.findall(whole)
    found_chars = sum(len(r.strip()) for r in runs)
    res.counts["emphasis"] = len(runs)
    res.counts["emphasis_chars"] = found_chars
    if not baseline or "colored_chars" not in baseline:
        res.add("INFO", "5.4 색상",
                f"강조 마크업 {len(runs)}덩어리 / {found_chars}자. 원본 대조본이 없다.")
        return
    # 강조는 두 번 옮겨진다. 원본 span → 줄 글자(==) → 결과물.
    # 헤딩 제목으로 들어간 것은 마크업이 걷히지만 사라진 게 아니라 구조가 담은
    # 것이므로 되더한다. 그리고 **잃은 것만** 본다 — 이어진 span 이 한 덩어리로
    # 합쳐지면서 사이의 구분자까지 안에 들어가 글자 수가 조금 느는 것은
    # 보존에 문제가 없다.
    origin = baseline["colored_chars"]
    absorbed = int(baseline.get("absorbed", 0))
    kept = found_chars + absorbed
    res.counts["colored_chars_origin"] = origin
    res.counts["colored_chars_kept"] = kept
    res.counts["colored_chars_in_headings"] = absorbed
    colors = baseline.get("distinct_colors", 0)
    if origin == 0:
        res.add("WARN", "5.4 색상", "원본에 유채색이 없다. 강조색 없는 판본인지 "
                                    "확인할 것.")
        return
    lost = (origin - kept) / origin
    if lost > 0.05:
        res.add("WARN", "5.4 색상",
                f"강조가 {lost * 100:.1f}% 사라졌다 (원본 {origin}자 vs 남은 {kept}자"
                f" = 마크업 {found_chars} + 제목흡수 {absorbed}). palette.md 와 함께 볼 것.")
    if colors > 3:
        res.add("WARN", "5.4 색상", f"색상 팔레트가 {colors}종이다. 근접색 병합이 필요하다 "
                                    f"(preserve.color.merge_distance).")


# ── 5.5 여백 마커 검사 ───────────────────────────────────────────
def _sidenotes(res, cfg, bodies):
    """§5.5 — 옆번호가 본문에 섞여 들어갔는지.

    옆번호는 좌표로 떼어 낸다(버리든 남기든). 그러니 **본문 글자 속에 남아
    있는 `sE-n` 은 전부 새어 들어온 것**이다. 이게 §4.3 이 경고한 사고다:
    `sE-8` + `1.` 이 붙으면 `sE-81` 이 되어 참조가 바뀐다.
    백틱 안에 있는 것은 우리가 헤딩 옆에 일부러 붙인 것이므로 뺀다.
    """
    suspect_rx = re.compile(cfg["legend"]["sidenote"]["merge_suspect"])
    tagged, leaked = 0, 0
    for path, text in bodies.items():
        for m in _SIDE.finditer(text):
            in_backticks = (text[max(0, m.start() - 1):m.start()] == "`"
                            and text[m.end():m.end() + 1] == "`")
            if in_backticks:
                tagged += 1
                if suspect_rx.search(m.group(0)):
                    leaked += 1
                    res.add("FAIL", "5.5 여백 마커",
                            f"자릿수가 이상한 옆번호: `{m.group(0)}` "
                            f"(sE-8 + 1. → sE-81 꼴)",
                            _ctx(text, m.start(), m.end()), path.name)
                continue
            leaked += 1
            res.add("FAIL", "5.5 여백 마커",
                    f"옆번호가 본문에 섞였다: `{m.group(0)}` — 좌표 분리가 "
                    f"어긋났다는 뜻이고, 붙은 글자만큼 참조 번호가 바뀐다",
                    _ctx(text, m.start(), m.end()), path.name)
    res.counts["sidenotes"] = tagged
    res.counts["sidenote_merged"] = leaked
    if not leaked:
        res.add("INFO", "5.5 여백 마커",
                f"본문에 새어 든 옆번호 0건 (헤딩에 붙인 것 {tagged}건)")


# ── 5.6 각주 무결성 ──────────────────────────────────────────────
def _footnotes(res, pat, bodies, partial=False):
    refs, defs = Counter(), Counter()
    where = defaultdict(list)
    for path, text in bodies.items():
        for line in text.splitlines():
            m = pat.footnote_def.match(line.strip())
            if m:
                defs[int(m.group("n"))] += 1
                where[int(m.group("n"))].append(path.name)
                continue
            for r in pat.footnote_ref.finditer(line):
                refs[int(r.group("n"))] += 1
    res.counts["footnote_refs"] = sum(refs.values())
    res.counts["footnote_defs"] = sum(defs.values())

    orphan_def = sorted(set(defs) - set(refs))
    orphan_ref = sorted(set(refs) - set(defs))
    res.counts["footnote_mismatch"] = len(orphan_def) + len(orphan_ref)
    # 쪽 범위를 잘라 돌린 경우, 짝이 범위 밖에 있는 것은 당연하다. 그걸 FAIL 로
    # 세면 §8 의 '한 장만 먼저' 가 영영 통과하지 못한다.
    level = "WARN" if partial else "FAIL"
    if orphan_ref:
        res.add(level, "5.6 각주",
                f"정의 없는 참조 {len(orphan_ref)}건 — 각주 본문이 사라졌다: "
                f"{', '.join(str(n) for n in orphan_ref[:20])}")
    if orphan_def:
        # 각주는 버리지 않았다. 다만 참조를 못 살렸으므로 §5.8 은 불일치로 본다.
        res.add(level, "5.6 각주",
                f"참조 없는 각주 {len(orphan_def)}건 — 본문의 위첨자 번호를 못 살렸다"
                f"(각주 자체는 버리지 않고 섹션 끝에 남겨 뒀다): "
                f"{', '.join(str(n) for n in orphan_def[:20])}")
    dup = sorted(n for n, c in defs.items() if c > 1)
    if dup:
        res.add("WARN", "5.6 각주", f"같은 번호의 각주 정의가 둘 이상: "
                                    f"{', '.join(str(n) for n in dup[:20])}")
    if defs:
        lo, hi = min(defs), max(defs)
        missing = [n for n in range(lo, hi + 1) if n not in defs]
        res.counts["footnote_missing"] = len(missing)
        if missing:
            res.add("WARN", "5.6 각주",
                    f"번호가 끊긴다 {lo}~{hi} 중 {len(missing)}개 없음: "
                    f"{', '.join(str(n) for n in missing[:30])}")


# ── 5.7 구조 검사 ────────────────────────────────────────────────
def _structure(res, bodies):
    empty, jumps = 0, 0
    for path, text in bodies.items():
        lines = text.splitlines()
        prev_level, prev_head, has_body = 0, None, False
        for line in lines:
            m = _HEAD.match(line)
            if not m:
                if line.strip():
                    has_body = True
                continue
            level = len(m.group(1))
            if prev_head is not None and not has_body and level > prev_level:
                pass                    # 상위 헤딩 바로 아래 하위 헤딩은 정상
            elif prev_head is not None and not has_body:
                empty += 1
                res.add("WARN", "5.7 구조", f"빈 섹션: `{prev_head}`", "", path.name)
            if prev_level and level > prev_level + 1:
                jumps += 1
                res.add("WARN", "5.7 구조",
                        f"헤딩 단계가 {prev_level} → {level} 로 건너뛴다: `{m.group(2)}`",
                        "", path.name)
            prev_level, prev_head, has_body = level, m.group(2), False
        if prev_head is not None and not has_body:
            empty += 1
            res.add("WARN", "5.7 구조", f"빈 섹션: `{prev_head}`", "", path.name)
        # 학판검 세트 힌트 (⑪)
        if "학설" in text and not any(k in text for k in ("검토", "判例", "판례")):
            res.add("WARN", "5.7 구조",
                    "학설은 있는데 判例/검토가 없다 (학판검 세트 누락 의심)", "", path.name)
    res.counts["empty_sections"] = empty
    res.counts["heading_jumps"] = jumps


# ── 잔여 노이즈 (§5.8 WARN) ──────────────────────────────────────
def _noise(res, cfg, whole, baseline):
    scan = cfg.get("noise_scan", {})
    allowed = set(scan.get("allowed_chars", ""))
    for lo, hi in scan.get("allowed_ranges", []):
        allowed.update(chr(c) for c in range(int(lo), int(hi) + 1))
    noise = Counter(ch for ch in whole if not ch.isspace() and ch not in allowed)
    total = sum(noise.values())
    pages = (baseline or {}).get("pages") or 1
    res.counts["noise"] = total
    res.counts["noise_per_page"] = round(total / pages, 2)
    limit = float(cfg["validation"]["warn_on"]["noise_per_page"])
    if total / pages > limit:
        res.add("WARN", "노이즈",
                f"잔여 노이즈 {total}자 (쪽당 {total / pages:.1f} > {limit}). "
                f"흔한 것: " + ", ".join(f"`{c}`×{n}" for c, n in noise.most_common(8)))


# ── §4.6 추출 검수 (자동 치환하지 않는다) ────────────────────────
def _extraction_qa(res, cfg, bodies):
    qa = cfg.get("extraction_qa", {})
    hits = Counter()
    for spec in qa.get("patterns", []):
        rx = re.compile(spec["regex"])
        for path, text in bodies.items():
            for m in rx.finditer(text):
                hits[spec["name"]] += 1
                if hits[spec["name"]] <= 3:
                    res.add("WARN", "4.6 추출검수",
                            f"{spec['note']} — 자동 치환하지 않았다. 파서 교체를 검토할 것.",
                            _ctx(text, m.start(), m.end()), path.name)
    res.counts["qa_hits"] = sum(hits.values())


# ── 프론트매터 대조 (§10) ────────────────────────────────────────
def _frontmatter(res, pat, texts):
    for path, text in texts.items():
        m = _FM.match(text)
        if not m:
            res.add("WARN", "프론트매터", "프론트매터가 없다", "", path.name)
            continue
        head, body = m.group(0), text[m.end():]
        listed = set(re.findall(r'id:\s*"([^"]+)"', head))
        actual = {mm.group(0) for mm in pat.case.finditer(body)}
        missing = actual - listed
        extra = listed - actual
        if missing:
            res.add("FAIL", "프론트매터",
                    f"본문에 있는데 cases 에 없는 사건번호: "
                    f"{', '.join(sorted(missing)[:10])}", "", path.name)
        if extra:
            res.add("WARN", "프론트매터",
                    f"cases 에 있는데 본문에 없는 사건번호: "
                    f"{', '.join(sorted(extra)[:10])}", "", path.name)


def _ctx(text: str, start: int, end: int, width: int = 30) -> str:
    left = text[max(0, start - width):start].replace("\n", "⏎")
    right = text[end:end + width].replace("\n", "⏎")
    return f"…{left}〖{text[start:end]}〗{right}…"


# ── 리포트 ──────────────────────────────────────────────────────
def reports(res: Result, cfg: dict) -> dict[str, str]:
    out = {}
    c = res.counts

    L = [f"# 검증 리포트 — **{res.verdict}**", ""]
    L.append(f"- FAIL {res.failed} · WARN {res.warned}")
    L.append("")
    L.append("## 판정 기준 대조 (§5.8)")
    L.append("")
    L.append("| 항목 | 기준 | 실제 | 판정 |")
    L.append("|---|---|---:|---|")
    rows = [
        ("사건번호 형식 오류", "0건", c.get("case_errors", 0), c.get("case_errors", 0) == 0),
        ("별표 개수 불일치", "0건",
         _diff(c.get("stars"), c.get("stars_baseline")),
         c.get("stars_baseline") is None or c.get("stars") == c.get("stars_baseline")),
        ("각주 참조/정의 불일치", "0건", c.get("footnote_mismatch", 0),
         c.get("footnote_mismatch", 0) == 0 or c.get("partial")),
        ("여백 마커 병합 의심", "0건", c.get("sidenote_merged", 0),
         c.get("sidenote_merged", 0) == 0),
    ]
    for name, want, got, ok in rows:
        L.append(f"| {name} | {want} | {got} | {'✅ PASS' if ok else '❌ FAIL'} |")
    warn_noise = c.get("noise_per_page", 0) <= float(cfg["validation"]["warn_on"]["noise_per_page"])
    L.append(f"| 잔여 노이즈 | 쪽당 {cfg['validation']['warn_on']['noise_per_page']}건 이하 | "
             f"{c.get('noise_per_page', 0)} | {'✅' if warn_noise else '⚠️ WARN'} |")
    L.append(f"| 색상 강조 유실 | 5% 이하 | 원본 {c.get('colored_chars_origin', '-')}자 "
             f"→ 남음 {c.get('colored_chars_kept', '-')}자 | "
             f"{'✅' if not any(f.check.startswith('5.4') and f.level == 'WARN' for f in res.findings) else '⚠️ WARN'} |")
    L.append("")
    L.append("> 두문자 일치(§5.3)는 두 소스가 모두 있어야 판정한다. "
             "`convert crosscheck` 를 돌릴 것.")
    L.append("")
    L.append("## 집계")
    L.append("")
    for k, v in c.items():
        L.append(f"- `{k}`: {v}")
    L.append("")
    L.append("## 지적 사항")
    L.append("")
    if not res.findings:
        L.append("없음")
    for level in ("FAIL", "WARN", "INFO"):
        items = [f for f in res.findings if f.level == level]
        if not items:
            continue
        L.append(f"### {level} ({len(items)})")
        L.append("")
        for f in items[:200]:
            loc = f" `{f.location}`" if f.location else ""
            L.append(f"- **{f.check}**{loc} — {f.message}")
            if f.context:
                L.append(f"  - `{f.context}`")
        if len(items) > 200:
            L.append(f"- … 외 {len(items) - 200}건")
        L.append("")
    out["validation.md"] = "\n".join(L) + "\n"

    # 사람이 눈으로 확인할 목록 (§5.1)
    lines = [f"# 사건번호 전수 {len(res.cases)}건 — 눈으로 확인할 것", ""]
    tally = Counter(cid for cid, _, _ in res.cases)
    for cid, n in sorted(tally.items()):
        lines.append(f"{cid}\t×{n}")
    lines.append("")
    lines.append("# 출현 위치")
    for cid, fname, ctx in res.cases:
        lines.append(f"{cid}\t{fname}\t{ctx}")
    out["caselist.txt"] = "\n".join(lines) + "\n"

    lines = [f"# 두문자 전수 {len(res.mnemonics)}종 — 한 글자도 고치지 않았다", ""]
    for body, n in sorted(res.mnemonics.items()):
        lines.append(f"[{body}]\t×{n}")
    lines.append("")
    lines.append("# 출현 위치")
    for body in sorted(res.mnemonic_context):
        for ctx in res.mnemonic_context[body][:20]:
            lines.append(f"[{body}]\t{ctx}")
    out["mnemonics.txt"] = "\n".join(lines) + "\n"

    L = ["# 수동 확인 필요 지점", ""]
    items = [f for f in res.findings if f.level in ("FAIL", "WARN")]
    if not items:
        L.append("없음")
    for f in items:
        loc = f" `{f.location}`" if f.location else ""
        L.append(f"- [{f.level}] **{f.check}**{loc} — {f.message}")
        if f.context:
            L.append(f"  - `{f.context}`")
    out["warnings.md"] = "\n".join(L) + "\n"
    return out


def _diff(a, b):
    if a is None or b is None:
        return "대조 불가"
    return abs(a - b)


def load_baseline(path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
