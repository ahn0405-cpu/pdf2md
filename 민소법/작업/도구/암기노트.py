#!/usr/bin/env python3
"""템플릿(답안 순서)과 목차집 항목 이름을 뼈대로, 외울 문언만 빈칸으로 싣는 암기노트를 뽑는다.

암기노트는 **시험장에 들고 갈 단 한 권**이다(2026-10-19). 목차집은 기본서 내용·순서의 요약,
템플릿(`노트/템플릿/CH08_변론.md`)은 사례집 답안 순서의 뼈대이고, 암기노트가 둘을 합친다 —
template 이 있는 논점은 template 단계 순서로 싣고, 어느 단계에도 안 붙은 블록은 `그 밖에` 에 목차집 순서로.
목차집 요약 문장에 빈칸을 뚫어 보았더니(2026-10-19) 흔한 낱말이 어디서나 가려지고 낱말 중간이
잘려 못 쓰게 되었다 — 그래서 목차집에서는 **항목 이름만** 가져온다.

- **뼈대** — 템플릿의 단계 줄, 그리고 목차집 논점의 항목 이름(`**이름**` · ` — ` 앞 · `학설:` 같은 머리). 핵심·📝 메모는 뺀다.
- **기본서 문언** — 노트의 판례 블록 밖 `>` 인용(의의·요건·검토)을 글자 겹침이 가장 큰 목차집 줄 아래에.
- **판시** — 중요 판례(`표준판례` 이거나 사례집 뱃지 `E-5`)만, 짝지은 (判) 줄 아래에.
- **빈칸** — 노트가 채점 단위로 단 BOLD 그대로.

빈칸에는 BOLD 덩어리의 글자마다 ＿ 를 두되, 띄어쓰기와 조사·기능어(것·수·경우 …)는
그대로 둔다 — 「칸」. 여러 낱말 덩어리가 ＿ 한 줄이 되면 무엇을 묻는지 읽히지 않는다.

장(CHAPTER) 단위로 `노트/목차집/CH08_변론.md` + `노트/템플릿/CH08_변론.md` → `노트/암기노트/CH08_변론.md`.

    python3 암기노트.py              목차집이 있는 장 전부
    python3 암기노트.py 05 08        그 장만
    python3 암기노트.py 05 --화면    파일로 쓰지 않고 화면에
    python3 암기노트.py 046 068     그 논점만 화면에 (세 자리는 논점 번호)
    python3 암기노트.py --검사       짝 없는 중요 판례 · 약한 짝 · 블록 없는 template 단계 · 15자 넘는 빈칸만 보고

**만든 파일을 손으로 고치지 않는다.** 다시 뽑으면 덮어쓴다.
답안 순서가 이상하면 템플릿을, 항목이 이상하면 목차집을, 빈칸·판시가 이상하면 단권화 노트를 고치고 다시 뽑는다.
"""
import re
import sys
from pathlib import Path

from 경로 import 기본서, 노트, 암기노트, 목차집, 템플릿, 기본서파일

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


# 빈칸 안에 그대로 두는 것 — 조사와 기능어. 여러 낱말 덩어리가 ＿ 한 줄이 되면
# 무엇을 묻는지 알 수 없으므로 문장의 뼈대만 보이게 한다.
# 「있다·없다·아니다」 같은 술어는 결론의 방향이 곧 답이라 남기지 않는다.
_조사 = re.compile(r"(.{2,}?)(으로서|로서|으로써|로써|에서|에게|에는|에도|까지|부터|으로|이나"
                 r"|을|를|이|가|은|는|에|의|로|와|과|도|만)")
_기능어 = {"것", "수", "경우", "등", "및", "또는", "위", "그"}
# 조사처럼 끝나지만 낱말의 일부인 것 — 처분권주의·부제소합의·소송참가 …
_조사아님 = {"주의", "합의", "협의", "동의", "이의", "정의", "고의", "선의", "악의", "임의", "의의",
          "참가", "평가", "대가", "국가", "추가", "증가", "허가", "인가", "시가",
          "제도", "정도", "한도", "태도", "의도", "인도", "양도", "명도", "과도",
          "결과", "효과", "경과", "초과", "부과", "통과", "미만", "이도",
          # 어미 — 「못했으므로」의 로, 「없지만」의 만을 조사로 떼면 뜻이 깨진다
          "므로", "지만", "라도", "아도", "어도", "고도", "데도", "아가", "어가", "대로"}


def 칸(낱말):
    """한 어절의 빈칸 — 글자는 ＿ 로, 조사·문장부호는 그대로."""
    if 낱말 in _기능어 or re.fullmatch(r"(?:것|수)(?:으로|이|을|은|는|도|만|에)?", 낱말):
        return 낱말
    m = _조사.fullmatch(낱말)
    if m and m.group(1)[-1] + m.group(2)[0] not in _조사아님 and 낱말[-2:] not in _조사아님:
        몸, 꼬리 = m.groups()
        if 몸 in _기능어:                 # 경우가 · 경우에는
            return 낱말
    else:
        몸, 꼬리 = 낱말, ""
    return re.sub(r"[\w]", "＿", 몸) + 꼬리


def 빈칸(판시):
    """BOLD 를 ❶(＿＿) 로 바꾸고 정답 목록을 함께 돌려준다."""
    정답 = []

    def 바꿈(m):
        답 = re.sub(r"\s+", " ", m.group(1)).strip()
        끝 = re.search(r"[.,]$", 답)                  # 「…아니다.」의 마침표는 빈칸 밖으로
        답 = 답.rstrip(".,")
        정답.append(답)
        return f"{번호표(len(정답))}({' '.join(칸(w) for w in 답.split(' '))})" + (끝.group(0) if 끝 else "")

    return _BOLD.sub(바꿈, 판시), 정답


# ── 쓰기 ────────────────────────────────────────────────


def 논점정보(번호):
    """기본서 머리말의 논점 이름과 기출연도."""
    p = 기본서파일(번호)
    if not p:
        return None, []
    s = p.read_text(encoding="utf-8")[:3000]
    m = re.search(r'^chapter:\s*"(.*)"', s, re.M)
    y = re.search(r"^exam_years:\s*\[(.*)\]", s, re.M)
    연도 = [x.strip() for x in y.group(1).split(",") if x.strip()] if y else []
    return (m.group(1) if m else None), 연도


# ── 목차집과 짝짓기 ─────────────────────────────────────────
# 목차집에는 사건번호가 없다((判) 만 단다). 판시와 (判) 줄의 글자 겹침으로 짝을 찾는다.

짝하한 = 0.2
약한짝 = 0.35
# 겹침으로는 엇갈리는 짝 — (논점, 사건번호): 목차집 그 줄에 있는 말.
# 행 번호로 적지 않는다 — 목차집을 고치면 행이 밀린다.
짝고침 = {
    ("053", "2017다865"): "가정적 항변",
    ("054", "2022다263462"): "석명해야 하는 경우",
    ("055", "2013다25217"): "대위소의 보전의 필요성",
    ("070", "2019다220618"): "소송 중 수감",
    ("070", "2022다229936"): "별거 중인 아내",
    ("071", "2000다60197"): "주소 등을 먼저 시도할 것",
}
_논점머리 = re.compile(r"^# (\d{3}(?:-\d+)?)\s+(.*)$")


def _쌍(s):
    s = re.sub(r"[\s*`\[\]()]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def 목차논점(파일):
    """목차집 한 장을 논점별로 — [(논점, 제목, [줄…])]. 맨 위 표·설명은 버린다."""
    out = []
    for l in 파일.read_text(encoding="utf-8").split("\n"):
        m = _논점머리.match(l)
        if m:
            out.append((m.group(1), m.group(2).strip(), []))
        elif out:
            out[-1][2].append(l)
    return out


def 判줄(줄들):
    """짝 후보가 되는 (判) 줄의 번호 — 학설·핵심 줄과 사례 줄(▸ 이후)은 뺀다."""
    out = []
    for k, l in enumerate(줄들):
        s = l.strip()
        if s.startswith("▸"):
            break
        if "判" in s and not re.match(r"(?:-\s*학설|\*\*핵심\*\*)", s):
            out.append(k)
    return out


def 짝(번호, p, 줄들, 후보):
    """판례가 목차집의 어느 (判) 줄에 해당하나 — (줄 번호, 점수) 또는 None."""
    고침 = 짝고침.get((번호, p["사건"]))
    if 고침:
        return next(((k, 1.0) for k in 후보 if 고침 in 줄들[k]), None)
    b = _쌍(re.sub(r"\*\*", "", p["판시"]))
    점 = [(len(b & (c := _쌍(줄들[k]))) / max(1, min(len(b), len(c))), k) for k in 후보]
    점수, k = max(점, default=(0, None))
    return (k, 점수) if 점수 >= 짝하한 else None


# ── 노트의 기본서 문언 ─────────────────────────────────────────

문언하한 = 0.3


def 문언블록(번호):
    """노트의 기본서 문언 — 판례 블록 밖의 `>` 인용 중 BOLD 가 있고 해설(「니다」)·사례(甲乙)가 아닌 것.
    판례 블록 안인지는 헤딩으로 가린다(①②③ 이나 사건번호 헤딩 아래).
    → [{글, 파일, 행, 절}] 노트 순서. 절 = 그 블록을 감싼 헤딩들(가까운 것이 끝)."""
    out, 본것 = [], set()
    for path in sorted(노트.glob(f"{번호[:3]}_*.md")):
        L = path.read_text(encoding="utf-8").split("\n")
        판례안, 블, 표, 첫, 절 = False, [], [], 0, {}
        for i, l in enumerate(L + [""], 1):
            m = re.match(r"^(#{1,6})\s+(.*)$", l)
            if l.lstrip().startswith(">") and not m:
                if not 블:
                    첫 = i
                블.append(re.sub(r"^[>\s]+", "", l))
                continue
            if l.startswith("|"):                       # 학설 표 — 아래에서 한 줄씩 편다
                if not 표:
                    첫 = i
                표.append(l)
                continue
            글, 학설 = 다듬기("\n".join(블)).strip(), False
            if 표:
                글, 학설 = 학설줄(표), True
            블, 표 = [], []
            if (글 and not 판례안 and "**" in 글 and "니다" not in 글
                    and not re.search(r"[甲乙丙丁]", 글)):
                열쇠 = re.sub(r"\s", "", 글)
                if 열쇠 not in 본것:
                    본것.add(열쇠)
                    out.append({"글": 글, "파일": path.name, "행": 첫, "학설": 학설,
                                "절": [절[n] for n in sorted(절)]})
            if m:                                   # 블록을 끊은 뒤에 헤딩 상태를 바꾼다
                n = len(m.group(1))
                절 = {k: v for k, v in 절.items() if k < n}
                절[n] = re.sub(r"`[^`]*`", "", m.group(2)).strip()
                판례안 = bool(re.search(r"[①②③]", m.group(2)) or _사건.search(m.group(2)))
    return out


def 학설줄(표):
    """노트의 학설 표(`| 견해 | 논거 | 결론 |`)를 `견해: 논거 → 결론` 줄들로. 학설 표가 아니면 ""."""
    칸들 = [[c.strip() for c in l.strip().strip("|").split("|")] for l in 표
            if not re.match(r"^\|[\s:|-]+\|?$", l.strip())]
    if len(칸들) < 2 or 칸들[0][:2] != ["견해", "논거"]:
        return ""
    결론 = len(칸들[0]) > 2 and 칸들[0][2] == "결론"       # 「위 사례에서는」 칸은 뺀다
    줄 = []
    for c in 칸들[1:]:
        if len(c) < 2:
            continue
        이름 = re.sub(r"\*\*", "", c[0]).strip()           # 견해명은 가리지 않는다
        줄.append(f"{이름}: {c[1]}" + (f" → {c[2]}" if 결론 and len(c) > 2 and c[2] else ""))
    return 다듬기("\n".join(줄))


# ── 분절 — 판시를 i) ii) iii) 토막으로 (도쓰 「자료」에서 가져온 것) ─────────

_로마 = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv"]
_자를곳 = re.compile(r"(?:, |(?:므로|하여|하고|이나|는데|으며|지만|면서|하며|이고|이며|거나|에는|더라도|라도) )")
_있는번호 = re.compile(r"(?:(?<=\s)|^)(?:[ivx]{1,4})\)\s")
토막상한, 토막하한 = 50, 15


def _굵은안(t):
    """t 의 각 위치가 **…** 안인가."""
    안, 속 = [False] * (len(t) + 1), False
    i = 0
    while i < len(t):
        if t.startswith("**", i):
            속 = not 속
            안[i] = 안[i + 1] = 속
            i += 2
            continue
        안[i] = 속
        i += 1
    return 안


def _길이(t):
    """찍힌 줄의 길이 어림 — 빈칸 하나는 ❶( ) 와 띄어쓰기로 3자쯤 늘어난다."""
    return len(re.sub(r"\*\*|\s", "", t)) + 3 * (t.count("**") // 2)


def _쪼개기(t):
    """한 문장을 쉼표·연결어미 뒤에서 가운데에 가깝게 반으로 — 양쪽 하한 이상, 빈칸 안은 피한다."""
    if _길이(t) <= 토막상한:
        return [t]
    안 = _굵은안(t)
    후보 = [m.end() for m in _자를곳.finditer(t)
          if not 안[m.end() - 1] and _길이(t[:m.end()]) >= 토막하한 and _길이(t[m.end():]) >= 토막하한]
    if not 후보:
        return [t]
    가운데 = len(t) / 2
    i = min(후보, key=lambda x: abs(x - 가운데))
    return _쪼개기(t[:i].rstrip()) + _쪼개기(t[i:].lstrip())


def 분절(글):
    """판시·기본서 문언을 토막 줄로. 이미 i) 가 있으면 그 앞에서만, 없으면 문장 끝과 연결어미에서."""
    문단 = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", 글) if p.strip()]
    if any(_있는번호.search(p) for p in 문단):
        out = []
        for p in 문단:
            안 = _굵은안(p)
            자리 = [m.start() for m in _있는번호.finditer(p) if not 안[m.start()]]
            for a, b in zip([0] + 자리, 자리 + [len(p)]):
                if p[a:b].strip():
                    out.append(p[a:b].strip())
        return out
    토막 = []
    for p in 문단:
        안 = _굵은안(p)
        끝 = [m.end() for m in re.finditer(r"(?:[다요]|\))(?:\*\*)?\.(?=\s)", p) if not 안[m.end() - 1]]
        for a, b in zip([0] + 끝, 끝 + [len(p)]):
            if p[a:b].strip():
                토막 += _쪼개기(p[a:b].strip())
    if len(토막) < 2:
        return 토막
    return [f"{_로마[k] if k < len(_로마) else k + 1}) {x}" for k, x in enumerate(토막)]


def 붙일자리(글, 줄들, 후보):
    """글자 겹침이 가장 큰 목차집 줄 — (줄 번호, 점수)."""
    b = _쌍(re.sub(r"\*\*", "", 글))
    점 = [(len(b & (c := _쌍(줄들[k]))) / max(1, min(len(b), len(c))), k) for k in 후보]
    return max(점, default=(0, None))[::-1]


# ── 목차집 뼈대 ──────────────────────────────────────────────

_항목머리 = re.compile(r"^(\s*(?:(?:[-*]|\d+\.)\s+)?)")    # 「**의의**」의 * 는 목록 기호가 아니다


def 항목이름(l):
    """목차집 줄의 (머리, 항목 이름). 이름이 없으면 None — 그 줄은 요약 문장뿐이다.
    이름: 줄 머리의 `**이름**`(뒤 백틱 포함) · ` — ` 앞 · `학설:` 같은 짧은 머리."""
    머리 = _항목머리.match(l).group(1)
    몸 = l[len(머리):]
    m = re.match(r"\*\*[^*]+\*\*((?:\s*`[^`]*`)*)", 몸)
    if m:
        return 머리, m.group(0).strip()
    m = re.match(r"([^—]{1,60}?)\s—\s", 몸)
    if m:
        return 머리, m.group(1).strip()
    m = re.match(r"([^:：—]{1,20}?)\s*[:：]\s", 몸)
    if m:
        return 머리, m.group(1).strip()
    # 번호 줄이 짧은 이름뿐인 것 — 「1. 판단기준 `기출 10·12`」 · 「5. 과실·정당한 사유 등 불확정개념」
    if re.match(r"\d+\.", 머리.strip()) and len(re.sub(r"`[^`]*`", "", 몸).strip()) <= 24 \
            and not re.search(r"다\.|[(（]判|→", 몸):
        return 머리, 몸.strip()
    return 머리, None


def 줄임(몸):
    """이름 없는 줄 — 결론을 드러내지 않게 첫 ` → `·`(判)`·40자에서 자른다."""
    t = re.sub(r"\*\*", "", 몸).strip()
    끝 = min([i for i in (t.find(" → "), t.find("(判)")) if i > 0] + [40])
    return t[:끝].rstrip(" ,·") + ("…" if 끝 < len(t) else "")


# ── 쓰기 ────────────────────────────────────────────────


def 인용(글, 들여, 머리줄=None, 쪼갬=True):
    """노트 BOLD 를 빈칸으로 바꾼 인용 블록 — 줄의 들여쓰기에 맞춘다.
    토막(i) ii) …)마다 한 줄. 빈칸 번호는 블록 안에서 이어 센다."""
    새, 정답 = 빈칸("\n".join(분절(글)) if 쪼갬 else 글)
    w = [f"{들여}> {머리줄}"] if 머리줄 else []
    w += [f"{들여}> {x}".rstrip() for x in 새.split("\n")]
    return w + [""], 정답


def 判표시(글, 줄, 줄들):
    """학설 줄의 견해명에 목차집 학설 줄의 `(判·검토)` 를 붙인다 — 그 블록이 붙은 줄에서만 찾는다
    (같은 논점의 다른 쟁점 학설 줄에서 가져오면 엉뚱한 견해에 判 이 붙는다)."""
    목 = [re.sub(r"\*\*", "", 줄)] if "학설" in 줄 else []
    out = []
    for l in 글.split("\n"):
        이름, 사이, 뒤 = l.partition(": ")
        for t in 목:
            m = re.search(re.escape(이름) + r"\(([^()]{1,8})\)", t)
            if m and re.search(r"判|검토", m.group(1)):
                이름 = f"{이름}({m.group(1)})"
                break
        out.append(이름 + 사이 + 뒤)
    return "\n".join(out)


def 본문줄(줄들):
    """논점의 목차 본문 — `▸` (사례 줄·답안 template) 앞까지."""
    사례 = next((k for k, l in enumerate(줄들) if l.strip().startswith("▸")), len(줄들))
    return 줄들[:사례]


def 블록쓰기(종류, x, 들여, 줄, 줄들, 표시):
    """붙은 것 하나를 빈칸 인용으로 → (줄들, 정답, 정답 머리). 목차순 판·답안 set 판이 같이 쓴다."""
    if 종류 == "판":
        꼬리 = "　".join(y for y in ("★" if x["표준"] else "", " ".join(x["뱃지"])) if y)
        블, 정답 = 인용(x["판시"], 들여, "**判**" + (f"　{꼬리}" if 꼬리 else ""))
        return 블, 정답, x["사건"]
    if x.get("학설"):
        블, 정답 = 인용(判표시(x["글"], 줄, 줄들), 들여, 쪼갬=False)
        return 블, 정답, "학설"
    블, 정답 = 인용(x["글"], 들여)
    return 블, 정답, 표시


def 빈줄정리(w):
    """인용 뒤 빈 줄은 번호 목록(「2. 」)·굵은 머리·다음 인용 앞에서만 둔다 — 없으면 인용에 이어 붙는다.
    나머지는 지면만 늘리므로 뺀다(프린트용)."""
    w = [l for i, l in enumerate(w)
         if l.strip() or i + 1 >= len(w) or not w[i - 1].lstrip().startswith(">")
         or re.match(r"\s*(?:\d+\.\s|\*\*|>|#)", w[i + 1])]
    while w and not w[-1].strip():
        w.pop()
    return w


def 붙임계산(번호, 줄들):
    """목차집 한 논점(본문 줄) → ({줄 번호: [(파일, 행, 종류, 것)]}, 보고).
    중요 판례는 (判) 줄에, 기본서 문언·학설은 글자 겹침이 가장 큰 줄에."""
    후보 = [k for k, l in enumerate(줄들) if l.strip() and not l.strip().startswith(("|", "<!--"))]
    붙임 = {}                                  # 줄 번호 → [(파일, 행, 종류, 것)]
    보고 = []

    본것 = set()
    for path in sorted(노트.glob(f"{번호[:3]}_*.md")):
        for p in 판례들(path):
            열쇠 = (p["사건"], re.sub(r"\s", "", p["판시"]))
            if 열쇠 in 본것 or not p["판시"]:
                continue
            본것.add(열쇠)
            if not (p["표준"] or p["뱃지"]):     # 중요 판례만 판시를 싣는다
                continue
            j = 짝(번호, p, 줄들, 判줄(줄들))
            if not j:
                보고.append(("짝없음", path.name, p, None))
                continue
            if j[1] < 약한짝:
                보고.append(("약한짝", path.name, p, j))
            붙임.setdefault(j[0], []).append((path.name, p["행"], "판", p))

    앞 = None
    for d in 문언블록(번호):
        k, 점수 = 붙일자리(d["글"], 줄들, 후보)
        # 노트 순서를 거슬러 앞 줄로 튀지 않게 — 요건 (1)(2)(3) 이 갈라지던 것.
        # 앞 블록 자리 이후에서도 거의 같은 점수(0.8배)가 나오면 그쪽에 붙인다.
        if 앞 is not None and k is not None and k < 앞:
            k2, 점2 = 붙일자리(d["글"], 줄들, [x for x in 후보 if x >= 앞])
            if k2 is not None and 점2 >= 점수 * 0.8:
                k, 점수 = k2, 점2
        if 점수 < 문언하한:
            # 짝이 약하면 노트에서 그 블록이 놓인 절 제목으로 목차집 항목을 찾는다(가까운 절부터).
            # 「검토」 같은 일반 이름은 건너뛰고, 그래도 없으면 앞 블록 자리.
            자리 = None
            for 제 in reversed(d["절"]):
                제 = _번호머리.sub("", 제).strip()
                if len(제) < 3 or _일반절.match(제):
                    continue
                k3, 점3 = 붙일자리(제, 줄들, 후보)
                if 점3 >= 0.6:
                    자리 = k3
                    break
            k = 자리 if 자리 is not None else (앞 if 앞 is not None else k)
            보고.append(("기댄문언", d["파일"], {"행": d["행"], "사건": d["글"][:40]},
                       (k, 점수, "절 제목" if 자리 is not None else "앞 블록")))
        if k is None:
            continue
        앞 = k
        붙임.setdefault(k, []).append((d["파일"], d["행"], "문", d))
    return 붙임, 보고


def 남은줄(줄들, 붙임):
    """`그 밖에` 에 실을 줄 — 남은 블록이 붙은 줄과 그 윗줄(항목 이름의 줄기)."""
    깊 = lambda l: len(l) - len(l.lstrip())
    out = set()
    for k in 붙임:
        out.add(k)
        d = 깊(줄들[k])
        for j in range(k - 1, -1, -1):
            if 줄들[j].strip() and 깊(줄들[j]) < d:
                out.add(j)
                d = 깊(줄들[j])
                if d == 0:
                    break
    return out


def 목차순쓰기(번호, 줄들, 붙임, 고른=None):
    """목차집 항목 이름을 뼈대로 블록을 싣는다 → (줄들, 정답, 실음).
    고른(줄 번호 집합)이 있으면 그 줄만 — template 에 실리고 남은 것(`그 밖에`)."""
    w, 답, 실음 = [""], [], []
    주석, 메모 = False, None
    for k, l in enumerate(줄들):
        s = l.strip()
        if 주석 or s.startswith("<!--"):
            주석 = "-->" not in s
            continue
        깊이 = len(l) - len(l.lstrip())
        if 메모 is not None and (깊이 > 메모 or not s):
            continue
        메모 = None
        if not s or s == "---" or s.startswith(("|", "#", "**핵심**")):
            continue
        if re.match(r"(?:[-*]\s+)?📝", s):          # 사용자의 메모 — 목차집에서 본다
            메모 = 깊이
            continue
        if 고른 is not None and k not in 고른:
            continue
        머리, 이름 = 항목이름(l)
        것들 = sorted(붙임.get(k, []), key=lambda x: (x[0], x[1]))
        if not 이름 and not 것들 and 고른 is None:      # `그 밖에` 에서는 이름 없는 윗줄도 줄여서 싣는다 — 어디 붙은 블록인지 보이게
            continue
        if not 머리.strip() and w[-1].strip():        # 목록 밖 줄(**의의** 등)은 문단을 띄운다
            w.append("")
        표시 = 이름 or 줄임(l[len(머리):])
        w.append(머리 + 표시)
        들여 = " " * len(머리)
        표시 = re.sub(r"\*\*|`[^`]*`", "", 표시).strip()
        for _, _, 종류, x in 것들:
            블, 정답, 머리글 = 블록쓰기(종류, x, 들여, l, 줄들, 표시)
            답.append((머리글, 정답))
            if 종류 != "판":
                x["사건"] = 머리글
            x["정답"] = 정답
            w += 블
            실음.append(x)
    return w, 답, 실음


def 논점쓰기(번호, 제목, 논점들):
    """한 논점 → (글, 실은 것[판례·문언], 빈칸 수, 보고).
    template 이 있으면 template 순서로 먼저 싣고, 어느 단계에도 안 붙은 블록은 `그 밖에` 에 목차집 순서로."""
    _, 연도 = 논점정보(번호[:3])
    v = 논점들[번호]
    줄들, 붙임, 보고 = v["줄들"], v["붙임"], list(v["보고"])

    기출 = f" `기출 {', '.join(연도)}`" if 연도 and "기출" not in 제목 else ""
    w = [f"# {번호} {제목}{기출}", ""]
    답, 실음 = [], []
    if v["템플릿"]:
        tw, t답, t실음, 쓴, t보고 = 셋쓰기(논점들, 번호)
        w += tw
        답 += t답; 실음 += t실음; 보고 += t보고
        남은 = {k: [x for x in 것들 if (번호, k, x[0], x[1]) not in 쓴] for k, 것들 in 붙임.items()}
        남은 = {k: 것들 for k, 것들 in 남은.items() if 것들}
        if 남은:
            mw, m답, m실음 = 목차순쓰기(번호, 줄들, 남은, 남은줄(줄들, 남은))
            w += ["## 그 밖에"] + mw
            답 += m답; 실음 += m실음
    else:                                       # template 이 없으면 목차집 순서 그대로 — 가리킴 줄은 끝에
        mw, 답, 실음 = 목차순쓰기(번호, 줄들, 붙임)
        w += mw[1:]
        if v["사례줄"]:
            w += ["", "## 함께 나오는 사례", ""] + [re.sub(r"^▸\s*", "", l) for l in v["사례줄"]]
    w = 빈줄정리(w)
    w += ["", "---", "", f"## {번호} 정답", ""]
    w += [f"- {이름}　" + ("　".join(f"{번호표(i)} {d}" for i, d in enumerate(정답, 1)) or "— 통째로")
          for 이름, 정답 in 답]
    w += ["", "---", ""]
    return "\n".join(w), 실음, sum(len(x) for _, x in 답), 보고


# ── template — 사례집 답안 순서 (`노트/템플릿/CH08_변론.md`) ─────────────────────
# 사례집은 한 주제를 하나의 set(문제의 소재 → 의의 → 判 → 요건 → 사안해결)으로 묻는다.
# template 단계마다 목차집 항목에 붙은 블록을 끌어다 붙인다. 논점 안에서 두 번째로 나오는 블록은
# 처음 실은 자리(`→ {일부인용} 2.(1)`)를 가리킨다 — 같은 빈칸을 한 권에서 두 번 채우지 않게.

_템플릿머리 = re.compile(r"^\*\*\{(.+?)\}\*\*\s*(.*)$")
_가리킴 = re.compile(r"→\s*(\d{3})")
_지시 = re.compile(r"사안 포섭|배점|먼저 세운다")


def 템플릿들(줄들):
    """템플릿 파일 한 논점의 줄 → [(이름, 머리 뒤, [단계 줄…])]. 단계 = 머리 다음 빈 줄까지."""
    out, 지금 = [], None
    for l in 줄들:
        m = _템플릿머리.match(l.strip())
        if m:
            지금 = (m.group(1), m.group(2).lstrip("— ").strip(), [])
            out.append(지금)
        elif 지금 and l.strip():
            지금[2].append(l)
        else:
            지금 = None
    return out


def 사례줄들(줄들):
    """template 밖의 줄 — 다른 논점의 template 을 가리키는 줄, 아직 template 으로 안 바꾼 사례 줄."""
    out, 안 = [], False
    for l in 줄들:
        s = l.strip()
        if _템플릿머리.match(s):
            안 = True
        elif not s:
            안 = False
        elif not 안 and s != "---" and not s.startswith("<!--"):
            out.append(l)
    return out


def 단계표시(l):
    """단계 줄의 이름만 — ` — ` 나 `: ` 뒤 요약은 빈칸 답을 드러내므로 뺀다. 두문자·배점·쓰는 법은 둔다."""
    머리 = _항목머리.match(l).group(1)
    몸 = l[len(머리):]
    i = min([x for x in (몸.find(" — "), 몸.find(": ")) if x > 0] + [len(몸)])
    앞, 뒤 = 몸[:i], 몸[i:]
    # 학설 단계는 견해 이름을 남긴다(이름은 답이 아니라 실마리) · 쓰는 법 지시도 남긴다
    남김 = _지시.search(뒤) or re.search(r"학설\s*$", 앞)
    덧 = re.findall(r"`[^`]*`", 뒤) + ([뒤.lstrip(" —:")] if 남김 else [])
    덧 = [x for x in 덧 if x not in 앞]
    return 머리 + 앞.rstrip() + ("　" + " ".join(덧) if 덧 else "")


def 단계자리들(단계들):
    """단계 줄마다 자리 이름(`2.(1)` · `설문2 3.`) — 두 번째로 나오는 블록이 이 이름으로 처음 자리를 가리킨다."""
    out, 설문, 큰 = [], "", ""
    for l in 단계들:
        s = l.strip()
        if m := re.match(r"-\s*(설문\s*\S+)$", s):
            설문, 큰 = m.group(1) + " ", ""
            out.append(설문.strip())
        elif m := re.match(r"(?:-\s*)?(\d+)\.\s", s):
            큰 = m.group(1) + "."
            out.append(설문 + 큰)
        elif m := re.match(r"-\s*(\(\d+\))", s):
            out.append(설문 + 큰 + m.group(1))
        else:
            out.append(설문 + 큰)
    return out


def 단계잇기(l, 논점들, 집, 가리킨, 잎=True):
    """단계 줄 하나 → 이을 목차집 항목 [(논점, 줄 번호, 직접)]. 직접 = 그 줄을 바로 가리켰다(하위 줄로 딸려 온 것이 아니다).
    ① 두문자 ② 학설 이름과 괄호(`법규기준설(判·검토)`) ③ 「의의」(그 논점 제목이 단계에 있으면 그 논점)
    ④ 글자 겹침 0.4 이상 — 하위 단계가 있는 큰 단계(잎이 아닌 것)는 ④ 를 쓰지 않는다(엉뚱한 判 을 끌어왔다).
    찾는 곳: template 이 있는 논점 + 가리킨 논점(→ 054). 블록이 붙은 줄만 본다."""
    범위 = [집] + [n for n in 가리킨 if n in 논점들 and n != 집]
    줄있는 = lambda n: [k for k in 논점들[n]["붙임"]]
    t = re.sub(r"\*\*", "", l)
    맞음 = []

    def 아래까지(n, k):
        """목차집 줄 k 와 그보다 깊게 들여쓴 하위 줄 가운데 블록이 붙은 것."""
        줄들 = 논점들[n]["줄들"]
        깊 = len(줄들[k]) - len(줄들[k].lstrip())
        아래 = [k]
        for j in range(k + 1, len(줄들)):
            if 줄들[j].strip() and len(줄들[j]) - len(줄들[j].lstrip()) <= 깊:
                break
            아래.append(j)
        return [(n, j, j == k) for j in 아래 if j in 논점들[n]["붙임"]]

    for d in re.findall(r"`(\[[^\]`]+\])`", l):                     # ① 두문자 — 그 줄과 하위 줄까지
        for n in 범위:
            for k, x in enumerate(논점들[n]["줄들"]):
                if d in x:
                    맞음 += 아래까지(n, k)
    # ①-2 목차집 항목 이름이 단계 이름(` — ` 앞)에 그대로 있으면 — 뒤쪽 설명 문구(「질적 동일을 벗어나」)로는 잇지 않는다
    # 「효과」·「부인」처럼 짧은 이름은 단계 이름이 그것뿐일 때만(「- (3) 효과」)
    표 = re.sub(r"\*\*", "", 단계표시(l))
    핵 = re.sub(r"`[^`]*`|^[-\s]*(?:\(\d+\)|\d+\.)?\s*", "", 표).strip()
    for n in 범위:
        for k, x in enumerate(논점들[n]["줄들"]):
            이름 = re.sub(r"\*\*|`[^`]*`|^\s*☑\s*", "", 항목이름(x)[1] or "").strip()
            if 이름 and 이름 not in ("학설", "검토", "判", "의의") and (len(이름) >= 4 and 이름 in 표 or 이름 == 핵):
                맞음 += 아래까지(n, k)
    for 설 in re.findall(r"[가-힣]{2,10}설\([^()]*\)", t):             # ② 학설 이름 + 괄호까지
        for n in 범위:
            맞음 += [(n, k, True) for k in 줄있는(n)
                   if "학설" in 논점들[n]["줄들"][k] and 설 in re.sub(r"\*\*", "", 논점들[n]["줄들"][k])]
    if not 맞음 and re.search(r"(?<!협)의의", t):                       # ③ 의의(「협의의」는 아니다)
        이름난 = [n for n, v in 논점들.items() if v["제목"] and v["제목"] in t]
        for n in (이름난 or [집]):
            맞음 += [(n, k, True) for k in 줄있는(n) if 논점들[n]["줄들"][k].lstrip().startswith("**의의**")]
    판있음 = any(종류 == "판" for n, k, _ in 맞음 for _, _, 종류, _ in 논점들[n]["붙임"][k])
    판물음 = "判" in re.sub(r"[가-힣]{2,10}설\([^()]*\)", "", t)      # 「법규기준설(判·검토)」의 判 은 判例 단계가 아니다
    # ④ 글자 겹침 — 아무것도 못 찾았거나, 단계에 「判」이 있는데 이은 줄에 판시가 없을 때(학설 줄만 잡힌 경우)
    if 잎 and (not 맞음 or (판물음 and not 판있음)):
        best = (0, None, None)
        for n in 범위:
            판줄 = [k for k in 줄있는(n) if 맞음 == [] or any(y[2] == "판" for y in 논점들[n]["붙임"][k])]
            k, 점 = 붙일자리(t, 논점들[n]["줄들"], 판줄)
            if k is not None and 점 > best[0]:
                best = (점, n, k)
        if best[0] >= 0.4:
            맞음.append((best[1], best[2], True))
    out = {}
    for n, k, 직접 in 맞음:                                          # 같은 줄이 둘로 잡히면 「직접」이 이긴다
        out[(n, k)] = out.get((n, k), False) or 직접
    return [(n, k, d) for (n, k), d in out.items()]


def 셋쓰기(논점들, 집):
    """한 논점의 template 들 → (줄들, 정답, 실음, 쓴, 보고).
    쓴 = {블록 열쇠: 처음 실은 자리}, 블록 열쇠 = (논점, 목차집 줄, 노트 파일, 행)."""
    v = 논점들[집]
    w, 답, 실음, 보고, 쓴 = [], [], [], [], {}
    깊이 = lambda s: len(s) - len(s.lstrip())
    # 1차: template 마다, 단계마다 이을 목차집 줄 — 다른 template 이 바로 가리킨 줄을 알아야 해서 먼저 다 잇는다
    전부이음 = []
    for 이름, 머리뒤, 단계들 in v["템플릿"]:
        이음, 가리킨 = [], []
        for i, l in enumerate(단계들):
            if re.match(r"\d+\.\s", l):               # 큰 단계가 바뀌면 그 단계가 가리킨 논점을 새로 잡는다
                가리킨 = _가리킴.findall(l)
            잎 = i + 1 >= len(단계들) or 깊이(단계들[i + 1]) <= 깊이(l)
            이음.append(단계잇기(l, 논점들, 집, 가리킨 + _가리킴.findall(l), 잎))
        전부이음.append(이음)
    for 번째, ((이름, 머리뒤, 단계들), 이음) in enumerate(zip(v["템플릿"], 전부이음)):
        짧은 = re.sub(r"\s*template$", "", 이름)
        w += [f"## {{{짧은} template}}" + (f" — {머리뒤}" if 머리뒤 else ""), ""]
        남직접 = {(n, k) for j, 다른 in enumerate(전부이음) if j != 번째
               for 줄들 in 다른 for n, k, 직접 in 줄들 if 직접}
        # 2차: 한 줄의 블록을 그 줄에 이어진 단계들 가운데 글이 가장 닮은 단계에 하나씩 — 요건 (1)(2)(3) 이 한데 몰리지 않게.
        나눔 = {i: [] for i in range(len(단계들))}
        줄단계 = {}
        for i, 줄들 in enumerate(이음):
            for n, k, 직접 in 줄들:
                줄단계.setdefault((n, k), []).append((i, 직접))
        for (n, k), 이은 in 줄단계.items():
            # 그 줄을 바로 가리킨 단계가 있으면 그쪽만 — 큰 단계가 하위 항목까지 통째로 끌어가지 않게.
            # 여기서는 하위 줄로 딸려 왔을 뿐인데 다른 template 이 바로 가리켰으면 그쪽에 맡긴다.
            if not any(직접 for _, 직접 in 이은) and (n, k) in 남직접:
                continue
            단계번호들 = [i for i, 직접 in 이은 if 직접] or [i for i, _ in 이은]
            for 것 in sorted(논점들[n]["붙임"][k], key=lambda y: (y[0], y[1])):
                글 = 것[3].get("판시") or 것[3].get("글", "")
                점 = [(len(_쌍(글) & _쌍(단계표시(단계들[i]))), -i) for i in 단계번호들]
                나눔[-max(점)[1]].append((n, k, 것))
        자리들 = 단계자리들(단계들)
        for i, l in enumerate(단계들):
            w.append(단계표시(l))
            들여 = " " * (len(_항목머리.match(l).group(1)) + 2)
            for n, k, (파일, 행, 종류, x) in 나눔[i]:
                열쇠 = (n, k, 파일, 행)
                if 열쇠 in 쓴:                          # 논점 안 두 번째 — 처음 자리를 가리킨다
                    w += [f"{들여}> " + ("**判** " if 종류 == "판" else "") + f"→ {쓴[열쇠]}", ""]
                    continue
                쓴[열쇠] = f"{{{짧은}}} {자리들[i]}".rstrip()
                줄 = 논점들[n]["줄들"][k]
                표시 = re.sub(r"\*\*|`[^`]*`", "", 단계표시(l)).strip(" -")[:24]
                블, 정답, 머리글 = 블록쓰기(종류, x, 들여, 줄, 논점들[n]["줄들"], 표시)
                w += 블
                답.append((f"{{{짧은}}} {머리글}", 정답))
                if 종류 != "판":
                    x["사건"] = 머리글
                x["정답"] = 정답
                실음.append(x)
            잎 = i + 1 >= len(단계들) or 깊이(단계들[i + 1]) <= 깊이(l)      # 하위 단계가 있는 큰 단계는 원래 비어 있다
            if 잎 and not 나눔[i] and not re.search(r"문제의 소재|사안해결|사안$|설문\d", l):
                보고.append(("빈단계", 짧은, {"사건": 단계표시(l).strip()}, None))
        w.append("")
    if v["사례줄"]:
        w += ["## 함께 나오는 사례", ""] + [re.sub(r"^▸\s*", "", l) for l in v["사례줄"]] + [""]
    return w, 답, 실음, 쓴, 보고


def 장파일(폴더, 번):
    return next(iter(sorted(폴더.glob(f"CH{번}_*.md"))), None)


def 장논점들(번):
    """장의 논점마다 {제목, 원제목, 줄들(목차집 본문), 붙임, 보고, 템플릿, 사례줄}.
    다른 논점을 가리키는 template 이 있어 장 전체를 먼저 계산한다."""
    파일 = 장파일(목차집, 번)
    if not 파일:
        return {}
    t파일 = 장파일(템플릿, 번)
    템 = {n: 줄들 for n, _, 줄들 in 목차논점(t파일)} if t파일 else {}
    out = {}
    for 번호, 제목, 줄들 in 목차논점(파일):
        본 = 본문줄(줄들)
        붙임, 보고 = 붙임계산(번호, 본)
        t = 템.get(번호, [])
        out[번호] = {"제목": re.sub(r"\s*`[^`]*`", "", 제목).strip(), "원제목": 제목, "줄들": 본,
                   "붙임": 붙임, "보고": 보고, "템플릿": 템플릿들(t), "사례줄": 사례줄들(t)}
    return out


머리말 = """시험장에 들고 갈 책입니다. 목차집의 항목 아래 외울 문언만 빈칸으로 실었습니다.
사례로 나오는 논점은 **답안 template 순서**(`## {… template}`)로 먼저 싣고, 어느 단계에도 붙지 않은 문언은
`## 그 밖에` 에 목차집 순서로 싣습니다. 같은 논점 안에서 두 번째로 나오는 문언은 `→ {일부인용} 2.(1)` 처럼
처음 실은 자리를 가리킵니다. 사례가 없는 논점은 목차집 순서 그대로입니다.

`>` 는 기본서 문언(의의·요건·검토), `> **判**` 은 중요 판례(**★ 표준판례** 이거나 **사례집 수록**)의 판시 문언입니다.
＿ 하나가 한 글자이고, 띄어쓰기와 조사(을·를·에·의 …)·「것·수·경우」는 빈칸 안에 그대로 두었습니다.
빈칸 번호는 인용마다 ❶ 부터 다시 셉니다. 정답은 각 논점 끝에 있습니다.

<!-- 암기노트.py 가 뽑은 것이다(뼈대 = 템플릿 + 목차집 항목 이름, 문언·빈칸 = 단권화 노트).
     손으로 고치지 말고 템플릿·목차집·단권화 노트를 고친 뒤 다시 뽑는다. -->"""


def 장쓰기(번, 이름):
    논점들 = 장논점들(번)
    if not 논점들:
        return None, [], 0, []
    본문, 실음, 빈, 보고 = [], [], 0, []
    for 번호, v in 논점들.items():
        글, 판, n, b = 논점쓰기(번호, v["원제목"], 논점들)
        본문.append(글)
        실음 += 판; 빈 += n; 보고 += b
    w = [f"# 암기노트 · CHAPTER {번} {이름}", "", 머리말, "", "---", ""]
    return "\n".join(w + 본문).rstrip("\n") + "\n", 실음, 빈, 보고


def main():
    인자 = sys.argv[1:]
    # 모르는 옵션(--help 등)을 무시하고 전 장을 덮어쓰는 일이 실제로 있었다
    모름 = [a for a in 인자 if a.startswith("-") and a not in ("--화면", "--검사")]
    if 모름:
        sys.exit(f"모르는 옵션: {' '.join(모름)}\n쓰는 법은 이 파일 맨 위 설명 (--화면 · --검사)")
    화면, 검사 = "--화면" in 인자, "--검사" in 인자
    고른 = [a for a in 인자 if not a.startswith("--")]
    논점 = [a for a in 고른 if len(a) == 3 and a.isdigit()]
    if 논점:                             # 논점 미리보기 — 장 파일은 건드리지 않는다
        for n in 논점:
            for 번, _, 첫, 끝 in 장:
                if 첫 <= int(n) <= 끝:
                    논점들 = 장논점들(번)
                    for 번호, v in 논점들.items():
                        if 번호[:3] == n:
                            print(논점쓰기(번호, v["원제목"], 논점들)[0])
        return
    대상 = [c for c in 장 if not 고른 or c[0] in 고른 or c[0].lstrip("0") in 고른]
    if 고른 and not 대상:
        sys.exit(f"그런 장이 없다: {' '.join(고른)} (01~18)")

    합 = [0, 0, 0]
    for 번, 이름, _, _ in 대상:
        글, 실음, 빈, 보고 = 장쓰기(번, 이름)
        if not 글:
            continue
        합[0] += 1; 합[1] += len(실음); 합[2] += 빈
        if 검사:
            for 종류, 파일, p, j in 보고:
                if 종류 == "약한짝":
                    print(f"  약한짝 {j[1]:.2f}  {파일}:{p['행']}  {p['사건']}")
                elif 종류 == "짝없음":
                    print(f"  짝없음     {파일}:{p['행']}  {p['사건']}  (중요 판례인데 목차집 (判) 줄과 짝이 없다)")
                elif 종류 == "빈단계":
                    print(f"  빈단계     {{{파일}}}  {p['사건']}  (template 단계에 붙은 블록이 없다 — 단계 이름에 목차집 항목 이름을 넣는다)")
                elif 종류 == "기댄문언":
                    print(f"  기댄문언 {j[1]:.2f}  {파일}:{p['행']}  {p['사건']}…  (짝이 약해 {j[2]} 자리에)")
            for p in 실음:
                for d in p["정답"]:
                    if 진단자수(d) > 빈칸상한:
                        print(f"  {진단자수(d):2}자      {p['사건']}  「{d}」")
            # 분절이 못 나눈 긴 토막 · 빈칸 괄호 밖에 남은 ＿(분절이 빈칸을 자른 것)
            for l in 글.split("\n"):
                t = l.strip()
                if not t.startswith(">"):
                    continue
                if len(t) > 92:
                    print(f"  긴토막 {len(t)}  {t[:50]}…")
                if "＿" in re.sub(r"(?:[❶-❿⓫-⓴]|\(\d+\))\((?:[^()]|\([^()]*\))*\)", "", t):   # 빈칸 안 괄호 하나까지
                    print(f"  잘린빈칸  {t[:60]}…")
            continue
        if 화면:
            print(글)
            continue
        암기노트.mkdir(parents=True, exist_ok=True)
        out = 암기노트 / f"CH{번}_{re.sub(r'\s*—\s*', '-', 이름).replace(' ', '')}.md"
        out.write_text(글, encoding="utf-8", newline="\n")
        판 = sum(1 for x in 실음 if "판시" in x)
        print(f"CH{번} {이름:14}  판시 {판:3}  기본서 문언 {len(실음) - 판:3}  빈칸 {빈:4}  → {out.name}")
    if not 화면:
        print(f"\n합계  장 {합[0]}  판례 {합[1]}  빈칸 {합[2]}")


if __name__ == "__main__":
    main()
