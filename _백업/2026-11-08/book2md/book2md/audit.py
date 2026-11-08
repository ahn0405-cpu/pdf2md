"""절 제목 전수 점검 (`convert audit-sections`).

변환된 md 를 그대로 읽는다. **PDF 를 다시 돌리지 않는다.** 무엇을 고칠지
정하기 전에 몇 건인지부터 세기 위한 것이라, 고치지 않고 세기만 한다.

가짜 절 하나가 판례를 엉뚱한 목차 아래로 끌고 간다. 002 신의칙에서 `(D 의의`
가 진짜 `II. 내용` 절의 판례 12건을 가져갔다. 매핑을 아무리 잘해도 소스가
틀린 것이라, 이 점검이 매핑보다 앞선다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .crosscheck import _distance
from .model import is_generated

_FM = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.S)
_HEAD = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.*)$")
_OUTLINE_FM = re.compile(r"^outline: \[(?P<items>.*)\]$", re.M)
#: 본문에 남은 목차 띠. '==& 의의 - 소송물 - 중복소제기==' (§1.5 ①)
_BAND = re.compile(r"^==\s*[&◎@※＆⊙○●]?\s*(?P<items>[^=]+?)\s*==\s*$")
_BAND_SEP = re.compile(r"\s*[-–—>»/·+]\s*")
#: 제목에 있어서는 안 되는 글자. 한글·한자·영숫자·흔한 문장부호만 남긴다.
_JUNK_CHAR = re.compile(
    r"[^0-9A-Za-z가-힣㐀-鿿·\s.,()\[\]{}『』「」·•‧∙・\-–—~/:;'\"%\^\*=`_+]")
_DASH_RUN = re.compile(r"[-–—_=]{4,}")
#: 알아볼 수 있는 절 번호. 이런 번호가 붙어 있으면 목차 띠 없이도 절이다.
_NUMBERED = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[IVXivx]{1,5}|\d{1,3})\s*[.,·•‧∙・)\]]")
#: 목차 띠가 그대로 절 제목이 된 것. '◎ 의의-내용'
_BAND_HEAD = re.compile(r"^\s*[&◎@※＆⊙○●]\s*\S")


def similar(band_key: str, sec_key: str) -> bool:
    """목차 띠 항목과 절 제목이 같은 것을 가리키는가.

    완전 일치나 부분 문자열로는 못 만난다. 띠는 축약형이고 절은 완전형이다.

        띠 '협의소송자료'   ↔ 절 '협의의 소송자료 준별과 완화'
        띠 '본안신청'       ↔ 절 '본안의 신청'
        띠 '사해행위 법적평가' ↔ 절 '사해행위의 법률적 평가를 달리 주장'

    띠의 글자가 절 안에 **순서대로** 나오고 그 구간이 지나치게 벌어지지
    않으면 같은 것으로 본다. 첫 글자가 맞아야 한다고 걸면 절이 앞에 말을
    더 붙인 경우를 놓친다 — 띠 '형성권행사소멸' ↔ 절 'I. 소송상 형성권
    행사의 효력 소멸시 취급'. 그래서 시작 자리는 안 따지고 구간 길이로만 죈다.

    세 글자 이하는 순서만 보면 아무 데나 걸리므로('의의' 가 '소송물의 의미' 에)
    한 글자 차이까지만 본다.
    """
    if not band_key or not sec_key:
        return False
    if band_key in sec_key:
        return True
    # 띠가 절보다 길 때의 포함은 조금만 인정한다. '부진정 예비적 병합' 이
    # 'V. 예비적 병합' 까지 삼키면 진짜 절이 짝을 잃고 가짜로 몰린다.
    if sec_key in band_key and len(band_key) - len(sec_key) <= 2:
        return True
    if len(band_key) <= 3:
        head = sec_key[:len(band_key)]
        return bool(head) and _distance(band_key, head) <= 1
    j, first, last = 0, -1, -1
    for ch in band_key:
        j = sec_key.find(ch, j)
        if j < 0:
            return False
        if first < 0:
            first = j
        last = j
        j += 1
    return last - first + 1 <= len(band_key) * 2


def _key(text: str) -> str:
    """대조용 열쇠. validate._key 와 같은 규칙으로 양쪽을 똑같이 턴다."""
    text = re.sub(r"[=*`]+", "", text or "")
    text = re.sub(r"^[^가-힣]{0,6}", "", text)
    return re.sub(r"\s+", "", text).strip()


class Sec:
    """절 제목 하나."""

    def __init__(self, file: Path, line: int, level: int, title: str, band: int):
        self.file, self.line, self.level = file, line, level
        self.title = title
        self.band = band          # 이 절이 딸린 목차 띠의 번호 (-1 = 없음)
        self.key = _key(title)
        self.matched: str | None = None     # 짝지은 목차 항목
        self.dup = False                    # 그 항목을 이미 다른 절이 썼다

    @property
    def numbered(self) -> bool:
        """번호가 알아볼 수 있는 꼴인가.

        번호가 성한 절은 목차 띠 없이도 절이다. 목차 항목을 여러 절이 나눠
        가지는 것도 정상이다 — '요건-당사자 동일', '요건-소송물 동일'.
        가짜를 만드는 것은 **번호가 뭉개진 줄**이다.
        """
        return bool(_NUMBERED.match(self.title))

    @property
    def is_band(self) -> bool:
        """목차 띠 자체가 절 제목이 된 것인가. '◎ 의의-내용'"""
        if not _BAND_HEAD.match(self.title):
            return False
        items = [x for x in _BAND_SEP.split(_BAND_HEAD.sub("", self.title)) if x.strip()]
        return len(items) >= 2

    @property
    def junk(self) -> str:
        """제목에 섞인 잡글자. 비어 있으면 깨끗하다."""
        bad = "".join(sorted(set(_JUNK_CHAR.findall(self.title))))
        if _DASH_RUN.search(self.title):
            bad += " (줄표 반복)"
        return bad


def _bands(body: str, fm_lines: int, sec_level: int):
    """목차 띠와 절 제목을 본문에서 줄 번호와 함께 뽑는다.

    한 파일에 논점이 여럿 들어 있을 수 있어 프론트매터의 `outline` 하나로는
    부족하다. 본문의 띠를 순서대로 세어 절을 그 아래 묶는다.
    """
    bands: list[list[str]] = []
    secs: list[Sec] = []
    cur = -1
    for i, line in enumerate(body.splitlines(), start=fm_lines + 1):
        b = _BAND.match(line.strip())
        if b:
            items = [x.strip() for x in _BAND_SEP.split(b.group("items")) if x.strip()]
            if len(items) >= 2:
                bands.append(items)
                cur = len(bands) - 1
                continue
        h = _HEAD.match(line)
        if not h:
            continue
        level = len(h.group("hashes"))
        if level <= 3:
            cur = -1          # 논점이 바뀌면 띠도 바뀐다
            continue
        if level == sec_level:
            secs.append(Sec(Path(""), i, level, h.group("title").strip(), cur))
    return bands, secs


def scan(root, cfg: dict, sec_level: int = 4) -> dict:
    profs = cfg.get("profiles") or {}
    label = (profs.get("textbook") or {}).get("label", "기본서")
    files, all_secs, all_bands = [], [], {}
    for path in sorted(Path(root).rglob("*.md")):
        rel = path.relative_to(root).parts
        if any(p.startswith("_") for p in rel[:-1]) or not is_generated(path):
            continue
        text = path.read_text(encoding="utf-8")
        m = _FM.match(text)
        if not m:
            continue
        head, body = m.group("body"), text[m.end():]
        if re.search(r"^source:\s*(.+)$", head, re.M) is None:
            continue
        if re.search(r"^source:\s*(.+)$", head, re.M).group(1).strip().strip('"') != label:
            continue
        files.append(path)
        fm_lines = m.group(0).count("\n")
        bands, secs = _bands(body, fm_lines, sec_level)
        if not bands:
            om = _OUTLINE_FM.search(head)
            if om:
                bands = [[x.strip().strip('"') for x in om.group("items").split(",")
                          if x.strip()]]
                for s in secs:
                    s.band = 0
        for s in secs:
            s.file = path
        all_bands[path] = bands
        all_secs.extend(secs)

    # 절 ↔ 목차 항목 짝짓기. 띠 안에서 앞에서부터, 한 항목은 한 번만.
    by_file_band: dict = {}
    for s in all_secs:
        by_file_band.setdefault((s.file, s.band), []).append(s)
    unused: dict = {}
    for (path, bi), secs in by_file_band.items():
        if bi < 0 or bi >= len(all_bands.get(path, [])):
            continue
        items = all_bands[path][bi]
        taken: dict = {}
        # 긴 항목부터 본다. '부진정 예비적 병합' 이 있는데 '예비적 병합' 이
        # 먼저 걸리면 짝이 어긋나고, 뒤엣것이 가짜로 몰린다.
        ordered = sorted(items, key=lambda n: -len(_key(n)))
        for s in secs:
            for name in ordered:
                k = _key(name)
                if not k or not similar(k, s.key):
                    continue
                s.matched = name
                if k in taken:
                    s.dup = True
                else:
                    taken[k] = s
                break
        left = [n for n in items if _key(n) and _key(n) not in taken]
        if left:
            unused[(path, bi)] = left

    repeat = Counter(s.key for s in all_secs)
    return {"files": files, "sections": all_secs, "bands": all_bands,
            "unused": unused, "repeat": repeat, "root": Path(root)}


# ── 유형 판정 ────────────────────────────────────────────────────
def _near(band: list, key: str) -> str | None:
    """깨진 절 제목에 가장 가까운 목차 항목. 앞 글자가 얼마나 겹치나로 본다."""
    best, score = None, 0
    for name in band:
        k = _key(name)
        n = 0
        while n < min(len(k), len(key)) and k[n] == key[n]:
            n += 1
        if n >= 2 and n > score:
            best, score = name, n
    return best


def classify(data: dict, repeat_min: int = 3, book_words=()) -> dict:
    """가짜 절 후보를 유형별로 가른다. **고치지 않는다. 세기만 한다.**

    `repeat_min` 은 이제 판정에 쓰지 않는다. 리포트에 '같은 제목이 N곳에 있다'
    로 보여줄 뿐이다 — 반복은 정상 절의 성질이지 머리말의 표지가 아니다.
    """
    secs, repeat, bands = data["sections"], data["repeat"], data["bands"]
    words = tuple(w for w in book_words if w)
    out: dict = {"목차_띠가_절이_됨": [], "목차_두_번_씀": [], "머리말로_보임": [],
                 "잡글자_섞임": [], "목차에_없음": [], "띠가_없어_판정보류": [],
                 "목차에_있는데_절이_없음": []}
    for s in secs:
        if s.is_band:
            out["목차_띠가_절이_됨"].append(s)
            continue
        # 목차 항목을 여러 절이 나눠 가지는 것은 정상이다 —
        # '요건-당사자 동일', '요건-소송물 동일', '요건-권리보호이익'.
        # 번호가 뭉개진 줄이 뒤늦게 같은 항목을 집을 때만 가짜다.
        if s.dup and not s.numbered:
            out["목차_두_번_씀"].append(s)
            continue
        if s.dup:
            continue
        if s.matched is not None:
            if s.junk:
                out["잡글자_섞임"].append(s)
            continue
        # 목차에 대응이 없는 절. 먼저 **깨진 진짜 절**인지 본다 — 목차 띠에
        # 앞 글자가 겹치는 항목이 있으면 머리말일 리가 없다. 이 순서를
        # 뒤집으면 '고유필수적 공동소승인 추개■…' 이 머리말로 분류된다.
        # 책 제목이 들어 있으면 띠와 무관하게 머리말이다. 실측
        # 'VIII • 윤곽 민사소송법' 은 띠를 못 읽은 파일에 있어서, 띠 검사를
        # 먼저 하면 진짜 두 건이 판정보류로 새어 나간다.
        if any(w and w in s.title for w in words):
            out["머리말로_보임"].append(s)
            continue
        band = bands.get(s.file) or []
        if not (0 <= s.band < len(band)):
            # 목차 띠를 못 읽은 자리다. 근거가 없으니 판정하지 않는다.
            # 여기서 반복만 세면 'I. 의의 및 취지'(77곳) 가 머리말이 된다.
            out["띠가_없어_판정보류"].append(s)
            continue
        near = _near(band[s.band], s.key)
        if near:
            out["잡글자_섞임"].append(s)
            continue
        # 여러 논점에 되풀이되면 머리말이 절 규칙에 걸린 것이다. 반복만
        # 세면 안 된다 — 'I. 의의' 도 논점마다 나온다. 목차에 없다는
        # 조건이 함께 걸려야 걸러진다.
        # 반복 횟수는 판정에 쓰지 않는다. 'I. 의의 및 취지' 는 77곳에 있는데
        # 논점이 135개라 당연하다. 한 파일에 논점이 여럿이고 띠가 그중 하나만
        # 잡히면 나머지 논점의 정형 절이 전부 걸린다 (실측 108_109 의
        # 'I. 의의', 'II. 종류'). 책 제목으로만 가른다 — 위에서 이미 봤다.
        if s.junk:
            out["잡글자_섞임"].append(s)
        else:
            out["목차에_없음"].append(s)
    for (path, bi), left in sorted(data["unused"].items()):
        out["목차에_있는데_절이_없음"].append((path, bi, left))
    return out


def report(data: dict, kinds: dict, limit: int = 200) -> str:
    root = data["root"]

    def rel(p) -> str:
        try:
            return str(Path(p).relative_to(root))
        except Exception:
            return str(p)

    total = len(data["sections"])
    L = ["# 절 제목 전수 점검", "",
         f"기본서 md {len(data['files'])}개 · 절 제목 {total}개", "",
         "고치지 않았다. 무엇을 고칠지 정하기 전에 세기만 한 것이다.", ""]
    banded = sum(1 for f in data["files"] if data["bands"].get(f))
    no_band = sum(1 for s in data["sections"]
                  if not (0 <= s.band < len(data["bands"].get(s.file) or [])))
    L += [f"목차 띠를 읽은 파일 {banded}/{len(data['files'])}개 · "
          f"띠에 못 붙은 절 {no_band}/{total}개", "",
          "띠가 판정의 근거다. 띠가 없으면 무엇이 가짜인지 정할 수 없어 "
          "「띠가 없어 판정보류」로 뺀다.", "",
          "## 유형별 건수", "", "| 유형 | 건수 | 뜻 |", "|---|---:|---|"]
    tips = {
        "목차_띠가_절이_됨": "'◎ 의의-내용' 이 절 제목이 됐다. 띠가 사라져 그 뒤 판정이 전부 어긋난다",
        "목차_두_번_씀": "번호가 뭉개진 줄이 이미 쓰인 목차 항목을 또 집었다",
        "머리말로_보임": "목차에 없고 여러 논점에 되풀이된다. 러닝 헤더가 절 규칙에 걸린 것",
        "잡글자_섞임": "제목에 한글·한자가 아닌 글자가 섞였다. 진짜 절일 수 있다",
        "목차에_없음": "띠는 읽었는데 대응이 없다. 저자가 띠에 안 적었을 수도 있다",
        "띠가_없어_판정보류": "그 자리에 띠가 없다. 근거가 없어 판정하지 않았다",
        "목차에_있는데_절이_없음": "띠에 있는데 절이 안 섰다. 그 절이 문단에 묻혔다",
    }
    for k, tip in tips.items():
        L.append(f"| {k.replace('_', ' ')} | {len(kinds[k])} | {tip} |")
    L.append("")

    for k in ("목차_띠가_절이_됨", "목차_두_번_씀", "머리말로_보임",
              "잡글자_섞임", "목차에_없음", "띠가_없어_판정보류"):
        items = kinds[k]
        L += [f"## {k.replace('_', ' ')} — {len(items)}건", ""]
        if not items:
            L += ["없음", ""]
            continue
        for s in items[:limit]:
            band = data["bands"].get(s.file, [])
            names = band[s.band] if 0 <= s.band < len(band) else []
            L.append(f"- `{rel(s.file)}:{s.line}`")
            L.append(f"  - 절 제목: `{s.title}`")
            if s.matched:
                L.append(f"  - 목차 띠: `{s.matched}`")
            else:
                near = _near(names, s.key)
                if near:
                    L.append(f"  - 목차 띠(가장 가까운 것): `{near}`")
            if s.junk:
                L.append(f"  - 섞인 글자: `{s.junk}`")
            if data['repeat'][s.key] > 1:
                L.append(f"  - 같은 제목이 {data['repeat'][s.key]}곳에 있다")
        if len(items) > limit:
            L.append(f"- … 그리고 {len(items) - limit}건 더")
        L.append("")

    items = kinds["목차에_있는데_절이_없음"]
    L += [f"## 목차에 있는데 절이 없음 — {len(items)}건", ""]
    if not items:
        L += ["없음", ""]
    for path, bi, left in items[:limit]:
        L.append(f"- `{rel(path)}` (띠 {bi + 1}) — 절이 안 선 항목: "
                 + ", ".join(f"`{x}`" for x in left))
    if len(items) > limit:
        L.append(f"- … 그리고 {len(items) - limit}건 더")
    return "\n".join(L) + "\n"


# ── 묻힌 절과 놓친 띠 찾기 ────────────────────────────────────────
_LOOSE_BAND = re.compile(r"^\s*(?:==)?\s*[&◎@※＆⊙○●]?\s*(?P<items>.+?)\s*(?:==)?\s*$")


def find_buried(data: dict, head: int = 40, per_item: int = 3) -> list:
    """절이 안 선 목차 항목이 본문 어느 줄에 묻혀 있는지 찾는다.

    글자는 사라지지 않았다. 번호 자리가 뭉개져 헤딩으로만 안 잡힌 것이다
    (SKILL.md §1). 그러니 본문에서 제목 글자를 찾으면 자리를 짚을 수 있다.
    **고치지 않는다.** 어느 줄인지 알려줄 뿐이다.
    """
    out = []
    for (path, bi), items in sorted(data["unused"].items()):
        text = Path(path).read_text(encoding="utf-8")
        m = _FM.match(text)
        body, off = (text[m.end():], m.group(0).count("\n")) if m else (text, 0)
        lines = body.splitlines()
        for name in items:
            k = _key(name)
            if not k:
                continue
            hits = []
            for i, line in enumerate(lines, start=off + 1):
                s = line.strip()
                if not s or _HEAD.match(s) or _BAND.match(s):
                    continue
                if similar(k, _key(s[:head])):
                    hits.append((i, s[:100]))
                if len(hits) >= per_item:
                    break
            out.append((Path(path), bi, name, hits))
    return out


def find_bands(data: dict, cfg: dict, limit: int = 6) -> list:
    """띠를 못 읽은 파일에서 띠일 법한 줄을 찾는다.

    띠가 없는 것인지 우리가 못 읽은 것인지 가려야 한다. 띠는 이 점검과
    제목 복구와 검증 셋 모두의 근거라, 못 읽었다면 그것부터 고쳐야 한다.
    """
    ol = (cfg.get("legend") or {}).get("outline") or {}
    sep = ol.get("separator", r"[-–—>»/·+]")
    # _BAND_HEAD 는 표지 뒤 한 글자까지 물고 있어(판정용) 여기 쓰면 '개시' 가
    # '시' 가 된다. 자르는 데는 설정의 표지 규칙을 쓴다.
    lead = ol.get("lead_marker", r"^[&◎@※＆⊙○●\s]+")
    max_len = int(ol.get("max_item_len", 10))
    out = []
    for path in data["files"]:
        if data["bands"].get(path):
            continue
        text = Path(path).read_text(encoding="utf-8")
        m = _FM.match(text)
        body, off = (text[m.end():], m.group(0).count("\n")) if m else (text, 0)
        cands = []
        for i, line in enumerate(body.splitlines(), start=off + 1):
            s = re.sub(r"[=*`]+", "", line).strip()
            if not s or len(s) > 60 or _HEAD.match(line.strip()):
                continue
            if re.search(r"(?:[.?!]|다\.|음\.|함\.)\s*$", s):
                continue
            items = [t.strip() for t in re.split(sep, re.sub(lead, "", s))
                     if t.strip()]
            if len(items) < 2 or any(len(t) > max_len for t in items):
                continue
            cands.append((i, line.strip()[:100], items))
            if len(cands) >= limit:
                break
        out.append((path, cands))
    return out


def extra_report(data: dict, cfg: dict) -> str:
    root = data["root"]

    def rel(p):
        try:
            return str(Path(p).relative_to(root))
        except Exception:
            return str(p)

    buried = find_buried(data)
    L = ["", "## 묻힌 절은 어느 줄에 있나", "",
         "글자는 사라지지 않았다. 번호 자리가 뭉개져 헤딩으로만 안 잡힌 것이다.",
         "아래 줄을 원본과 견주어 무엇이 번호 자리를 망가뜨렸는지 보면 된다.", ""]
    for path, bi, name, hits in buried:
        L.append(f"- `{rel(path)}` (띠 {bi + 1}) — `{name}`")
        if not hits:
            L.append("  - 본문에서 못 찾았다. 정말 빠졌을 수 있다 — 원본 확인 필요")
        for i, s in hits:
            L.append(f"  - `:{i}` {s}")
    L += ["", "## 띠를 못 읽은 파일 — 띠일 법한 줄", "",
          "띠가 없는 것인지 우리가 못 읽은 것인지 가려야 한다. 띠는 제목 복구·",
          "검증·이 점검 셋 모두의 근거다.", ""]
    for path, cands in find_bands(data, cfg):
        L.append(f"- `{rel(path)}`")
        if not cands:
            L.append("  - 띠일 법한 줄이 없다. 저자가 안 적은 논점으로 보인다")
        for i, s, items in cands:
            L.append(f"  - `:{i}` {s}   → 토막 {len(items)}개")
    return "\n".join(L) + "\n"
