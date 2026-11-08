#!/usr/bin/env python3
"""도쓰 암기장·자료(22년, 옛 판)를 9판(2026)과 견줘 **고칠 곳 후보**를 논점마다 모은다 → 갱신의 할 일 목록.

도쓰 두문자 상당수는 도쓰가 직접 만든 것이라 9판 기본서에 없다 — 「없음」은 틀렸다는 뜻이 아니다.
그래서 두문자 일치만 보지 않고, 논점마다 아래를 한자리에 놓는다. 판단은 사람이(또는 Claude 가) 9판 원문을 보고 한다.

    ① 9판 자리     도쓰대응.tsv 로 짝지은 9판 논점과 목차집(9판 요약)의 행 — 여기를 열어 견준다
    ② ⚠ 추록       정오.md 의 9판 1차 추록 줄
    ③ 개정 낱말     특허청 · 근로자의 날 · 3배 · 수출 · 개정법 … 이 든 도쓰 줄 (법 개정·조문 이동 후보)
    ④ 두문자        도쓰 두문자가 9판(기본서·목차집·두문자확인)에 있나 — 같음 / 비슷(한 글자 다름) / 없음
    ⑤ 9판에만       짝지은 목차집 논점의 두문자 가운데 도쓰 어디에도 없는 것 (넣을지 사용자가 고른다)

    python3 도쓰대조.py                 장 전부 → references/도쓰대조.md 로 쓴다
    python3 도쓰대조.py 제6장           그 장만 화면에
    python3 도쓰대조.py --요약          장마다 개수만

고친 뒤 다시 돌려 남은 것이 「그대로 둠」 이유와 함께 references/도쓰갱신.md 에 적혀 있는지 본다.
"""
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 기본서, 목차집, references, 암기장, 자료, 상대

대응표 = references / "도쓰대응.tsv"
보고서 = references / "도쓰대조.md"

# 법 개정·용어 변경 후보 — 9판 추록·기본서에서 바뀐 것. 늘리면 여기에 더한다.
개정낱말 = [
    (r"특허청", "2025. 10. 1. 시행 — 지식재산처(장)"),
    (r"근로자의\s*날", "2025. 11. 1. 시행 — 노동절(제14조 제4호)"),
    (r"3배|징벌", "2024. 8. 21. 이후 위반행위 — 배상 한도 5배(128⑧)"),
    (r"수출", "2025. 7. 22. 시행 — 실시 태양에 수출 포함 논의(간접침해 추록)"),
    (r"개정법|시행\s*개정|구법", "개정 시점 표기 — 9판 기준으로 여전히 맞나"),
    (r"의견서\s*제출기간|2개월", "시행규칙 — 의견서 제출기간 2개월 → 4개월(추록)"),
    (r"특허법원\s*判|특判|지방判|서울고법判", "하급심 — 그 뒤 대법원 판례가 나왔나"),
]

_논점 = re.compile(r"^## <([^>]+)>")
_굵은괄호 = re.compile(r"\*\*(\([^*]+\))\*\*")
_괄호 = re.compile(r"\(([가-힣0-9+]{2,}(?:/[가-힣0-9+]+)*)\)")
_멈춤 = {"충돌", "공용성", "전용성", "판단대상", "반대견해有", "判例", "선결", "본수", "검토"}
_구판두문자 = re.compile(r"`\[([^\]`]{2,30})\]`|==\[?([가-힣/]{2,20})\]?==|\[([가-힣]{2,12}(?:/[가-힣]{1,12})*)\]")


def 정규(이름):
    return re.sub(r"\s|判例|判|특허|를|의", "", 이름)


_별칭 = {"무효심판": "특허무효심판", "심결취소소송심리": "심결취소소송소송물및심리"}


def 대응():
    """(장, 정규 논점) → (9판 번호들, 메모)"""
    out = {}
    with open(대응표, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            번호 = [x.strip() for x in (r["9판"] or "").split("·") if x.strip()]
            out[(r["도쓰장"], 정규(r["도쓰논점"]))] = (번호, r.get("메모") or "")
    return out


def 묶음(글자):
    """두문자 → 무리 목록. (약속의용/용시) → ['약속의용', '용시']"""
    return [g for g in re.split(r"[/\s]", re.sub(r"[()\[\]`=+]", "", 글자)) if len(g) >= 2]


def 도쓰읽기():
    """→ {(장, 정규논점): {'이름', '암기장', '자료': [(행, 글)], }}  (머리)는 첫 논점 앞."""
    논점들 = {}
    for 종류, 폴더 in (("암기장", 암기장), ("자료", 자료)):
        for p in sorted(폴더.glob("*.md")):
            장 = p.stem
            지금 = "(머리)"
            시작 = False
            for k, l in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
                if l.startswith("<!--") or (not 시작 and not l.startswith(("##", "**", "-", "[", "1.", "{")) and k < 8):
                    continue
                m = _논점.match(l)
                if m:
                    지금 = m.group(1).strip()
                    시작 = True
                키 = 정규(지금)
                키 = _별칭.get(키, 키)
                d = 논점들.setdefault((장, 키), {"이름": 지금, "암기장": [], "자료": [], "파일": {}})
                d[종류].append((k, l))
                d["파일"][종류] = p
    return 논점들


def 두문자들(줄들):
    s = set()
    for _, l in 줄들:
        for m in _굵은괄호.finditer(l):
            for g in re.findall(r"\(([^()]+)\)", m.group(1)):
                s.add(g.strip())
        for m in _괄호.finditer(l):
            g = m.group(1)
            if g not in _멈춤 and not g.isdigit() and ("/" in g or len(g) >= 3):
                s.add(g)
    return s


def 구판두문자():
    """9판 두문자 무리 집합 — 기본서 변환물 · 목차집 · 두문자확인."""
    무리 = set()
    for p in list(기본서.glob("*.md")) + list(목차집.glob("CH*.md")) + [references / "두문자확인.md"]:
        for m in _구판두문자.finditer(p.read_text(encoding="utf-8")):
            for g in 묶음(next(x for x in m.groups() if x)):
                if re.fullmatch(r"[가-힣0-9]+", g):    # OCR 찌꺼기(「용.」「기,」)는 뺀다
                    무리.add(g)
    return 무리


def 비슷(a, b):
    """3글자 이상에서 한 글자만 다르거나, 한쪽이 다른 쪽을 품고 길이 차이가 2 이하(「약만발상」↔「약만발상명」)."""
    if a == b or min(len(a), len(b)) < 3:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    짧, 긴 = sorted((a, b), key=len)
    return len(긴) - len(짧) <= 2 and 짧 in 긴


def 목차집자리(번호):
    """'6-01' → (파일, 행, 제목, 그 논점의 두문자 무리)"""
    장, 번 = 번호.split("-")
    f = next(iter(sorted(목차집.glob(f"CH{int(장):02d}_*.md"))), None)
    if not f:
        return None
    L = f.read_text(encoding="utf-8").split("\n")
    for i, l in enumerate(L):
        if re.match(rf"^# {int(번):02d} ", l):
            j = next((k for k in range(i + 1, len(L)) if re.match(r"^# \d\d ", L[k])), len(L))
            무리 = set()
            for m in re.finditer(r"`\[([^\]`]+)\]`", "\n".join(L[i:j])):
                무리.update(묶음(m.group(1)))
            return f, i + 1, re.sub(r"\s*`.*$", "", l[2:]), 무리
    return None


def 추록줄(번호):
    s = (references / "정오.md").read_text(encoding="utf-8")
    sec = s.split("## 기본서 9판 1차 추록", 1)[1].split("\n## ", 1)[0]
    장, 번 = 번호.split("-")
    키 = f"{int(장)}-{int(번):02d}"
    return [l for l in sec.splitlines() if l.startswith("| ") and f"| {키} " in l]


def 보고(장고름=None):
    표 = 대응()
    도쓰 = 도쓰읽기()
    구판 = 구판두문자()
    도쓰무리 = set()
    for d in 도쓰.values():
        for g in 두문자들(d["암기장"] + d["자료"]):
            도쓰무리.update(묶음(g))
    out, 요약 = [], {}
    for (장, 키), d in 도쓰.items():
        if 장고름 and not 장.startswith(장고름):
            continue
        번호, 메모 = 표.get((장, 키), ([], "대응표에 없음"))
        if not d["암기장"] and not d["자료"]:
            continue
        줄 = [f"### {장} · <{d['이름']}> → 9판 {' · '.join(번호) or '—'}" + (f"  ({메모})" if 메모 else "")]
        셈 = {"추록": 0, "개정": 0, "비슷": 0, "없음": 0, "9판에만": 0}
        # ① 9판 자리
        구판무리 = set()
        for b in 번호:
            r = 목차집자리(b)
            if r:
                f, 행, 제목, 무리 = r
                구판무리 |= 무리
                줄.append(f"- ① {b} {제목} — `{상대(f)}:{행}`")
            else:
                줄.append(f"- ① {b} — 목차집에서 못 찾음")
        # ② 추록
        for b in 번호:
            for l in 추록줄(b):
                칸 = [c.strip() for c in l.strip("|").split("|")]
                줄.append(f"- ② ⚠추록 {b}: {칸[3]}")
                셈["추록"] += 1
        # ③ 개정 낱말
        for 종류 in ("암기장", "자료"):
            f = d["파일"].get(종류)
            for k, l in d[종류]:
                for pat, 뜻 in 개정낱말:
                    m = re.search(pat, l)
                    if m:
                        줄.append(f"- ③ {종류} `{상대(f)}:{k}` 「{m.group(0)}」 {뜻} — {l.strip()[:60]}")
                        셈["개정"] += 1
                        break
        # ④ 두문자
        상태 = []
        for g in sorted(두문자들(d["암기장"] + d["자료"])):
            무 = 묶음(g)
            if not 무:
                continue
            같 = [x for x in 무 if x in 구판]
            비 = [(x, y) for x in 무 if x not in 구판 for y in 구판 if 비슷(x, y)]
            if len(같) == len(무):
                continue
            if 비:
                상태.append(f"({g}) 비슷: " + ", ".join(f"{x}→[{y}]" for x, y in 비[:3]))
                셈["비슷"] += 1
            elif 같:
                상태.append(f"({g}) 일부: [{'/'.join(같)}]")
            else:
                셈["없음"] += 1
        if 상태:
            줄.append("- ④ " + " · ".join(상태))
        # ⑤ 9판에만
        만 = sorted(g for g in 구판무리 if g not in 도쓰무리 and not any(비슷(g, y) for y in 도쓰무리))
        if 만:
            셈["9판에만"] += len(만)
            줄.append("- ⑤ 9판에만: " + " ".join(f"[{g}]" for g in 만))
        줄.append(f"- 셈: 추록 {셈['추록']} · 개정낱말 {셈['개정']} · 두문자 비슷 {셈['비슷']} · 없음(도쓰 자작?) {셈['없음']} · 9판에만 {셈['9판에만']}")
        out.append("\n".join(줄))
        s = 요약.setdefault(장, {k: 0 for k in 셈})
        for k, v in 셈.items():
            s[k] += v
    return out, 요약


def main():
    인자 = sys.argv[1:]
    고름 = next((a for a in 인자 if not a.startswith("--")), None)
    out, 요약 = 보고(고름)
    if "--요약" in 인자:
        for 장, s in 요약.items():
            print(f"{장:22} " + " · ".join(f"{k} {v}" for k, v in s.items()))
        return
    if 고름:
        print("\n\n".join(out))
        return
    머리 = ["# 도쓰 ↔ 9판 대조 (도쓰대조.py 가 쓴다 — 손으로 고치지 않는다)", "",
           "논점마다 고칠 곳 후보. ① 9판 목차집 자리 ② ⚠추록 ③ 개정 낱말이 든 도쓰 줄 ④ 두문자(같은 것은 생략) ⑤ 9판에만 있는 두문자.",
           "무엇을 고쳤고 무엇을 그대로 뒀는지는 `도쓰갱신.md` 에 적는다.", "",
           "| 장 | " + " | ".join(next(iter(요약.values())).keys()) + " |",
           "|---|" + "---:|" * len(next(iter(요약.values()))),
           *[f"| {장} | " + " | ".join(str(v) for v in s.values()) + " |" for 장, s in 요약.items()], ""]
    보고서.write_text("\n".join(머리) + "\n" + "\n\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"→ {상대(보고서)}  논점 {len(out)}")


if __name__ == "__main__":
    main()
