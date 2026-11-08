#!/usr/bin/env python3
"""목차집(`노트/목차집/CH*.md`)의 논점을 쓸 재료를 한자리에 모으고, 쓴 것을 검사한다.

민소법 판(`민소법/작업/도구/목차재료.py`)과 같은 일을 하되, 특허법은 단권화 노트가 없으므로
**기본서 변환물을 직접** 읽는다. 작성 원칙은 `작업/references/목차집.md`.

    0 머리        장·번호·책쪽, 기출 회차, 윤곽 띠, 두문자, ⚠ 추록
    1 뼈대        기본서 절(N.) · 소절(==(N) …==) · 두문자 자리 · 判 개수
    2 의의        「의의」 절의 첫 문단 (기본서 원문)
    3 학설        학설·견해·검토가 나오는 문단 앞머리
    4 사례집      답안 목차에 논점 이름이 나오는 문제 — 제목·기출·설문 배점·걸린 목차, ⚠ 정오

사례집은 **문제 지문의 설문·배점과 답안 목차 제목만** 본다. 답안 본문은 읽지 않는다.

    python3 목차재료.py 011           재료 (순번)
    python3 목차재료.py 2-07          재료 (장-장내번호)
    python3 목차재료.py 2-07 --키 진보성 용이성   사례집을 찾을 낱말을 직접 준다
    python3 목차재료.py --문제 049 080-091    문제별 설문(배점)·답안 목차 전체 — 사례 줄 재료
    python3 목차재료.py --검사        목차집에 없는 논점 · 기본서에 없는 두문자
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 사례집, 목차집, references, 논점표, 찾기, 기본서파일, 상대

_헤딩 = re.compile(r"^(#{1,6})\s+(.*)$")
_소절 = re.compile(r"==\s*\(\s*(\d+)\s*\)\s*([^=]{1,50}?)\s*==")
_항목 = re.compile(r"^(\d)\s*\)\s*([^.。]{1,40}?)(?:\s+[i①-⑳@®©判]|$)")
_두문자 = re.compile(r"`\[([^\]`]{2,20})\]`")
_기출 = re.compile(r"(\d{2})\s*회")
_띠 = re.compile(r"1\.\s*의의[^#\n]{0,160}")
_배점 = re.compile(r"\((\d+)\s*점\)")


def 본문(p):
    s = Path(p).read_text(encoding="utf-8")
    return s.split("\n---\n", 1)[1] if s.startswith("---\n") else s


def 앞말(s):
    m = re.search(r"^---\n(.*?)\n---\n", Path(s).read_text(encoding="utf-8"), re.S)
    return m.group(1) if m else ""


def 맨글(t):
    return re.sub(r"==|\*\*|`", "", t)


# ── 0 머리 ──────────────────────────────────────────────────────
def 정오표(이름):
    """references/정오.md 의 표 하나 → 행 목록(칸 목록)."""
    s = (references / "정오.md").read_text(encoding="utf-8")
    sec = s.split(f"## {이름}", 1)[1].split("\n## ", 1)[0]
    return [[c.strip() for c in l.strip("|").split("|")]
            for l in sec.splitlines() if l.startswith("| ") and not l.startswith("| 책쪽")
            and not l.startswith("| 문제")]


def 머리(행, L):
    print(f"CHAPTER {int(행['장'])} {행['장제목']} · {행['장내번호']} {행['논점']}"
          f"   (순번 {행['순번']}, 책 {행['책쪽']}쪽, PDF {행['PDF시작']}-{행['PDF끝']})")
    첫 = 맨글(" ".join(L[:6]))
    회 = _기출.findall(첫[:200])
    if 회:
        print(f"기출   {'·'.join(회)}회")
    m = _띠.search(첫)
    if m:
        print(f"윤곽   {m.group(0).strip()}")
    for r in 정오표("기본서 9판 1차 추록"):
        if r[1] == 행["순번"]:
            print(f"⚠ 추록  p.{r[0]} — {r[3]}  (추록 {r[4]}쪽)")


# ── 1 뼈대 ──────────────────────────────────────────────────────
def 뼈대(L):
    판 = 0
    for l in L:
        m = _헤딩.match(l)
        if m:
            if 판:
                print(f"      (判 {판})")
            판 = 0
            lv = len(m.group(1))
            if lv >= 4:
                print(맨글(m.group(2)).strip())
            continue
        if l.startswith("[^"):
            continue                        # 각주는 뼈대가 아니다
        판 += l.count("判")
        for n, t in _소절.findall(l):
            print(f"  ({n}) {t.strip()}")
        mm = _항목.match(맨글(l).strip())
        if mm:
            print(f"      {mm.group(1)}) {mm.group(2).strip()}")
        for d in _두문자.findall(l):
            print(f"        [{d}]")
    if 판:
        print(f"      (判 {판})")


# ── 2 의의 · 3 학설 ──────────────────────────────────────────────
def 의의(L):
    for i, l in enumerate(L):
        m = _헤딩.match(l)
        if not (m and "의의" in m.group(2)):
            continue
        절 = []
        for x in L[i + 1:]:
            if _헤딩.match(x):
                break
            if x.strip() and not x.startswith("[^"):
                절.append(맨글(x).strip())
        print(f"[{맨글(m.group(2)).strip()}]")
        print("  " + " ".join(절)[:400])
        return
    print("(의의 절 없음)")


def 학설(L):
    본것 = 0
    for i, l in enumerate(L):
        if l.startswith("[^"):
            continue
        t = 맨글(l)
        for 낱말 in ("학설", "견해", "검토", "생각건대"):
            k = t.find(낱말)
            if k >= 0:
                print(f"[{i + 1}행 {낱말}] {t[max(0, k - 10):k + 160].strip()}")
                본것 += 1
                break
    if not 본것:
        print("(학설·검토 없음)")


# ── 4 사례집 ────────────────────────────────────────────────────
def 키(행, 더):
    """논점 이름에서 괄호(조문)를 뗀 것. 공백은 무시하고 맞춘다."""
    base = re.sub(r"\(.*?\)", "", 행["논점"]).replace("제도", "").strip()
    keys = [base] + list(더)
    return [re.sub(r"\s", "", k) for k in keys if k.strip()]


def 문제들():
    """사례집 문제마다 (번호, 제목, 기출, 설문[(번호, 배점)], 답안 목차[(수준, 제목)])."""
    out = []
    for p in sorted(사례집.glob("[0-9][0-9][0-9]_*.md")):
        if p.name.startswith("000_"):
            continue
        L = 본문(p).split("\n")
        번호 = p.name[:3]
        제목 = next((re.sub(r"^\d{3}\.\s*", "", 맨글(x[3:]).strip())
                    for x in L if x.startswith("## ")), "")
        기출 = next((m.group(1) for x in L[:6] for m in [re.search(r"기출\s*\((\d+)\)", x)] if m), "")
        설문, 목차, 답안 = [], [], False
        for x in L:
            t = 맨글(x).strip()
            if t.startswith("답안"):
                답안 = True
                continue
            if not 답안:
                m = re.match(r"^>\s*\(\s*(\d+)\s*\)", x)
                b = _배점.findall(x)
                if m and b:
                    설문.append((m.group(1), b[-1]))
                elif x.startswith(">") and b and not 설문:
                    설문.append(("", b[-1]))
                continue
            m = _헤딩.match(x)
            if m and len(m.group(1)) >= 3:
                목차.append((len(m.group(1)), 맨글(m.group(2)).strip()))
            elif re.match(r"^\d{1,2}\s*\.\s*\S", t) and len(t) <= 45:
                목차.append((4, t))          # 길어서 헤딩이 못 된 'N. …' 목차
        out.append((번호, 제목, 기출, 설문, 목차))
    return out


def 사례(행, 더):
    keys = 키(행, 더)
    정오 = {r[0]: r[1] for r in 정오표("사례집 5판 정오표")}
    찾음 = 0
    for 번호, 제목, 기출, 설문, 목차 in 문제들():
        걸림 = [i for i, (_, t) in enumerate(목차)
                if any(k in re.sub(r"\s", "", t) for k in keys)]
        if not 걸림:
            continue
        찾음 += 1
        배점 = " ".join(f"({n}){b}" if n else f"{b}점" for n, b in 설문)
        print(f"\n{번호} {제목}" + (f"  기출 {기출}회" if 기출 else "") + f"  [{배점}]")
        if 번호 in 정오:
            print(f"   ⚠ 정오 — {정오[번호]}")
        for i in 걸림:
            # 걸린 목차의 설문(### I. 설문(1)…)을 함께 보인다
            위 = next((t for lv, t in reversed(목차[:i]) if lv == 3), "")
            print(f"   {위 + ' > ' if 위 else ''}{목차[i][1]}")
    if not 찾음:
        print(f"(답안 목차에 {' / '.join(keys)} 가 나오는 문제 없음 — --키 로 낱말을 더 줄 것)")


def 본다(행, 더):
    p = 기본서파일(행)
    L = 본문(p).split("\n")
    print(f"\n{'━' * 60}\n{상대(p)}\n{'━' * 60}")
    print("\n── 0 머리")
    머리(행, L)
    m = re.search(r"^mnemonics:\s*(.*)$", 앞말(p), re.M)
    if m:
        print(f"두문자 {m.group(1)}")
    print("\n── 1 뼈대 (절 · (소절) · N) 항목 · [두문자] · 判 개수)")
    뼈대(L)
    print("\n── 2 의의")
    의의(L)
    print("\n── 3 학설·검토")
    학설(L)
    print(f"\n── 4 사례집 (답안 목차에 {' / '.join(키(행, 더))})")
    사례(행, 더)


def 문제덤프(인자들):
    """문제마다 설문(배점)과 답안 목차 전체 — 사례 줄을 쓸 재료. '049' '080-091' 꼴."""
    번호 = []
    for a in 인자들:
        m = re.fullmatch(r"(\d{1,3})-(\d{1,3})", a)
        번호 += ([f"{n:03d}" for n in range(int(m.group(1)), int(m.group(2)) + 1)] if m
                else [f"{int(a):03d}"])
    정오 = {r[0]: r[1] for r in 정오표("사례집 5판 정오표")}
    for p in sorted(사례집.glob("[0-9][0-9][0-9]_*.md")):
        if p.name[:3] not in 번호:
            continue
        L = 본문(p).split("\n")
        print("=" * 60)
        print(f"{상대(p)}")
        for x in L[:5]:
            if x.strip() and not x.startswith("## ") and not x.startswith("**문제"):
                print("   " + 맨글(x)[:70])
        if p.name[:3] in 정오:
            print(f"   ⚠ 정오 — {정오[p.name[:3]]}")
        답안 = False
        for x in L:
            t = 맨글(x).strip()
            if t.startswith("답안"):
                답안 = True
                continue
            if not 답안:
                if x.startswith(">") and (re.match(r"^>\s*\(\s*\d", x) or _배점.search(x)):
                    print("  Q " + t[1:].strip()[-150:])
                continue
            m = _헤딩.match(x)
            if m and len(m.group(1)) >= 3:
                print("  " + "  " * (len(m.group(1)) - 3) + 맨글(m.group(2)).strip()[:70])
            elif re.match(r"^\d{1,2}\s*\.\s*\S", t) and len(t) <= 45:
                print("    " + t)


# ── 검사 ────────────────────────────────────────────────────────
def 검사():
    """장 파일마다 — 아직 없는 논점, 기본서에 없는 두문자(오기를 잡는다)."""
    표 = 논점표()
    확인 = set()                            # 원본 쪽으로 확인한 두문자 (references/두문자확인.md)
    for l in (references / "두문자확인.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*(\d+-\d+)\s*\|\s*(\[[^\]]+\])", l)
        if m:
            확인.add((m.group(1), m.group(2)))
    없음 = 쓴수 = 0
    for p in sorted(목차집.glob("CH*.md")):
        장 = int(re.match(r"CH(\d+)", p.name).group(1))
        조각 = re.split(r"^# (\d{2})\s", p.read_text(encoding="utf-8"), flags=re.M)
        쓴것 = dict(zip(조각[1::2], 조각[2::2]))
        for r in [r for r in 표 if int(r["장"]) == 장]:
            if r["장내번호"] not in 쓴것:
                print(f"  없음     {장}-{r['장내번호']} {r['논점']}  ({p.name})")
                없음 += 1
                continue
            쓴수 += 1
            # 기본서는 두문자를 점으로 찍는다('[필.허.기]'). 점·공백·강조를 걷고 맞춘다.
            # OCR 로 깨진 두문자('[법실남.소태]')는 여기 걸린다 — 원본 쪽으로 확인한 것이면 둔다.
            원문 = re.sub(r"[\s=`.·]", "", 본문(기본서파일(r)))
            for d in re.findall(r"`(\[[^\]`]+\])`", 쓴것[r["장내번호"]]):
                if (f"{장}-{r['장내번호']}", d) in 확인:
                    continue
                if re.sub(r"[\s.·]", "", d) not in 원문:
                    print(f"  두문자?  {장}-{r['장내번호']}  {d}  ({p.name} — 기본서에 없다)")
    print(f"\n목차집 논점 {쓴수}  ·  쓴 장 안에서 아직 없음 {없음}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--검사" in args:
        검사()
        sys.exit()
    if "--문제" in args:
        문제덤프(args[args.index("--문제") + 1:])
        sys.exit()
    더 = []
    if "--키" in args:
        k = args.index("--키")
        더, args = args[k + 1:], args[:k]
    if not args:
        sys.exit(__doc__)
    for a in args:
        본다(찾기(a), 더)
