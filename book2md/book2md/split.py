"""분할과 프론트매터 (§6.3).

기본서는 장(章) 단위, 400KB 를 넘으면 절 단위로 다시 쪼갠다.
사례집은 문제 그룹(E, F…) 단위다.

프론트매터의 `cases` 는 후속 처리가 판례 누락을 검사하는 근거다. 그래서
본문에 실제로 나온 사건번호만 넣는다. 여기서 새로 만들어 넣지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import is_generated
from .structure import Block, render

_SAFE = re.compile(r"[^\w가-힣]+")


@dataclass
class Part:
    """파일 하나가 될 블록 묶음."""
    index: int
    title: str
    chapter: str = ""
    section: str = ""
    blocks: list = field(default_factory=list)

    def text(self) -> str:
        return render(self.blocks)


def split(blocks: list[Block], prof: dict) -> list[Part]:
    mode = prof.get("split", "chapter")
    limit = int(prof.get("split_max_bytes", 0))
    if mode == "group":
        parts = _split_group(blocks)
    elif any(b.kind == "heading" and b.level == 2 for b in blocks):
        parts = _split_chapter(blocks)
    else:
        # 이 교재는 장 제목이 쪽마다 되풀이되는 꼬리말로만 찍혀 있어서
        # 본문에는 없다. 그럴 때는 논점(절) 단위로 나눈다. 안 그러면 한 덩어리를
        # 크기로만 쪼개어 '머리1', '머리2' 같은 이름이 붙는다.
        parts = _split_level(blocks, 3, prof.get("split_prefer"))
    if limit:
        parts = _resplit(parts, limit)
    for k, part in enumerate(parts, 1):
        part.index = k
    return parts


def _split_chapter(blocks) -> list[Part]:
    """장(H2) 마다 자른다. 첫 장 앞의 편 제목은 그 장에 딸려 간다."""
    parts, current, lead = [], None, []
    chapter = ""
    for b in blocks:
        if b.kind == "heading" and b.level <= 2:
            if b.level == 1:
                lead.append(b)
                chapter = _plain(b.text)
                continue
            if current:
                parts.append(current)
            title = _plain(b.text)
            current = Part(index=0, title=title,
                           chapter=f"{chapter} {title}".strip() if chapter else title)
            current.blocks.extend(lead)
            lead = []
            current.blocks.append(b)
            continue
        if current is None:
            current = Part(index=0, title="머리", chapter=chapter)
            current.blocks.extend(lead)
            lead = []
        current.blocks.append(b)
    if current:
        parts.append(current)
    return parts or [Part(index=1, title="전체", blocks=list(blocks))]


def _split_level(blocks, level: int, prefer: str | None = None) -> list[Part]:
    """주어진 수준의 헤딩마다 자른다. 파일 이름은 그 제목에서 딴다.

    prefer 무늬에 맞는 제목이 하나라도 있으면 **그것만** 경계로 삼는다.
    이 교재의 논점 번호('046 일부청구')가 그것이다. 같은 수준의 'N. 학설'
    에서도 자르면 학설·判例·검토가 서로 다른 파일로 흩어진다.
    """
    rx = re.compile(prefer) if prefer else None
    if rx and not any(b.kind == "heading" and b.level <= level
                      and rx.search(_plain(b.text)) for b in blocks):
        rx = None

    parts, current, lead = [], None, []
    for b in blocks:
        if b.kind == "heading" and b.level <= level and (
                rx is None or rx.search(_plain(b.text))):
            if current:
                parts.append(current)
            title = _plain(b.text)
            current = Part(index=0, title=title, chapter=title)
            current.blocks.extend(lead)
            lead = []
            current.blocks.append(b)
            continue
        if current is None:
            lead.append(b)
            continue
        current.blocks.append(b)
    if lead and not parts and not current:
        current = Part(index=0, title="머리", blocks=lead)
    elif lead and current is None:
        current = Part(index=0, title="머리", blocks=lead)
    elif lead:
        parts.insert(0, Part(index=0, title="머리", blocks=lead))
    if current:
        parts.append(current)
    return parts or [Part(index=1, title="전체", blocks=list(blocks))]


def _split_group(blocks) -> list[Part]:
    """사례집: 문제 번호의 앞 글자(E, F…)가 바뀌면 새 파일."""
    parts, current, letter = [], None, None
    for b in blocks:
        m = re.match(r"^([A-Z])-(\d+)\.", _plain(b.text)) if b.kind == "heading" else None
        if m and m.group(1) != letter:
            if current:
                parts.append(current)
            letter = m.group(1)
            current = Part(index=0, title=_topic(_plain(b.text)), chapter=letter)
        if current is None:
            current = Part(index=0, title="머리", chapter="")
        current.blocks.append(b)
    if current:
        parts.append(current)
    return parts or [Part(index=1, title="전체", blocks=list(blocks))]


def _resplit(parts, limit) -> list[Part]:
    """400KB 를 넘는 장을 절(H3) 단위로 다시 쪼갠다 (§6.3)."""
    out = []
    for part in parts:
        if len(part.text().encode("utf-8")) <= limit:
            out.append(part)
            continue
        chunk, made = None, []
        for b in part.blocks:
            if b.kind == "heading" and b.level <= 3 and chunk and chunk.blocks:
                made.append(chunk)
                chunk = None
            if chunk is None:
                head = _plain(b.text) if b.kind == "heading" else ""
                chunk = Part(index=0, title=head or part.title,
                             chapter=part.chapter, section=head)
            chunk.blocks.append(b)
        if chunk:
            made.append(chunk)
        for k, m in enumerate(made, 1):
            if not m.section:                    # 제목을 못 찾은 조각만 번호로
                m.title = f"{part.title}-{k}"
        out.extend(made)
    return out


def filename(part: Part, prof: dict) -> str:
    stem = _SAFE.sub("", part.title)[:40] or f"part{part.index}"
    if prof.get("split") == "group":
        return f"{part.chapter or 'X'}_{stem}.md"
    return f"{part.index:02d}_{stem}.md"


def front_matter(part: Part, prof: dict, parser: str, validation: str) -> str:
    """§6.3 프론트매터. 본문에서 실제로 뽑힌 값만 싣는다."""
    cases, seen = [], set()
    mnemonics, bonus, outline, years, sidenote, sections = [], [], [], [], "", []
    for b in part.blocks:
        for c in b.cases:
            if c["id"] in seen:
                # 같은 사건번호가 여러 번 나오면 라벨·별표는 처음 것을 살리되
                # 뒤에서 별표가 붙으면 표준판례로 올린다 (④)
                if c["standard"]:
                    for e in cases:
                        if e["id"] == c["id"]:
                            e["standard"] = True
                continue
            seen.add(c["id"])
            cases.append(dict(c))
        for m in b.mnemonics:
            if m not in mnemonics:
                mnemonics.append(m)
        meta = b.meta or {}
        if meta.get("bonus_topic"):
            bonus.append(meta["bonus_topic"])
        if meta.get("outline"):
            outline = meta["outline"]
        if meta.get("exam_years"):
            years += [y for y in meta["exam_years"] if y not in years]
        if meta.get("sidenote") and not sidenote:
            sidenote = meta["sidenote"]
        if b.kind == "heading" and b.level >= 3:
            title = _plain(b.text)
            if title not in sections:
                sections.append(title)

    L = ["---"]
    L.append(f"source: {prof.get('label', prof['name'])}")
    L.append(f"chapter: {_q(part.chapter or part.title)}")
    if part.section:
        L.append(f"section: {_q(part.section)}")
    if sections:
        L.append("sections: [" + ", ".join(_q(s) for s in sections[:12]) + "]")
    if years:
        L.append("exam_years: [" + ", ".join(str(y) for y in years) + "]")
    if sidenote:
        L.append(f"sidenote: {_q(sidenote)}")
    if outline:
        L.append("outline: [" + ", ".join(_q(o) for o in outline) + "]")
    if cases:
        L.append("cases:")
        for c in cases:
            L.append(f"  - id: {_q(c['id'])}")
            if c.get("label"):
                L.append(f"    label: {_q(c['label'])}")
            L.append(f"    standard: {'true' if c.get('standard') else 'false'}")
    if bonus:
        L.append("bonus_topics: [" + ", ".join(_q(b) for b in bonus) + "]")
    if mnemonics:
        L.append("mnemonics: [" + ", ".join(_q(m) for m in mnemonics) + "]")
    L.append(f"converted: {_dt.date.today().isoformat()}")
    L.append(f"parser: {parser}")
    L.append(f"validation: {validation}")
    L.append("---")
    return "\n".join(L) + "\n\n"


def write(parts, out_dir, prof, parser, validation="PENDING",
          clean: bool = True) -> tuple[list[str], list[str]]:
    """분할 결과를 쓴다. (쓴 파일, 지운 옛 파일)

    쓰기 전에 이 폴더의 지난 결과물을 지운다. 실행마다 분할이 달라지면 옛
    파일이 남아 검증이 같은 내용을 두 번 센다. 별표가 4에서 8이 되고 각주
    정의가 통째로 중복돼 FAIL 이 난다.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    removed = []
    if clean:
        keep = {filename(p, prof) for p in parts}
        for old in sorted(out.glob("*.md")):
            if old.name in keep:
                continue
            if is_generated(old):
                old.unlink()
                removed.append(old.name)
    written = []
    for part in parts:
        path = out / filename(part, prof)
        path.write_text(front_matter(part, prof, parser, validation) + part.text(),
                        encoding="utf-8")
        written.append(str(path))
    return written, removed


def _plain(text: str) -> str:
    """헤딩 텍스트에서 마크업을 걷어낸 사람이 읽는 제목."""
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"[*=]{2}", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _topic(title: str) -> str:
    m = re.search(r"\[([^\]]+)\]", title)
    if m:
        return m.group(1).split("-")[0]
    return re.sub(r"^[A-Z]-\d+\.\s*", "", title)[:20]


def _q(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'
