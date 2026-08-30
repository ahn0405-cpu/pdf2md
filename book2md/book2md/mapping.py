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
#: 제목에 붙은 각주 참조. 'VI. 과실상계[^267]' 의 알맹이는 '과실상계' 다
_FOOTREF = re.compile(r"\[\^\d+\]")
#: 장 제목 앞 일련번호. '046 일부청구' → '일부청구'
_CHAP_NUM = re.compile(r"^\s*\d{1,4}[.\s]\s*")
#: 사례집 목차 쪽. 제목에 점선과 쪽수가 붙는다
_TOC_DOTS = re.compile(r"\.{4,}|…{2,}")


def _plain(text: str) -> str:
    return _FOOTREF.sub("", _MARKUP.sub("", text or "")).strip()


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

    @property
    def chapter_name(self) -> str:
        """번호를 뗀 장 이름. '046 일부청구' → '일부청구'

        실물 기본서의 절 제목은 'I. 의의 / II. 내용 / III. 효과' 처럼 정형이라
        논점 이름을 담지 않는다. 논점 이름은 장 제목에 있다.
        """
        return _CHAP_NUM.sub("", self.chapter).strip()


@dataclass
class Answer:
    """답안 목차 한 줄. 소제목까지 받는다.

    소제목이 기본서 절 제목을 그대로 따라간다 — '(1) 신의칙 의의 및 취지' ↔
    'I. 의의 및 취지'. 문제 제목만으로는 장까지밖에 못 좁히는데, 이걸 보면
    절을 고를 수 있다.
    """
    title: str
    points: float | None = None
    level: int = 3
    parent: float | None = None      # 소제목이면 상위 항목의 배점

    @property
    def name(self) -> str:
        return _ROMAN_LEAD.sub("", self.title).strip()

    @property
    def worth(self) -> float | None:
        return self.points if self.points is not None else self.parent


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

    from_toc: bool = False

    @property
    def looks_like_toc(self) -> bool:
        """사례집 앞머리의 목차 쪽에서 온 가짜 문제인가.

        목차 줄은 제목 뒤에 점선과 쪽수가 붙고 다음 문제까지 한 줄에 이어진다.
        실측: 'D-20. 증서진부확인의 쇠 ......233D-21. 장래이행의 쇠....237'
        """
        return (self.from_toc or bool(_TOC_DOTS.search(self.title))
                or len(self.title) > 120)

    @property
    def points_sum(self) -> float | None:
        """답안 목차 배점의 합.

        실물 사례집은 문제 제목에 총점을 적지 않는다. 그래서 이 합이 사실상
        총점 노릇을 한다. 지침 §M4 의 '합계 vs 총점' 검산은 대조군이 없어
        돌릴 수 없고, 대신 배점을 못 읽은 항목 수로 갈음한다.
        """
        known = [a.points for a in self.answers
                 if a.level == 3 and a.points is not None]
        return round(sum(known), 2) if known else None

    @property
    def points_missing(self) -> int:
        return sum(1 for a in self.answers
                   if a.level == 3 and a.points is None)

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


def read_casebook(files, pat: Patterns, cfg: dict | None = None) -> list[Problem]:
    """사례집에서 문제를 뽑는다. 답안 목차와 배점도 함께.

    총점은 제목이 아니라 **문제 지문 끝**에 있다 — '…설명하시오. (14점)'.
    제목에서만 찾으면 하나도 못 읽는다.
    """
    mp = (cfg or {}).get("mapping") or {}
    total_rx = re.compile(mp["total_points"]) if mp.get("total_points") else None
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
                if cur.points is None and total_rx is not None:
                    hit = total_rx.search(blob)
                    if hit:
                        cur.points = float(hit.group(1))
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
                    parent = _points_of(marks)
                    cur.answers.append(Answer(title=title, points=parent, level=3))
                elif level == 4:
                    up = next((a.points for a in reversed(cur.answers)
                               if a.level == 3), None)
                    cur.answers.append(Answer(title=title, points=_points_of(marks),
                                              level=4, parent=up))
                buf.append(line)
        close()

    # 목차 쪽에서 온 껍데기 — 같은 번호가 두 번 실리면 진짜 쪽이 가려진다
    seen: dict = {}
    for p in out:
        seen[p.id] = seen.get(p.id, 0) + 1
    for p in out:
        if seen[p.id] > 1 and not p.answers:
            p.from_toc = True
    return out


# ── 근거 ────────────────────────────────────────────────────────
def _hits(name: str, prob: Problem) -> list[str]:
    flat_name = re.sub(r"\s+", "", name)
    if len(flat_name) < 2:
        return []
    out = []
    for kw in prob.keywords:
        flat = re.sub(r"\s+", "", kw)
        if len(flat) >= 2 and (flat_name in flat or flat in flat_name):
            out.append(kw)
    return out


def _chap_hit(section: Section, prob: Problem) -> list[str]:
    """장 제목이 겹치는가. 절 제목이 정형이라 여기에 논점 이름이 있다."""
    return _hits(section.chapter_name, prob)


def _kw_hit(section: Section, prob: Problem) -> list[str]:
    """제목 키워드가 겹치는가. 부분 일치도 인정한다 (지침 §근거1)."""
    return _hits(section.name, prob)


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


def _ans_hit(section: Section, prob: Problem, cfg: dict) -> list[str]:
    """답안 목차가 기본서 절 제목을 따라가는가.

    실물 사례집의 답안 목차는 기본서 절 구조를 그대로 옮겨 적는다.
        'E-2 > 3. 일부청구 후 잔부청구 중복소제기 해당 여부' ↔ 'III. 중복소제기'
    사례집이 판시를 요지로만 압축해 실어 사건번호·두문자가 희박한 실물에서,
    이것이 가장 판정력이 높은 근거다.

    다만 '의의' '내용' '요건' '효과' 같은 짧은 절 이름은 어느 장에나 있어서
    다 걸린다. 길이와 뼈대 말로 막는다.
    """
    mp = cfg.get("mapping") or {}
    if not mp.get("answer_outline", True):
        return []
    name = section.name
    flat = re.sub(r"\s+", "", name)
    if len(flat) < int(mp.get("outline_min_len", 3)):
        return []
    deny = {re.sub(r"\s+", "", w) for w in (mp.get("outline_deny") or [])}
    if flat in deny:
        return []
    out = []
    for a in prob.answers:
        an = re.sub(r"\s+", "", a.name)
        if not an or an in deny:
            continue
        if flat in an or an in flat:
            out.append(a.title)
    return out


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
            if best is None or (a.worth or 0) > (best.worth or 0):
                best = a
    if best is None or best.worth is None:
        return "composite", None
    pts = best.worth
    known = [a.points for a in prob.answers
             if a.level == 3 and a.points is not None]
    if known and pts >= max(known):
        return "primary", pts
    total = prob.points or (sum(known) if known else 0)
    if total and pts >= total * 0.25:
        return "composite", pts
    return "incidental", pts


@dataclass
class Match:
    section: Section
    prob: Problem
    keywords: list
    chapter: list
    cases: list
    mnemonics: list
    near: list
    outline: list
    role: str
    points: float | None

    @property
    def score(self) -> int:
        """지침 §점수와 처리 그대로 0~3. 근거 1 은 장·절 어느 쪽이든 성립한다."""
        return sum(bool(x) for x in (self.keywords or self.chapter,
                                     self.cases,
                                     self.mnemonics or self.near))

    @property
    def strength(self) -> tuple:
        """같은 score 안에서 무엇을 먼저 볼지.

        실물에서는 사건번호·두문자가 희박해 score 1 이 1200쌍 넘게 나온다.
        점수를 부풀리는 대신 사람이 위에서부터 훑을 수 있게 줄을 세운다.
        긴 키워드가 맞은 쪽이 우연일 확률이 낮다.
        """
        kw_len = sum(len(re.sub(r"\s+", "", k)) for k in self.keywords)
        ch_len = sum(len(re.sub(r"\s+", "", k)) for k in self.chapter)
        return (self.score, len(self.outline), len(self.cases),
                len(self.mnemonics), kw_len, ch_len, len(self.near))

    @property
    def strong(self) -> bool:
        """mappings 로 올릴 것인가.

        지침은 score 2 이상을 올리라고 한다. 실물에서는 사례집이 사건번호를
        거의 안 실어 score 2 가 드물다. 답안 목차가 맞은 것은 그 하나로도
        판정력이 높아 함께 올린다 — 어차피 사람 승인을 거친다.
        """
        return self.score >= 2 or bool(self.outline)


@dataclass
class ChapterMatch:
    """장 이름만 맞고 절은 못 고른 것. 절은 사람이 고른다."""
    chapter: str
    file: str
    sections: list
    prob: Problem
    keywords: list

    @property
    def score(self) -> int:
        return 1


def build(roots, cfg: dict) -> dict:
    """폴더(들)을 통째로 받아 기본서·사례집을 갈라 읽고 매핑한다."""
    if isinstance(roots, (str, Path)):
        roots = [roots]
    pat = Patterns.build(cfg)
    tb_files, cb_files, other = sort_by_source(roots, cfg)
    sections = read_textbook(tb_files, pat)
    problems = read_casebook(cb_files, pat, cfg)

    dropped = [p for p in problems if p.looks_like_toc]
    problems = [p for p in problems if not p.looks_like_toc]

    by_section: dict[int, list[Match]] = {}
    used: set = set()
    # 장 이름이 맞은 (장, 문제) — 절까지 고른 것은 뒤에서 뺀다
    chap_hits: dict = {}
    for i, sec in enumerate(sections):
        for prob in problems:
            ck = _chap_hit(sec, prob)
            if ck:
                key = (sec.chapter, sec.file, prob.id)
                chap_hits.setdefault(key, [prob, ck, []])[2].append(sec.title)
            kw = _kw_hit(sec, prob)
            cs = sorted(sec.cases & prob.cases)
            mn, near = _mn_hit(sec, prob)
            ans = _ans_hit(sec, prob, cfg)
            if not (kw or cs or mn or near or ans):
                continue
            role, pts = _role(sec, prob)
            m = Match(sec, prob, kw, ck, cs, mn, near, ans, role, pts)
            by_section.setdefault(i, []).append(m)
            if m.strong:
                used.add(prob.id)

    placed = {(m.section.chapter, m.section.file, m.prob.id)
              for ms in by_section.values() for m in ms}
    chapters = [ChapterMatch(chapter=ch, file=f, sections=secs,
                             prob=prob, keywords=ck)
                for (ch, f, pid), (prob, ck, secs) in sorted(chap_hits.items())
                if (ch, f, pid) not in placed]
    for c in chapters:
        used.add(c.prob.id)

    return {"sections": sections, "problems": problems, "dropped": dropped,
            "matches": by_section, "chapters": chapters, "used": used,
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
        (strong if any(m.strong for m in ms) else weak).append((sec, ms))

    def emit(items, indent="  "):
        for sec, ms in items:
            ms = sorted(ms, key=lambda m: (tuple(-x for x in m.strength),
                                           m.prob.id))
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
            chs = sorted({k for m in ms for k in m.chapter})
            kws = sorted({k for m in ms for k in m.keywords})
            cs = sorted({c for m in ms for c in m.cases})
            mn = sorted({x for m in ms for x in m.mnemonics})
            nr = sorted({x for m in ms for x in m.near})
            ao = sorted({x for m in ms for x in m.outline})
            L.append(f"{indent}  evidence:")
            L.append(f"{indent}    title_keyword: [" + ", ".join(_q(k) for k in kws) + "]")
            L.append(f"{indent}    chapter_keyword: [" + ", ".join(_q(k) for k in chs) + "]")
            L.append(f"{indent}    shared_cases: [" + ", ".join(_q(c) for c in cs) + "]")
            L.append(f"{indent}    shared_mnemonics: [" + ", ".join(_q(x) for x in mn) + "]")
            if ao:
                L.append(f"{indent}    # 답안 목차가 이 절을 그대로 따라간다")
                L.append(f"{indent}    answer_outline: [" + ", ".join(_q(x) for x in ao) + "]")
            if nr:
                L.append(f"{indent}    # 한 글자 차이 — 두문자 결정표에서 확정할 것")
                L.append(f"{indent}    near_mnemonics: [" + ", ".join(_q(x) for x in nr) + "]")
            top = max(m.score for m in ms)
            L.append(f"{indent}  score: {top}")
            if top < 2 and ao:
                L.append(f"{indent}  # score 는 지침의 세 근거만 센다. "
                         f"이 줄은 답안 목차로 올렸다.")
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
    L.append("# 장 이름만 맞고 절은 못 골랐다. 실물 기본서의 절 제목은")
    L.append("# 'I. 의의 / II. 내용 / III. 효과' 처럼 정형이라 논점 이름이 없다.")
    L.append("# 어느 절인지는 사람이 고를 것 — sections 에 후보를 적어 두었다.")
    L.append("chapter_mappings:")
    if data.get("chapters"):
        for c in sorted(data["chapters"], key=lambda c: (c.chapter, c.prob.id)):
            L.append("  - textbook:")
            L.append(f"      chapter: {_q(c.chapter)}")
            L.append(f"      section: null      # ← 아래 sections 에서 고를 것")
            L.append(f"      file: {_q(c.file)}")
            L.append("      sections: [" + ", ".join(_q(x) for x in c.sections) + "]")
            L.append("    casebook:")
            L.append(f"      - id: {_q(c.prob.id)}")
            L.append(f"        title: {_q(c.prob.title)}")
            L.append(f"        points: "
                     f"{c.prob.points if c.prob.points is not None else 'null'}")
            L.append(f"        points_sum: "
                     f"{c.prob.points_sum if c.prob.points_sum is not None else 'null'}")
            L.append(f"        file: {_q(c.prob.file)}")
            L.append("        role: composite")
            L.append("    evidence:")
            L.append("      chapter_keyword: ["
                     + ", ".join(_q(k) for k in c.keywords) + "]")
            L.append("    score: 1")
            L.append("    confirmed: false")
    else:
        L.append("  []")
    L.append("")
    if data.get("dropped"):
        L.append("# 사례집 목차 쪽에서 온 가짜 문제 — 버렸다")
        L.append("# (제목에 점선과 쪽수가 붙어 다음 문제까지 한 줄에 이어진 것)")
        L.append("dropped_toc_rows:")
        for p in data["dropped"]:
            L.append(f"  - {_q(p.id)}")
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
    chaps = doc.get("chapter_mappings") or []
    L.append(f"매핑 {len(rows)}건 · 승인 대기 {len(waiting)}건 · "
             f"후보 {len(doc.get('candidates') or [])}건 · "
             f"장 단위 {len(chaps)}건")
    L.append("")
    for m in rows:
        tb = m.get("textbook", {})
        mark = "x" if m.get("confirmed") else " "
        ao = (m.get("evidence") or {}).get("answer_outline") or []
        books = ", ".join(
            f"{c.get('id')}({_pt(c.get('points'))}, {c.get('role')})"
            for c in (m.get("casebook") or []))
        L.append(f"[{mark}] {tb.get('chapter','')} > {tb.get('section','')}  ← {books}")
        L.append(f"    근거: {_evidence(m)}  [score {m.get('score')}]")
        if int(m.get("score") or 0) < 2 and ao:
            L.append("    ※ 답안 목차가 이 절을 그대로 따라간다 — 그래서 올렸다")
        elif int(m.get("score") or 0) < 3:
            L.append("    ⚠️ 근거 부족 — 확인 필요")
        L.append("")
    for m in (doc.get("candidates") or []):
        tb = m.get("textbook", {})
        books = ", ".join(str(c.get("id")) for c in (m.get("casebook") or []))
        L.append(f"[!] {tb.get('chapter','')} > {tb.get('section','')}  ← {books}")
        L.append(f"    근거: {_evidence(m)}  [score {m.get('score')}]")
        L.append("    ⚠️ 근거 하나뿐 — 후보로만 두었다")
        L.append("")
    if chaps:
        L.append("## 장 이름만 맞은 것 — 절은 사람이 고를 것")
        L.append("")
    for m in chaps:
        tb = m.get("textbook", {})
        books = ", ".join(str(c.get("id")) for c in (m.get("casebook") or []))
        L.append(f"[~] {tb.get('chapter','')} > (절 미정)  ← {books}")
        L.append(f"    근거: {_evidence(m)}")
        secs = tb.get("sections") or []
        L.append("    절 후보: " + (" | ".join(str(x) for x in secs) or "없음"))
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
    ch = e.get("chapter_keyword") or []
    parts = []
    if kw:
        parts.append(f"절 제목 {', '.join(_q(k) for k in kw)}")
    if ch:
        parts.append(f"장 제목 {', '.join(_q(k) for k in ch)}")
    if not kw and not ch:
        parts.append("제목키워드 없음")
    if "shared_cases" in e or "shared_mnemonics" in e:
        parts.append(f"사건번호 {len(e.get('shared_cases') or [])}건")
        parts.append(f"두문자 {len(e.get('shared_mnemonics') or [])}건")
    near = e.get("near_mnemonics") or []
    if near:
        parts.append(f"근접 두문자 {len(near)}건")
    ao = e.get("answer_outline") or []
    if ao:
        parts.append(f"답안 목차 {len(ao)}건")
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
    # M3 — 한 문제가 여러 절에 걸리는 것은 이 책에서 정상이다(지침 §근거1 주의).
    # 문제마다 한 줄씩 내면 나머지 경고가 묻히므로 세어서 한 줄로 낸다.
    multi = [(pid, roles) for pid, roles in seen.items()
             if len(roles) > 1 and any(r != "composite" for r in roles)]
    if multi:
        multi.sort(key=lambda x: -len(x[1]))
        head = ", ".join(f"{pid}({len(r)}곳)" for pid, r in multi[:8])
        warns.append(f"M3 여러 절에 쓰인 문제 {len(multi)}개 — composite 이 아닌 "
                     f"역할이 섞였다. 많이 쓰인 것부터: {head}")
    for m in (doc.get("chapter_mappings") or []):
        tb = m.get("textbook") or {}
        if m.get("confirmed") and not tb.get("section"):
            fails.append(f"M2 장 {tb.get('chapter')} 의 절을 안 고르고 승인했다 "
                         f"— sections 에서 하나를 골라 적을 것")
        if m.get("confirmed") and tb.get("file") and not Path(tb["file"]).exists():
            fails.append(f"M2 파일이 없다: {tb['file']}")
    left = (doc.get("unmapped") or {}).get("casebook_problems") or []
    if left:
        warns.append(f"M1 어디에도 안 붙은 사례집 문제 {len(left)}개: "
                     + ", ".join(str(x) for x in left[:10]))
    # M4 — 배점 검산. 문제마다 한 줄씩 내면 수백 줄이 되어 나머지를 덮는다.
    # 세어서 한 줄로 알리고, 어긋난 폭이 큰 것부터 몇 개만 보여준다.
    checked: dict = {}
    for m in rows + (doc.get("candidates") or []) + (doc.get("chapter_mappings") or []):
        for c in (m.get("casebook") or []):
            checked.setdefault(c.get("id"), c)
    no_total = [k for k, c in checked.items() if c.get("points") is None]
    no_part = [k for k, c in checked.items()
               if c.get("points") is not None and c.get("points_sum") is None]
    gaps = []
    for k, c in checked.items():
        t, s_ = c.get("points"), c.get("points_sum")
        if t is not None and s_ is not None and abs(float(t) - float(s_)) > 0.01:
            gaps.append((float(t) - float(s_), k, float(t), float(s_)))
    if no_total:
        warns.append(f"M4 총점을 못 읽은 문제 {len(no_total)}개: "
                     + ", ".join(str(x) for x in sorted(no_total)[:10]))
    if no_part:
        warns.append(f"M4 답안 배점을 하나도 못 읽은 문제 {len(no_part)}개: "
                     + ", ".join(str(x) for x in sorted(no_part)[:10]))
    if gaps:
        gaps.sort(key=lambda g: -abs(g[0]))
        head = "; ".join(f"{k} {s_:g}≠{t:g}" for _, k, t, s_ in gaps[:8])
        warns.append(f"M4 배점 합계가 총점과 다른 문제 {len(gaps)}/{len(checked)}개 "
                     f"— 배점을 못 읽은 항목이 있다는 뜻이다. 큰 것부터: {head}")
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
    for sc in (3, 2, 1):
        pairs = sum(1 for m in flat if m.score == sc)
        secs = sum(1 for ms in matches.values() if max(x.score for x in ms) == sc)
        L.append(f"| {sc} | {pairs} | {secs} |")
    L.append("")
    L.append(f"매핑으로 올린 쌍 {sum(1 for m in flat if m.strong)} "
             f"(score 2 이상이거나 답안 목차가 맞은 것)")
    L.append("")

    # 근거 조합
    L += ["## 어느 근거가 걸렸나", "",
          "| 절 제목 | 장 제목 | 답안 목차 | 사건번호 | 두문자 | 쌍 |",
          "|---|---|---|---|---|---:|"]
    combo: dict = {}
    for m in flat:
        key = (bool(m.keywords), bool(m.chapter), bool(m.outline),
               bool(m.cases), bool(m.mnemonics or m.near))
        combo[key] = combo.get(key, 0) + 1
    for key in sorted(combo, key=lambda k: -combo[k]):
        L.append("| " + " | ".join("○" if x else "·" for x in key)
                 + f" | {combo[key]} |")
    L.append("")
    L.append(f"장 이름만 맞아 절을 못 고른 (장, 문제) "
             f"{len(data.get('chapters') or [])}건 · "
             f"목차 쪽에서 온 가짜 문제 {len(data.get('dropped') or [])}건 버림")
    L.append("")
    L.append(f"절 제목이 걸린 쌍 {sum(1 for m in flat if m.keywords)} · "
             f"장 제목 {sum(1 for m in flat if m.chapter)} · "
             f"답안 목차 {sum(1 for m in flat if m.outline)} · "
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
    with_pt = sum(1 for p in problems if p.points is not None)
    ans_pt = sum(1 for p in problems for a in p.answers if a.points is not None)
    ans_all = sum(len(p.answers) for p in problems)
    L += ["## 배점을 읽었나", "",
          f"- 총점을 읽은 문제 {with_pt}/{len(problems)}개",
          f"- 배점을 읽은 답안 항목 {ans_pt}/{ans_all}개",
          "",
          "둘 다 0 이면 백틱 표시(`` `10점` ``)가 아예 없다는 뜻이다. "
          "아래 「제목 원문」을 볼 것.", ""]

    # 제목이 실제로 어떻게 생겼는지 — 짐작하지 않기 위해
    L += ["## 제목 원문 (사례집 첫 파일)", "", "```"]
    cb = data["files"]["casebook"]
    if cb:
        L.append(f"# {cb[0]}")
        n = 0
        for line in Path(cb[0]).read_text(encoding="utf-8").splitlines():
            if _HEAD.match(line):
                L.append(line)
                n += 1
                if n >= sample:
                    break
    L += ["```", ""]

    L += [f"## 사례집 문제 표본 (앞 {sample}개)", "",
          "| id | 제목 | 쪼갠 키워드 | 총점 | 답안 | 배점읽음 | 사건 | 두문자 |",
          "|---|---|---|---:|---:|---:|---:|---:|"]
    for p in problems[:sample]:
        got = sum(1 for a in p.answers if a.points is not None)
        L.append(f"| `{p.id}` | {p.title} | {' / '.join(p.keywords)} "
                 f"| {p.points if p.points is not None else '—'} "
                 f"| {len(p.answers)} | {got} | {len(p.cases)} | {len(p.mnemonics)} |")
    L += ["", f"## 기본서 절 표본 (앞 {sample}개)", "",
          "| 장 | 장 알맹이 | 절 | 절 알맹이 | 사건 | 두문자 |",
          "|---|---|---|---|---:|---:|"]
    for sec in sections[:sample]:
        L.append(f"| {sec.chapter} | {sec.chapter_name} | {sec.title} "
                 f"| {sec.name} | {len(sec.cases)} | {len(sec.mnemonics)} |")
    if data.get("chapters"):
        L += ["", "## 장 이름만 맞은 것 (앞 %d개)" % sample, "",
              "| 장 | 문제 | 맞은 키워드 | 절 후보 |", "|---|---|---|---|"]
        for c in data["chapters"][:sample]:
            L.append(f"| {c.chapter} | `{c.prob.id}` {c.prob.title} "
                     f"| {' / '.join(c.keywords)} | {' · '.join(c.sections)} |")
    if data.get("dropped"):
        L += ["", "## 목차 쪽에서 온 가짜 문제 (버림)", ""]
        for p in data["dropped"]:
            L.append(f"- `{p.id}` {p.title[:80]}")

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
