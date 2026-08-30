"""기본서 ↔ 사례집 매핑 (mapping_생성지침.md).

기본서와 사례집은 서로를 보완한다. 판례 **사실관계**는 사례집에만 있고,
목차·학설·판시 원문은 기본서에만 있다. 어느 절이 어느 문제로 나왔는지 이어
두지 않으면 뒤 단계가 사안을 지어내게 된다.

**이 모듈은 판정하지 않는다.** 근거를 세어 점수를 매기고 사람에게 넘긴다.
`confirmed: true` 가 아닌 매핑은 노트 생성에 쓰이지 않는다 — 잘못된 사안이
붙으면 노트 전체가 틀리기 때문이다.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from .crosscheck import _distance
from .model import is_generated
from .patterns import Patterns

_FM = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.S)
_HEAD = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.*)$")
#: 사례집 문제: '## E-5. [일부청구-시효중단] `10점`'
_PROBLEM = re.compile(r"^(?P<letter>[A-Z])\s*-\s*(?P<num>\d+)\s*\.\s*(?P<rest>.*)$")
#: 제목 뒤 백틱 표시 — 배점 `10점` `2.5`, 기출연도 `(11)`, 옆번호 `sE-8`
_TICKED = re.compile(r"`([^`]*)`")
_POINTS = re.compile(r"^\(?\s*(\d+(?:\.\d+)?)\s*\)?\s*점?$")
#: 대괄호 안 키워드. OCR 이 흘린 괄호도 받는다 (지침 §근거1)
_BRACKET = re.compile(r"[\[［｛{〔【「『」』｝】〕］\]]")
_ROMAN_LEAD = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[IVX]{1,5}|\d{1,3})\s*[.,·•‧∙・)]\s*")
_MARKUP = re.compile(r"(?:==|\*\*|`)")


def _plain(text: str) -> str:
    return _MARKUP.sub("", text or "").strip()


def _strip_ticked(title: str) -> tuple[str, list[str]]:
    """제목에서 백틱 표시를 떼어 (제목, 표시들) 로 나눈다.

    **백틱을 먼저 본다.** `_plain` 을 먼저 돌리면 백틱이 사라져 배점 `10점` 과
    기출연도 `(11)` 이 제목 안에 남는다. 그러면 'IV. 시효중단 (11)' 이 되어
    제목 키워드가 하나도 안 맞고 배점도 못 읽는다.
    """
    marks = _TICKED.findall(title)
    return _plain(_TICKED.sub("", title)), marks


def _points_of(marks) -> float | None:
    for m in marks:
        hit = _POINTS.match(m.strip())
        if hit:
            return float(hit.group(1))
    return None


@dataclass
class Section:
    """기본서의 절 하나."""
    chapter: str
    title: str                     # 'IV. 시효중단'
    file: str
    cases: set = field(default_factory=set)
    mnemonics: set = field(default_factory=set)

    @property
    def name(self) -> str:
        """번호를 뗀 알맹이. 'IV. 시효중단' → '시효중단'"""
        return _ROMAN_LEAD.sub("", self.title).strip()


@dataclass
class Answer:
    title: str
    points: float | None = None

    @property
    def name(self) -> str:
        return _ROMAN_LEAD.sub("", self.title).strip()


@dataclass
class Problem:
    """사례집의 문제 하나."""
    id: str                        # 'E-5'
    title: str                     # '일부청구-시효중단'
    file: str
    points: float | None = None
    answers: list = field(default_factory=list)
    cases: set = field(default_factory=set)
    mnemonics: set = field(default_factory=set)

    @property
    def points_sum(self) -> float | None:
        """답안 목차 배점의 합. 총점과 어긋나면 배점을 잘못 읽은 것이다 (§M4)."""
        known = [a.points for a in self.answers if a.points is not None]
        return round(sum(known), 2) if known else None

    @property
    def keywords(self) -> list[str]:
        """제목 대괄호 안을 '-' 와 ',' 로 나눈 것."""
        return [k.strip() for k in re.split(r"[-,·]", self.title) if k.strip()]


# ── 읽기 ────────────────────────────────────────────────────────
def _md_files(roots) -> list[Path]:
    """준 폴더들 아래의 우리 결과물 md. `_reports` `_work` 는 건너뛴다."""
    if isinstance(roots, (str, Path)):
        roots = [roots]
    out, seen = [], set()
    for root in roots:
        root = Path(root)
        for p in sorted(root.rglob("*.md")):
            rel = p.relative_to(root).parts
            if any(part.startswith("_") for part in rel[:-1]):
                continue
            if p.name == "README.md" or not is_generated(p):
                continue
            key = p.resolve()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out


def sort_by_source(roots, cfg: dict) -> tuple[list, list, list]:
    """어느 파일이 기본서고 어느 파일이 사례집인가.

    폴더 이름으로 가르지 않는다. 사장님이 어떤 이름으로 저장해 두었는지 우리는
    모르고, 이름을 잘못 짚으면 사례집을 기본서로 읽어 매핑이 통째로 헛돈다.
    프론트매터의 `source:` 는 우리가 프로파일 이름표를 직접 적어 넣은 것이라
    틀릴 수가 없다.
    """
    profs = cfg.get("profiles") or {}
    tb_label = (profs.get("textbook") or {}).get("label", "기본서")
    cb_label = (profs.get("casebook") or {}).get("label", "사례집")
    tb, cb, other = [], [], []
    for path in _md_files(roots):
        src = _front(path.read_text(encoding="utf-8")).get("source", "").strip('"')
        (tb if src == tb_label else cb if src == cb_label else other).append(path)
    return tb, cb, other


def _front(text: str) -> dict:
    m = _FM.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group("body").splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def read_textbook(files, pat: Patterns) -> list[Section]:
    """기본서에서 절을 뽑는다. 절마다 그 안의 사건번호·두문자를 모은다.

    프론트매터의 cases 는 **파일 전체** 것이라 절 단위 대조에 못 쓴다.
    헤딩 사이 본문을 갈라 절마다 따로 센다.
    """
    out: list[Section] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        chapter = _front(text).get("chapter", "").strip('"')
        body = _FM.sub("", text)
        cur: Section | None = None
        buf: list[str] = []

        def close():
            if cur is not None:
                blob = "\n".join(buf)
                cur.cases = {m.group(0) for m in pat.case.finditer(blob)}
                cur.mnemonics = set(pat.find_mnemonics(blob))
                out.append(cur)

        for line in body.splitlines():
            h = _HEAD.match(line)
            if h and len(h.group("level")) <= 4:
                close()
                buf = []
                cur = None
                if len(h.group("level")) == 4:
                    title, _ = _strip_ticked(h.group("title"))
                    cur = Section(chapter=chapter, title=title, file=str(path))
                continue
            if cur is not None:
                buf.append(line)
        close()
    return out


def read_casebook(files, pat: Patterns) -> list[Problem]:
    """사례집에서 문제를 뽑는다. 답안 목차와 배점도 함께."""
    out: list[Problem] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        body = _FM.sub("", text)
        cur: Problem | None = None
        buf: list[str] = []

        def close():
            if cur is not None:
                blob = "\n".join(buf)
                cur.cases = {m.group(0) for m in pat.case.finditer(blob)}
                cur.mnemonics = set(pat.find_mnemonics(blob))
                out.append(cur)

        for line in body.splitlines():
            h = _HEAD.match(line)
            if not h:
                if cur is not None:
                    buf.append(line)
                continue
            level = len(h.group("level"))
            title, marks = _strip_ticked(h.group("title"))
            hit = _PROBLEM.match(title)
            if hit and level <= 3:
                close()
                buf = []
                inner = _BRACKET.sub("", hit.group("rest")).strip()
                cur = Problem(id=f"{hit.group('letter')}-{hit.group('num')}",
                              title=inner, file=str(path), points=_points_of(marks))
                continue
            if cur is not None:
                if level == 3:
                    cur.answers.append(Answer(title=title, points=_points_of(marks)))
                buf.append(line)
        close()
    return out


# ── 근거 ────────────────────────────────────────────────────────
def _kw_hit(section: Section, prob: Problem) -> list[str]:
    """제목 키워드가 겹치는가. 부분 일치도 인정한다 (지침 §근거1)."""
    name = re.sub(r"\s+", "", section.name)
    if len(name) < 2:
        return []
    hits = []
    for kw in prob.keywords:
        flat = re.sub(r"\s+", "", kw)
        if len(flat) >= 2 and (name in flat or flat in name):
            hits.append(kw)
    return hits


def _mn_hit(section: Section, prob: Problem) -> tuple[list[str], list[str]]:
    """두문자 교집합. 한 글자 차이는 같은 것으로 보고 따로 적는다."""
    same, near = [], []
    for a in sorted(section.mnemonics):
        for b in sorted(prob.mnemonics):
            if a == b:
                same.append(a)
            elif abs(len(a) - len(b)) <= 1 and _distance(a, b) == 1:
                near.append(f"{a} ↔ {b}")
    return same, near


def _role(section: Section, prob: Problem) -> tuple[str, float | None]:
    """답안 목차의 배점으로 역할을 가른다 (지침 §role).

    배점을 못 찾으면 composite 으로 둔다. 어림짐작으로 primary 를 주면
    사람이 그냥 넘길 위험이 있는데, 이 판단은 사람이 해야 한다.
    """
    name = re.sub(r"\s+", "", section.name)
    best: Answer | None = None
    for a in prob.answers:
        flat = re.sub(r"\s+", "", a.name)
        if len(name) >= 2 and (name in flat or flat in name):
            if best is None or (a.points or 0) > (best.points or 0):
                best = a
    if best is None or best.points is None:
        return "composite", None
    known = [a.points for a in prob.answers if a.points is not None]
    if known and best.points >= max(known):
        return "primary", best.points
    total = prob.points or (sum(known) if known else 0)
    if total and best.points >= total * 0.25:
        return "composite", best.points
    return "incidental", best.points


@dataclass
class Match:
    section: Section
    prob: Problem
    keywords: list
    cases: list
    mnemonics: list
    near: list
    role: str
    points: float | None

    @property
    def score(self) -> int:
        return sum(bool(x) for x in
                   (self.keywords, self.cases, self.mnemonics or self.near))


def build(roots, cfg: dict) -> dict:
    """폴더(들)을 통째로 받아 기본서·사례집을 갈라 읽고 매핑한다."""
    if isinstance(roots, (str, Path)):
        roots = [roots]
    pat = Patterns.build(cfg)
    tb_files, cb_files, other = sort_by_source(roots, cfg)
    sections = read_textbook(tb_files, pat)
    problems = read_casebook(cb_files, pat)

    by_section: dict[int, list[Match]] = {}
    used: set = set()
    for i, sec in enumerate(sections):
        for prob in problems:
            kw = _kw_hit(sec, prob)
            cs = sorted(sec.cases & prob.cases)
            mn, near = _mn_hit(sec, prob)
            if not (kw or cs or mn or near):
                continue
            role, pts = _role(sec, prob)
            m = Match(sec, prob, kw, cs, mn, near, role, pts)
            if m.score >= 1:
                by_section.setdefault(i, []).append(m)
                if m.score >= 2:
                    used.add(prob.id)
    return {"sections": sections, "problems": problems,
            "matches": by_section, "used": used,
            "files": {"textbook": tb_files, "casebook": cb_files, "other": other}}


# ── YAML ────────────────────────────────────────────────────────
def _q(s) -> str:
    return '"' + str(s).replace('"', '\\"') + '"'


def to_yaml(data: dict) -> str:
    sections, problems = data["sections"], data["problems"]
    matches, used = data["matches"], data["used"]

    L = ["# mapping.yaml — 기본서 ↔ 사례집",
         "#",
         "# **confirmed: true 인 것만 노트 생성에 쓴다.** score 3 이어도 자동 승인하지",
         "# 않는다 — 잘못된 사안이 붙으면 노트 전체가 틀리기 때문이다.",
         "#   convert mapping review mapping.yaml     승인 대기 목록",
         "#   convert mapping confirm mapping.yaml --all",
         "version: 1",
         f"generated: {_dt.date.today().isoformat()}",
         "",
         "mappings:"]
    strong, weak = [], []
    for i, sec in enumerate(sections):
        ms = matches.get(i, [])
        if not ms:
            continue
        (strong if max(m.score for m in ms) >= 2 else weak).append((sec, ms))

    def emit(items, indent="  "):
        for sec, ms in items:
            ms = sorted(ms, key=lambda m: (-m.score, m.prob.id))
            L.append(f"{indent}- textbook:")
            L.append(f"{indent}    chapter: {_q(sec.chapter)}")
            L.append(f"{indent}    section: {_q(sec.title)}")
            L.append(f"{indent}    file: {_q(sec.file)}")
            L.append(f"{indent}  casebook:")
            for m in ms:
                L.append(f"{indent}    - id: {_q(m.prob.id)}")
                L.append(f"{indent}      title: {_q(m.prob.title)}")
                L.append(f"{indent}      points: "
                         f"{m.prob.points if m.prob.points is not None else 'null'}")
                L.append(f"{indent}      section_points: "
                         f"{m.points if m.points is not None else 'null'}")
                L.append(f"{indent}      points_sum: "
                         f"{m.prob.points_sum if m.prob.points_sum is not None else 'null'}")
                L.append(f"{indent}      file: {_q(m.prob.file)}")
                L.append(f"{indent}      role: {m.role}")
            kws = sorted({k for m in ms for k in m.keywords})
            cs = sorted({c for m in ms for c in m.cases})
            mn = sorted({x for m in ms for x in m.mnemonics})
            nr = sorted({x for m in ms for x in m.near})
            L.append(f"{indent}  evidence:")
            L.append(f"{indent}    title_keyword: [" + ", ".join(_q(k) for k in kws) + "]")
            L.append(f"{indent}    shared_cases: [" + ", ".join(_q(c) for c in cs) + "]")
            L.append(f"{indent}    shared_mnemonics: [" + ", ".join(_q(x) for x in mn) + "]")
            if nr:
                L.append(f"{indent}    # 한 글자 차이 — 두문자 결정표에서 확정할 것")
                L.append(f"{indent}    near_mnemonics: [" + ", ".join(_q(x) for x in nr) + "]")
            top = max(m.score for m in ms)
            L.append(f"{indent}  score: {top}")
            if top == 2:
                L.append(f"{indent}  # ⚠️ 근거 부족 — 셋 중 둘만 맞았다")
            L.append(f"{indent}  confirmed: false")

    if strong:
        emit(strong)
    else:
        L.append("  []")
    L.append("")
    L.append("# 근거가 하나뿐 — 매핑으로 올리지 않는다. 사람이 보고 판단할 것.")
    L.append("candidates:")
    if weak:
        emit(weak)
    else:
        L.append("  []")
    L.append("")
    L.append("# 짝을 못 찾은 것들")
    L.append("unmapped:")
    lone = [s for i, s in enumerate(sections) if not matches.get(i)]
    L.append("  textbook_sections:")
    if lone:
        for s in lone:
            L.append(f"    - {_q(s.title)}    # {s.chapter}")
    else:
        L.append("    []")
    left = [p for p in problems if p.id not in used]
    L.append("  casebook_problems:")
    if left:
        for p in left:
            L.append(f"    - {_q(p.id)}    # {p.title}")
    else:
        L.append("    []")
    return "\n".join(L) + "\n"


# ── review / confirm / validate ─────────────────────────────────
def load(path) -> dict:
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def review(doc: dict) -> str:
    L = ["# 승인 대기 목록", ""]
    rows = doc.get("mappings") or []
    waiting = [m for m in rows if not m.get("confirmed")]
    L.append(f"매핑 {len(rows)}건 · 승인 대기 {len(waiting)}건 · "
             f"후보 {len(doc.get('candidates') or [])}건")
    L.append("")
    for m in rows:
        tb = m.get("textbook", {})
        mark = "x" if m.get("confirmed") else " "
        books = ", ".join(
            f"{c.get('id')}({_pt(c.get('points'))}, {c.get('role')})"
            for c in (m.get("casebook") or []))
        L.append(f"[{mark}] {tb.get('chapter','')} > {tb.get('section','')}  ← {books}")
        L.append(f"    근거: {_evidence(m)}  [score {m.get('score')}]")
        if int(m.get("score") or 0) < 3:
            L.append("    ⚠️ 근거 부족 — 확인 필요")
        L.append("")
    for m in (doc.get("candidates") or []):
        tb = m.get("textbook", {})
        books = ", ".join(str(c.get("id")) for c in (m.get("casebook") or []))
        L.append(f"[!] {tb.get('chapter','')} > {tb.get('section','')}  ← {books}")
        L.append(f"    근거: {_evidence(m)}  [score {m.get('score')}]")
        L.append("    ⚠️ 근거 하나뿐 — 후보로만 두었다")
        L.append("")
    un = doc.get("unmapped") or {}
    L.append(f"짝 없음: 기본서 절 {len(un.get('textbook_sections') or [])}개 · "
             f"사례집 문제 {len(un.get('casebook_problems') or [])}개")
    return "\n".join(L) + "\n"


def _pt(v) -> str:
    return "점수 미상" if v is None else f"{v:g}점"


def _evidence(m: dict) -> str:
    e = m.get("evidence") or {}
    kw = e.get("title_keyword") or []
    parts = [f"제목키워드 {', '.join(_q(k) for k in kw)}" if kw else "제목키워드 없음",
             f"사건번호 {len(e.get('shared_cases') or [])}건",
             f"두문자 {len(e.get('shared_mnemonics') or [])}건"]
    near = e.get("near_mnemonics") or []
    if near:
        parts.append(f"근접 두문자 {len(near)}건")
    return " / ".join(parts)


def confirm(path, section: str | None = None, all_: bool = False) -> int:
    """사람이 검토한 매핑에 confirmed: true 를 찍는다.

    yaml 을 다시 써 내면 주석이 날아간다. 그래서 해당 줄만 바꾼다.
    """
    p = Path(path)
    rows = p.read_text(encoding="utf-8").splitlines()
    want = re.compile(r'^\s*section:\s*"(?P<t>.*)"\s*$')
    hits, live = 0, all_
    for i, line in enumerate(rows):
        m = want.match(line)
        if m and section is not None:
            live = section in m.group("t")
        if live and re.match(r"^\s*confirmed:\s*false\s*$", line):
            rows[i] = line.replace("false", "true")
            hits += 1
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return hits


def validate(doc: dict) -> tuple[list, list]:
    """M1~M4. (FAIL, WARN)"""
    fails, warns = [], []
    rows = doc.get("mappings") or []
    seen: dict = {}
    for m in rows:
        for c in (m.get("casebook") or []):
            path = c.get("file")
            if m.get("confirmed") and path and not Path(path).exists():
                fails.append(f"M2 파일이 없다: {path}")
            seen.setdefault(c.get("id"), []).append(c.get("role"))
        tb = (m.get("textbook") or {}).get("file")
        if m.get("confirmed") and tb and not Path(tb).exists():
            fails.append(f"M2 파일이 없다: {tb}")
    for pid, roles in seen.items():
        if len(roles) > 1 and any(r != "composite" for r in roles):
            warns.append(f"M3 문제 {pid} 가 {len(roles)}곳에 쓰였다 "
                         f"(role: {', '.join(str(r) for r in roles)})")
    left = (doc.get("unmapped") or {}).get("casebook_problems") or []
    if left:
        warns.append(f"M1 어디에도 안 붙은 사례집 문제 {len(left)}개: "
                     + ", ".join(str(x) for x in left[:10]))
    checked = set()
    for m in rows + (doc.get("candidates") or []):
        for c in (m.get("casebook") or []):
            pid, total, part = c.get("id"), c.get("points"), c.get("points_sum")
            if pid in checked:
                continue
            checked.add(pid)
            if total is None:
                warns.append(f"M4 문제 {pid} 의 총점을 못 읽었다 — 배점 오인식 가능")
            elif part is None:
                warns.append(f"M4 문제 {pid} 의 답안 배점을 하나도 못 읽었다")
            elif abs(float(total) - float(part)) > 0.01:
                warns.append(f"M4 문제 {pid} 의 배점 합계 {part:g} 가 "
                             f"총점 {float(total):g} 과 다르다 — 어딘가 잘못 읽었다")
    return fails, warns


# ── 진단 ────────────────────────────────────────────────────────
def debug_report(data: dict, sample: int = 40) -> str:
    """왜 이렇게 판정됐는지 사람이 볼 수 있게 늘어놓는다.

    점수가 낮게 나올 때 어느 근거가 안 걸리는지를 짐작하지 않기 위한 것이다.
    셋 중 무엇이 몇 번 걸렸는지, 제목 키워드가 어떻게 잘렸는지, 짝을 못 찾은
    문제가 무엇인지를 그대로 보여준다.
    """
    sections, problems = data["sections"], data["problems"]
    matches = data["matches"]
    flat = [m for ms in matches.values() for m in ms]

    L = ["# 매핑 진단", "",
         f"기본서 md {len(data['files']['textbook'])}개 → 절 {len(sections)}개",
         f"사례집 md {len(data['files']['casebook'])}개 → 문제 {len(problems)}개",
         f"짝 후보 {len(flat)}쌍", ""]

    # 점수 분포
    L += ["## 점수 분포", "", "| score | 쌍 | 절 |", "|---:|---:|---:|"]
    for s in (3, 2, 1):
        pairs = sum(1 for m in flat if m.score == s)
        secs = sum(1 for ms in matches.values() if max(x.score for x in ms) == s)
        L.append(f"| {s} | {pairs} | {secs} |")
    L.append("")

    # 근거 조합
    L += ["## 어느 근거가 걸렸나", "",
          "| 제목키워드 | 사건번호 | 두문자 | 쌍 |", "|---|---|---|---:|"]
    combo: dict = {}
    for m in flat:
        key = (bool(m.keywords), bool(m.cases), bool(m.mnemonics or m.near))
        combo[key] = combo.get(key, 0) + 1
    for key in sorted(combo, key=lambda k: -combo[k]):
        L.append("| " + " | ".join("○" if x else "·" for x in key)
                 + f" | {combo[key]} |")
    L.append("")
    L.append(f"제목키워드가 걸린 쌍 {sum(1 for m in flat if m.keywords)} · "
             f"사건번호 {sum(1 for m in flat if m.cases)} · "
             f"두문자 {sum(1 for m in flat if m.mnemonics)} · "
             f"근접 두문자 {sum(1 for m in flat if m.near and not m.mnemonics)}")
    L.append("")

    # 알맹이가 실려 있나
    L += ["## 알맹이 집계", "",
          "| | 사건번호 0건 | 두문자 0건 | 둘 다 0건 |", "|---|---:|---:|---:|"]
    for name, items in (("기본서 절", sections), ("사례집 문제", problems)):
        no_c = sum(1 for x in items if not x.cases)
        no_m = sum(1 for x in items if not x.mnemonics)
        both = sum(1 for x in items if not x.cases and not x.mnemonics)
        L.append(f"| {name} {len(items)}개 | {no_c} | {no_m} | {both} |")
    L.append("")

    # 표본
    L += [f"## 사례집 문제 표본 (앞 {sample}개)", "",
          "| id | 제목 | 쪼갠 키워드 | 총점 | 답안 | 사건 | 두문자 |",
          "|---|---|---|---:|---:|---:|---:|"]
    for p in problems[:sample]:
        L.append(f"| `{p.id}` | {p.title} | {' / '.join(p.keywords)} "
                 f"| {p.points if p.points is not None else '—'} "
                 f"| {len(p.answers)} | {len(p.cases)} | {len(p.mnemonics)} |")
    L += ["", f"## 기본서 절 표본 (앞 {sample}개)", "",
          "| 장 | 절 | 알맹이 | 사건 | 두문자 |", "|---|---|---|---:|---:|"]
    for s in sections[:sample]:
        L.append(f"| {s.chapter} | {s.title} | {s.name} "
                 f"| {len(s.cases)} | {len(s.mnemonics)} |")

    # 짝 없는 문제 — 여기가 제일 중요하다
    left = [p for p in problems if p.id not in data["used"]]
    L += ["", f"## 근거 2개 이상으로 붙지 못한 사례집 문제 {len(left)}개", ""]
    for p in left:
        best = max((m for m in flat if m.prob.id == p.id),
                   key=lambda m: m.score, default=None)
        why = ("아무 절에도 안 걸림" if best is None else
               f"최선 {best.section.title} (score {best.score})")
        L.append(f"- `{p.id}` {p.title} — {why}")
    return "\n".join(L) + "\n"
