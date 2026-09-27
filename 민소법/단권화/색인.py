#!/usr/bin/env python3
"""사례집 색인 — 뱃지를 달기 전에 먼저 돌린다 (SKILL.md §입력).

노트를 쓰다가 찾으면 빠뜨린다. 그래서 먼저 표를 만든다.

대조는 3단계다. 사례집은 판시를 요지로 압축해 실어 사건번호를 거의 쓰지
않으므로(실측 303문제 중 28문제만) 사건번호만으로는 색인이 거의 빈다.

    1 사건번호   가장 확실하나 드물다
    2 두문자     판례에 붙어 있으므로 사건번호와 같은 근거다
    3 답안 목차   1·2 가 **그 판례에 하나도 없을 때만** 내려간다

3단계를 판례마다 무르게 쓰면 뱃지가 뭉개진다. 절 이름으로 맞추는 것이라
그 절의 판례가 그 문제 전부에 붙기 때문이다. 실측으로 84다552 가 여섯 문제에
붙었다. 1·2 로 어디든 붙은 판례는 3단계로 내려가지 않는다.

    python3 색인.py ../출력/기본서/45_046일부청구.md
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
사례집 = HERE.parent / "출력" / "사례집"

_문제 = re.compile(r"^##\s+([A-Z]-\d+)\.")
_헤딩 = re.compile(r"^###+\s+(.*)$")
_사건 = re.compile(r"(?<!\d)((?:19|20)?\d{2})\s*(다카|나카|가카|다|카|그|초|오|므|두|누|마)\s*(\d+)")
_두문자 = re.compile(r"[\[【]([가-힣][가-힣 ]{1,9})[\]】]")
_마크업 = re.compile(r"(?:==|\*\*|`)")


def 사례집색인() -> dict:
    db = {}
    for p in sorted(사례집.glob("*.md")):
        cur = None
        for line in p.read_text(encoding="utf-8").splitlines():
            m = _문제.match(_마크업.sub("", line))
            if m:
                cur = m.group(1)
                db[cur] = {"파일": p.name, "제목": m.string[m.end():].strip(),
                           "사건": set(), "두문자": set(), "목차": []}
                continue
            if not cur:
                continue
            h = _헤딩.match(line)
            if h:
                db[cur]["목차"].append(_마크업.sub("", h.group(1)).strip())
            for c in _사건.finditer(line):
                db[cur]["사건"].add("".join(c.groups()))
            for c in _두문자.finditer(line):
                t = c.group(1).strip()
                if 2 <= len(t.replace(" ", "")) <= 8:
                    db[cur]["두문자"].add(t)
    return db


def 기본서읽기(path: Path):
    """판례마다 (그 판례가 선 절, 그 판례에 걸린 두문자) 를 모은다.

    두문자는 판례 **바로 앞 줄**의 항목 머리에 붙는다.

        **3. 判例 `[일외별명일]`**

        치료비청구를 하면서 … 한정된다(84다552).

    그래서 줄 단위로 보면 하나도 안 걸린다. 절 안에서 마지막으로 본 두문자를
    이어 들고 가다가 사건번호를 만나면 물려준다. 새 항목 머리가 나오면 갈아
    끼우고, 절이 바뀌면 버린다.
    """
    text = path.read_text(encoding="utf-8")
    fm = text[: text.index("\n---\n", 4)]
    cases = re.findall(r'- id: "([^"]+)"', fm)
    body = text[text.index("\n---\n", 4) + 5:]
    절, 들고감, 표, 물린수 = None, set(), {}, {}
    for line in body.splitlines():
        plain = _마크업.sub("", line)
        if re.match(r"^\[\^\d+\]:", plain):
            # 각주 줄. 여기 나오는 사건번호에 앞 항목의 두문자를 물리면 안 된다.
            # 실측 각주 257 의 76다1313 이 항목 8 의 '부원공 어패다기' 를 받았다.
            continue
        h = re.match(r"^#{4}\s+(.*)$", line)
        if h:
            절 = re.sub(r"\[\^\d+\]|`[^`]*`|==", "", h.group(1)).strip()
            들고감 = set()
        mns = {m.group(1).strip() for m in _두문자.finditer(line)
               if 2 <= len(m.group(1).strip().replace(" ", "")) <= 8}
        # 항목 머리('3. 判例', '(1) 원칙', '> ### ☑ …')에 붙은 두문자를 갈아 끼운다
        머리 = re.match(r"^\s*(?:>\s*)?(?:#+\s*)?(?:\*\*)?\s*(?:\(\d\)|\d+\.|[ivx]+\))", plain)
        if mns and 머리:
            들고감 = mns
        found = [c for c in cases if c.replace(" ", "") in plain.replace(" ", "")]
        for c in found:
            e = 표.setdefault(c, {"절": 절, "두문자": set(), "물림": set()})
            e["두문자"] |= mns                      # 같은 줄 = 그 판례의 것
            if not mns:
                e["물림"] |= 들고감                  # 항목 머리에서 물려받은 것
                물린수[frozenset(들고감)] = 물린수.get(frozenset(들고감), 0) + 1

    # 물려받은 두문자는 그 항목에 판례가 하나뿐일 때만 그 판례의 것으로 본다.
    # 여럿이 나눠 가지면 개별 판례를 못 가른다 — 실측 '(2) … [종확나시]' 아래
    # 1) 2) 3) 이 전부 같은 뱃지를 달게 된다.
    for e in 표.values():
        if e["물림"] and 물린수.get(frozenset(e["물림"]), 0) == 1:
            e["두문자"] |= e["물림"]
    return cases, 표


def 근거(표: dict, db: dict, 논점: str = "") -> dict:
    """세 근거를 **따로** 모아 돌려준다. 판정은 하지 않는다.

    한때 이 함수가 판정까지 했는데, 두문자가 그룹 전체에 걸리는 자리(실측
    '(2) … [종확나시]' 아래 1) 2) 3))에서 개별 판례를 못 갈라 뱃지가 뭉갰다.
    조이면 이번에는 84다552 가 통째로 빠졌다. 자동으로 가를 수 있는 자리가
    아니다. 근거를 늘어놓고 사람이 고른다.
    """
    # 3단계(목차)는 절 이름으로 맞추는 것이라 사례집 전체를 훑으면 넓게 걸린다.
    # 실측 '소송물' 이 303문제 중 26문제에 걸렸다. 먼저 **논점 이름이 문제
    # 제목에 든 문제**로 좁힌다. 그 논점을 다루는 문제라야 그 절의 판례가
    # 나올 수 있기 때문이다.
    같은논점 = {pid for pid, v in db.items()
              if 논점 and 논점 in re.sub(r"[\s\[\]`]", "", v["제목"])}
    out = {}
    for cid, e in 표.items():
        키 = re.sub(r"^[IVX]+\.\s*", "", e["절"] or "")
        키 = re.sub(r"\[\^\d+\]|\s*\([^)]*\)\s*$", "", 키).strip()
        r = {"사건번호": [], "두문자": [], "물림": [], "목차": []}
        for pid, v in db.items():
            if cid in v["사건"]:
                r["사건번호"].append(pid)
            공유 = e["두문자"] & v["두문자"]
            if 공유:
                r["두문자"].append(f"{pid}({'·'.join(sorted(공유))})")
            물 = e.get("물림", set()) & v["두문자"]
            if 물 and not 공유:
                r["물림"].append(f"{pid}({'·'.join(sorted(물))})")
            if (pid in 같은논점 and 키 and len(키) >= 2
                    and 키 in " / ".join(v["목차"])):
                r["목차"].append(pid)
        out[cid] = r
    return out


def main() -> int:
    db = 사례집색인()
    if len(sys.argv) < 2:
        print(f"사례집 문제 {len(db)}개 "
              f"(사건번호 {sum(1 for v in db.values() if v['사건'])} · "
              f"두문자 {sum(1 for v in db.values() if v['두문자'])})")
        return 0
    src = Path(sys.argv[1])
    cases, 표 = 기본서읽기(src)
    논점 = re.sub(r"[\s\d]", "", re.search(r'^chapter: "(.*)"',
                 src.read_text(encoding="utf-8"), re.M).group(1))
    got = 근거(표, db, 논점)
    print(f"논점 이름 「{논점}」 으로 3단계 후보를 좁힌다\n")
    print(f"# {src.name}   사례집 문제 {len(db)}개와 대조\n")
    for c in cases:
        e, r = 표.get(c, {"절": "?"}), got.get(c, {})
        print(f"{c}   〔{e.get('절') or '?'}〕")
        for k in ("사건번호", "두문자", "물림", "목차"):
            v = r.get(k) or []
            꼬리 = "  ← 그룹에서 물려받음. 개별 판례를 못 가른다" if k == "물림" and v else ""
            print(f"    {k:5} {', '.join(v) if v else '—'}{꼬리}")
    print("\n1 사건번호 · 2 두문자 는 그대로 근거가 된다.")
    print("3 목차 는 1·2 가 하나도 없을 때만 쓴다. 절 단위라 넓게 걸린다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
