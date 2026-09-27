#!/usr/bin/env python3
"""단권화 노트에서 빈칸 채우기 암기노트를 뽑는다.

판시 원문(「② 판례의 태도」의 인용문)의 **BOLD 가 곧 빈칸**이다.
SKILL.md 가 BOLD 를 채점 키워드 단위로 10~15자 안에 끊게 한 까닭이 이것이다.
빈칸에는 BOLD 덩어리의 글자 수(공백 제외)만큼 ＿ 를 둔다.

장(CHAPTER) 단위로 묶어 `노트/암기노트/CH05_소송물.md` 처럼 쓴다.
장의 경계는 기본서 목차(CONTENTS)를 따른다 — 아래 「장」 표.

수록 기준은 `표준판례` 이거나 사례집 뱃지(`E-5`)가 붙은 판례다.
같은 판례가 같은 판시로 두 번 나오면 처음 것만 싣는다.

    python3 암기노트.py              노트가 있는 장 전부
    python3 암기노트.py 05 08        그 장만
    python3 암기노트.py 05 --화면    파일로 쓰지 않고 화면에
    python3 암기노트.py --전부       수록 기준을 끄고 모든 판례를
    python3 암기노트.py --검사       빈칸 없는 판시 · 15자 넘는 빈칸만 보고

형식 기준은 `작업/samples/암기노트_CH06_소송물.md` 다.
**만든 파일을 손으로 고치지 않는다.** 다시 뽑으면 덮어쓴다.
고칠 것이 있으면 단권화 노트를 고치고 다시 뽑는다.
"""
import re
import sys
from pathlib import Path

from 경로 import 기본서, 노트, 암기노트

# 기본서 목차(CONTENTS)의 장 — (번호, 제목, 첫 논점, 끝 논점)
장 = [
    ("01", "민사소송법 총론", 1, 2),
    ("02", "소송의 주체 — 법원", 3, 19),
    ("03", "소송의 주체 — 당사자", 20, 34),
    ("04", "소와 소송요건", 35, 44),
    ("05", "소송물", 45, 46),
    ("06", "소송절차 개시", 47, 49),
    ("07", "소송절차 개시의 효력", 50, 51),
    ("08", "변론", 52, 75),
    ("09", "자백과 자백간주", 76, 78),
    ("10", "경험칙과 현저한 사실", 79, 80),
    ("11", "증거", 81, 91),
    ("12", "법원의 판단", 92, 95),
    ("13", "소송의 종료", 96, 103),
    ("14", "판결의 효력", 104, 110),
    ("15", "사해행위취소소송", 111, 111),
    ("16", "병합소송", 112, 129),
    ("17", "상소", 130, 139),
    ("18", "재심", 140, 140),
]

_헤딩 = re.compile(r"^([>\s]*)(#{1,6})\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_사건 = re.compile(r"\d{2,4}\s?[가-힣]{1,3}\s?\d{1,6}")
_뱃지 = re.compile(r"`([A-Q]-\d+)`")
_두문자 = re.compile(r"`(\[[^\]`]+\])`")
_번호머리 = re.compile(r"^(?:[ivx]+\)|\d+\)|\(\d+\)|\d+\.(?:·\d+\.)*|[IVX]+\.|[①-⑳])\s*")
_일반절 = re.compile(r"^(?:判例|판례|학설|검토|문제점)$")
빈칸상한 = 15


def 깊이(l):
    return l[: len(l) - len(re.sub(r"^[>\s]*", "", l))].count(">")


def 벗김(l, n=None):
    """인용 접두사 `> ` 를 n 단(없으면 전부) 벗긴다."""
    for _ in range(깊이(l) if n is None else n):
        l = re.sub(r"^\s*>\s?", "", l, count=1)
    return l


def 다듬기(t):
    """각주 참조 · 주석 · 백틱 조각을 뗀다."""
    t = re.sub(r"<!--.*?-->", "", t)
    t = re.sub(r"\[\^\d+\]", "", t)
    return t.strip()


def 번호표(k):
    if k <= 10:
        return chr(0x2775 + k)          # ❶ … ❿
    if k <= 20:
        return chr(0x24EB + k - 11)     # ⓫ … ⓴
    return f"({k})"


# ── 노트 읽기 ─────────────────────────────────────────────


def 판례들(path):
    """노트에서 「② 판례의 태도」 하나마다 판례 하나를 뽑는다."""
    L = Path(path).read_text(encoding="utf-8").split("\n")
    헤딩 = []
    for i, l in enumerate(L):
        m = _헤딩.match(l)
        if m:
            헤딩.append((i, len(m.group(2)), 다듬기(m.group(3))))
    out = []
    for n, (i, lv, t) in enumerate(헤딩):
        if "② 판례의 태도" not in t:
            continue
        # 조상 헤딩 — 레벨이 줄어드는 것만 거슬러 올라간다
        조상 = []
        최소 = lv
        for j, lj, tj in reversed(헤딩[:n]):
            if lj < 최소:
                조상.append((j, lj, tj))
                최소 = lj
        if not 조상:
            continue
        사건헤딩 = 조상[0]
        셋째 = None                      # 같은 판례의 「③ 고득점 포인트」
        for h in 헤딩[n + 1:]:
            if h[1] < lv:
                break
            if h[1] == lv and h[2].startswith("③ 🎓"):
                셋째 = h
                break

        사건, 라벨 = 사건풀기(사건헤딩[2])
        # 뱃지는 사건 헤딩과 ① 사이에 있다
        머리 = " ".join(L[사건헤딩[0] + 1: i])
        머리 = 머리[: 머리.find("① 사건의 전말")] if "① 사건의 전말" in 머리 else 머리
        표준 = "`표준판례`" in 머리
        뱃지 = _뱃지.findall(머리)

        판시끝 = next((k for k in range(i + 1, len(L))
                    if _헤딩.match(L[k]) or "**판시 구조**" in L[k]), len(L))
        기준 = 깊이(L[i])
        판시 = [벗김(x, 기준 + 1) for x in L[i + 1: 판시끝] if 깊이(x) > 기준]
        판시 = 다듬기(re.sub(r"\n{3,}", "\n\n", "\n".join(판시)))

        두문자 = 풀이 = 구별 = None
        if 셋째:
            셋째끝 = next((h[0] for h in 헤딩 if h[0] > 셋째[0] and h[1] <= lv), len(L))
            블록 = [벗김(x) for x in L[셋째[0] + 1: 셋째끝]]
            요약 = 항목(블록, "한 줄 요약")
            if 요약:
                m = _두문자.search(요약)
                if m:
                    두문자 = m.group(1)
                    if "=" in 요약:
                        풀이 = 요약.split("=", 1)[1].strip()
            구별 = 첫문장(항목(블록, "구별 개념"))
        if not 두문자:
            m = _두문자.search(사건헤딩[2])
            두문자 = m.group(1) if m else None

        out.append({
            "사건": 사건, "쟁점": 쟁점짓기(조상, 라벨), "표준": 표준, "뱃지": 뱃지,
            "판시": 판시, "두문자": 두문자, "풀이": 풀이, "구별": 구별,
            "행": 사건헤딩[0] + 1,
        })
    return out


def 사건풀기(t):
    """`1) [청구확장 취지 명백히 표시] 91다43695` → ('91다43695', '청구확장 취지 명백히 표시')"""
    t = re.sub(r"`[^`]*`", "", t).replace("☑", "").strip()
    t = _번호머리.sub("", t)
    라벨 = [x.strip() for x in re.findall(r"\[([^\]]+)\]", t)]
    t = re.sub(r"\[[^\]]+\]", "", t).strip()
    조각 = [x.strip() for x in t.split(" — ") if x.strip()]
    사건 = next((x for x in 조각 if _사건.search(x)), 조각[0] if 조각 else t)
    라벨 += [x for x in 조각 if x is not 사건]
    return 사건, " · ".join(라벨)


def 쟁점짓기(조상, 라벨):
    """대절 이름 + 가장 가까운 라벨. ☑ 박스 안이면 ☑ 를 붙인다."""
    이름 = lambda t: _번호머리.sub("", re.sub(r"`[^`]*`", "", t).replace("☑", "")).strip()
    대절 = 이름(조상[-1][2])
    if not 라벨:
        for _, _, t in 조상[1:-1]:
            후보 = 이름(t)
            if 후보 and not _일반절.match(후보):
                라벨 = 후보
                break
    쟁점 = " · ".join([대절] + ([라벨] if 라벨 and 라벨 != 대절 else []))
    if any("☑" in t for _, _, t in 조상):
        쟁점 += " ☑"
    return 쟁점


def 항목(블록, 이름):
    """`- **이름**` 항목의 본문을 이어 붙여 돌려준다."""
    for k, l in enumerate(블록):
        if re.match(rf"^\s*-\s\*\*{이름}\*\*", l):
            글 = [re.sub(rf"^\s*-\s\*\*{이름}\*\*:?\s*", "", l)]
            for x in 블록[k + 1:]:
                if not x.strip() or re.match(r"^\s*-\s", x) or _헤딩.match(x):
                    break
                글.append(x.strip())
            return 다듬기(" ".join(글))
    return None


# 노트 안의 자리를 가리키는 말 — 암기노트는 번호가 달라 뜻이 통하지 않는다
_자리말 = re.compile(r"(?:^|[\s(「])(?:위|아래|앞|뒤)\s|거기|여기|이 판례만|만 쓰면|표가|세트|"
                   r"(?<![\d.])(?:\d+\)|\(\d+\)|\d+\.(?!\d)|[IVX]+[.의])|[ivx]+\)")


def 첫문장(t):
    """자리를 가리키지 않는 첫 문장. 없으면 None — ⚠️ 줄을 빼는 편이 낫다."""
    if not t:
        return None
    t = t.replace("⚠️", "").strip()
    문장 = re.findall(r".+?[다오]\.(?:\*\*)?(?=\s|$)|.+$", t)
    쓸만 = lambda x: (x and not _자리말.search(re.sub(r"\*\*", "", x))
                    and not re.match(r"(?:\*\*)?(?:그리고|그래서|또한|반면)", x) and len(x) <= 150)
    문장 = [x.strip() for x in 문장]
    for k, x in enumerate(문장):
        if not 쓸만(x):
            continue
        # 「정확히 외우십시오」처럼 짧은 머리면 무엇을 외우는지 다음 문장까지
        if len(x) < 40 and k + 1 < len(문장) and 쓸만(문장[k + 1]):
            x += " " + 문장[k + 1]
        return x
    return None


# ── 빈칸 만들기 ───────────────────────────────────────────


def 글자수(답):
    """빈칸의 길이 — 공백만 뺀다. 「심리·판단」은 다섯 칸."""
    return len(re.sub(r"\s", "", 답))


def 진단자수(답):
    """15자 상한을 잴 때의 자수 — 진단.py · 검사.py 와 같은 규칙."""
    return len(re.sub(r"[`\[\]()·,/…\s>\n]", "", 답))


def 빈칸(판시):
    """BOLD 를 ❶(＿＿) 로 바꾸고 정답 목록을 함께 돌려준다."""
    정답 = []

    def 바꿈(m):
        답 = re.sub(r"\s+", " ", m.group(1)).strip()
        정답.append(답)
        return f"{번호표(len(정답))}({'＿' * 글자수(답)})"

    return _BOLD.sub(바꿈, 판시), 정답


# ── 쓰기 ────────────────────────────────────────────────


def 논점정보(번호):
    """기본서 머리말의 논점 이름과 기출연도."""
    cands = sorted(기본서.glob(f"*_{번호}*.md"))
    if not cands:
        return None, []
    s = cands[0].read_text(encoding="utf-8")[:3000]
    m = re.search(r'^chapter:\s*"(.*)"', s, re.M)
    y = re.search(r"^exam_years:\s*\[(.*)\]", s, re.M)
    연도 = [x.strip() for x in y.group(1).split(",") if x.strip()] if y else []
    return (m.group(1) if m else None), 연도


def 논점쓰기(path, 전부):
    번호 = Path(path).name[:3]
    제목, 연도 = 논점정보(번호)
    제목 = 제목 or Path(path).stem.replace("_", " ")
    본것 = set()
    실을것 = []
    for p in 판례들(path):
        열쇠 = (p["사건"], re.sub(r"\s", "", p["판시"]))
        if 열쇠 in 본것 or not p["판시"]:
            continue
        본것.add(열쇠)
        if 전부 or p["표준"] or p["뱃지"]:
            실을것.append(p)
    if not 실을것:
        return None, []

    기출 = f" `기출 {', '.join(연도)}`" if 연도 else ""
    w = [f"# {제목}{기출}", "",
         "| # | 쟁점 | | 사례집 |", "|:--:|---|:--:|---|"]
    for k, p in enumerate(실을것, 1):
        w.append(f"| {k} | {p['쟁점']} | {'★' if p['표준'] else ''} | {' '.join(p['뱃지'])} |")
    w += ["", "★ 표준판례", "", "<br>", ""]

    답표 = []
    for k, p in enumerate(실을것, 1):
        꼬리 = "　".join(x for x in ("★" if p["표준"] else "", " ".join(p["뱃지"])) if x)
        w.append(f"### {k} · {p['쟁점']}" + (f"　　{꼬리}" if 꼬리 else ""))
        w.append("")
        글, 정답 = 빈칸(p["판시"])
        w.append(글)
        w.append("")
        if p["두문자"]:
            w.append(f"`{p['두문자']}`" + (f"　{p['풀이']}" if p["풀이"] else ""))
            w.append("")
        if p["구별"]:
            w.append(f"> ⚠️ {p['구별']}")
            w.append("")
        w += ["<br>", ""]
        p["정답"] = 정답
        답표.append(f"| {k} | {p['사건']} | "
                  + ("　".join(f"{번호표(i)} {d}" for i, d in enumerate(정답, 1)) or "— 통째로 외운다")
                  + " |")
    w += ["---", "", f"## {번호} 정답", "", "| # | 판례 | 정답 |", "|:--:|---|---|", *답표, "", "---", ""]
    return "\n".join(w), 실을것


머리말 = """판시 원문에서 채점 키워드를 뺀 것입니다. 빈칸의 길이가 글자 수(공백 제외)입니다.
정답은 각 논점 끝에 있습니다.

두문자는 그대로 두었습니다. 빈칸을 채울 때 실마리로 쓰십시오.

수록 기준 — **★ 표준판례** 이거나 **사례집 수록** 판례.

<!-- 암기노트.py 가 단권화 노트에서 뽑은 것이다. 손으로 고치지 말고 노트를 고친 뒤 다시 뽑는다. -->"""


def 장쓰기(번, 이름, 첫, 끝, 전부):
    노트들 = [p for p in sorted(노트.glob("*.md"))
            if p.name[:3].isdigit() and 첫 <= int(p.name[:3]) <= 끝]
    if not 노트들:
        return None, []
    있는 = {int(p.name[:3]) for p in 노트들}
    없는 = [f"{n:03d}" for n in range(첫, 끝 + 1) if n not in 있는]
    본문, 목록 = [], []
    for p in 노트들:
        글, 실음 = 논점쓰기(p, 전부)
        if 글:
            본문.append(글)
            목록 += [(p.name, x) for x in 실음]
    w = [f"# 암기노트 · CHAPTER {번} {이름}", "", 머리말, ""]
    if 없는:
        w += [f"아직 단권화 노트가 없어 빠진 논점: {' · '.join(없는)}", ""]
    w += ["---", ""]
    return "\n".join(w + 본문).rstrip("\n") + "\n", 목록


def main():
    인자 = sys.argv[1:]
    화면, 전부, 검사 = "--화면" in 인자, "--전부" in 인자, "--검사" in 인자
    고른 = [a for a in 인자 if not a.startswith("--")]
    대상 = [c for c in 장 if not 고른 or c[0] in 고른 or c[0].lstrip("0") in 고른]
    if 고른 and not 대상:
        sys.exit(f"그런 장이 없다: {' '.join(고른)} (01~18)")

    합 = [0, 0, 0]
    for 번, 이름, 첫, 끝 in 대상:
        글, 목록 = 장쓰기(번, 이름, 첫, 끝, 전부)
        if not 글:
            continue
        빈 = sum(len(x["정답"]) for _, x in 목록)
        합[0] += 1; 합[1] += len(목록); 합[2] += 빈
        if 검사:
            for 파일, x in 목록:
                if not x["정답"]:
                    print(f"  빈칸없음  {파일}:{x['행']}  {x['사건']}")
                for d in x["정답"]:
                    if 진단자수(d) > 빈칸상한:
                        print(f"  {진단자수(d):2}자     {파일}:{x['행']}  {x['사건']}  「{d}」")
            # ② 에 판시 인용이 없어 빠진 판례 (전원합의체처럼 판시를 다른 절에 둔 것)
            for p in sorted(노트.glob("*.md")):
                if 첫 <= int(p.name[:3]) <= 끝:
                    for x in 판례들(p):
                        if not x["판시"] and (전부 or x["표준"] or x["뱃지"]):
                            print(f"  판시없음  {p.name}:{x['행']}  {x['사건']}  (② 에 인용문이 없다)")
            continue
        if 화면:
            print(글)
            continue
        암기노트.mkdir(parents=True, exist_ok=True)
        out = 암기노트 / f"CH{번}_{re.sub(r'\s*—\s*', '-', 이름).replace(' ', '')}.md"
        out.write_text(글, encoding="utf-8", newline="\n")
        print(f"CH{번} {이름:14}  판례 {len(목록):3}  빈칸 {빈:4}  → {out.name}")
    if not 화면:
        print(f"\n합계  장 {합[0]}  판례 {합[1]}  빈칸 {합[2]}")


if __name__ == "__main__":
    main()
