#!/usr/bin/env python3
"""도쓰 자료(`특허법/참고/*.pdf`)를 마크다운으로 옮긴다 — **첫 판을 한 번 만들 때만** 쓴다.

22년 합격자 「도쓰」가 테마 특허법(옛 판)으로 만든 두 PDF 다. 한컴 PDF 라 글자·굵기·색을 그대로 읽는다(OCR 없음).

    암기장   논점별 답안 뼈대 + 두문자 `(약속의용/용시)`  → 노트/암기장/<장>.md
    자료     두문자마다 풀어 쓴 판시·문장. 두문자 글자가 문장 속에 빨간 굵은 글씨로 찍혀 있다
             → 노트/자료/<장>.md  (빨간 글자로 시작하는 낱말을 **굵게** — 빈칸채우기.py 의 빈칸 키)

- 2단 편집이다. 단(왼쪽 x<300 · 오른쪽)마다 위에서 아래로 읽고, 들여쓰기(10pt)를 목차 깊이로 본다.
- PDF 의 줄바꿈은 이어 붙인다. 목록 머리(`1.` `(1)` `1)` `i)` `判` `[` `<` `{` 두문자 …)로 시작하면 새 줄.
  한컴은 글자 단위로 줄을 나누므로, 앞 줄 끝(또는 다음 줄 앞에 홀로 찍힌 조각)에 빈칸이 있을 때만 띄운다.
- 빨간 글자 → 그 글자부터 어절 끝까지에서 조사·어미를 뗀 것을 굵게. 한 어절에 빨간 글자가 둘이면 한 낱말로 묶는다.
  자동으로 잡은 경계라 **손으로 다듬는다**(작업현황.md 「도쓰 자료」).
- 자료 PDF 도 장 띠(「----제3장 특허요건----」)로 나눈다. 띠 앞(제2장)은 암기장의 논점 순서로.

    python3 도쓰변환.py              노트/암기장 · 노트/자료 를 만든다 (이미 있으면 멈춘다)
    python3 도쓰변환.py --덮어쓰기    손으로 고친 것까지 덮어쓴다 — 첫 판을 다시 뽑을 때만
    python3 도쓰변환.py --세기        PDF 의 두문자·빨간 글자 수와 md 의 수를 견준다
    python3 도쓰변환.py --잇기        암기장에서 PDF 줄을 이어 붙인 자리 — 잘못 이은 곳을 손으로 가를 때

만든 뒤에는 md 를 손으로 고친다. 이 도구를 다시 돌리지 않는다.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 특허법

import fitz  # PyMuPDF

참고 = 특허법 / "참고"
암기장PDF = 참고 / "[특허] 암기장 자료 업로드 by 도쓰.pdf"
자료PDF = 참고 / "[특허] 자료 업로드 by 도쓰.pdf"
암기장 = 특허법 / "노트" / "암기장"
자료 = 특허법 / "노트" / "자료"

RED = 0xFF0000
가운데 = 300            # 이보다 오른쪽에서 시작하는 줄은 오른쪽 단
단왼쪽 = {0: 28, 1: 309}

# 암기장의 장 띠 「----------제2장 특허법상 특유쟁점----------」 → 파일 이름
장이름 = [
    ("제2장", "제2장_특허법상특유쟁점"), ("제3장", "제3장_특허요건"), ("4장", "제4장_출원제도"),
    ("제5장", "제5장_특허권및실시권"), ("제6장", "제6장_침해"), ("제7장", "제7장_심판"),
    ("제8장", "제8장_소송"), ("제9장", "제9장_PCT"), ("단문", "단문"),
]

_목록머리 = re.compile(
    r"^\s*(?:\d+\.\s|\(\d+\)|\d+\)|[ivx]+\)|判|특判|종래|최근|전합|지방|서울고법|구법|[\[<{〔(+\-－–]"
    r"|검토|학설|cf\.|ex\)|의의|요건|취지|문제|예외|원칙|※|\*|→)")
# 자료에서 앞 문장이 끝났으면 새 문단으로 여는 머리
_자료머리 = re.compile(r"^(?:判|특判|전합|종래|최근|검토|학설|[ivx]+\)|\d+\)|\d+항|[가-힣]{2,6}설\s*:|cf\.)")
_경계 = set(" \t,.)(‘’“”\"'/‧·:;!?、~[]「」<>{}=+-－–→※　")

_조사 = sorted([
    "으로서의", "으로써의", "에서부터", "으로부터", "이라는", "이라고", "에서의", "에게서", "으로서", "으로써",
    "으로는", "으로도", "으로의", "로서의", "로써의", "로부터", "까지의", "부터의", "에서는", "에서도",
    "에서", "에게", "에는", "에도", "에의", "까지", "부터", "으로", "이나", "이며", "이고", "이다", "이라",
    "라는", "라고", "로서", "로써", "로는", "로도", "로의", "과의", "와의", "과는", "와는", "과도", "와도",
    "하는", "하여", "하고", "하며", "하면", "하지", "하게", "하기", "해야", "해서", "한다", "하였",
    "되는", "되어", "되고", "되지", "된다", "되었",
    "하였다면", "하여야", "하지도", "하면서", "면서", "하다고", "해진다고", "했다면", "하는지", "하더라",
    "시키는", "시키", "시켜", "시킨", "하려는", "하려", "하던", "해서는", "되며", "되면", "되었는지", "되었다고", "되었다", "된다고", "하였다", "하거나", "되거나", "되므로", "하므로",
    "할", "될", "한", "함", "됨", "된",
    "이", "가", "을", "를", "은", "는", "에", "의", "로", "와", "과", "도", "만",
], key=len, reverse=True)
# 조사처럼 끝나지만 낱말의 일부인 것 — 자르는 자리가 이 낱말 안에 들면 자르지 않는다
_조사아님 = {
    "효과", "결과", "경과", "초과", "부과", "통과", "의의", "고의", "선의", "악의", "임의", "합의", "협의", "동의",
    "주의", "정의", "회의", "논의", "편의", "유의", "창의", "강의", "건의", "문의", "쟁의", "그대로",
    "대가", "국가", "평가", "허가", "추가", "증가", "인가", "참가", "시가", "원가", "단가", "물가",
    "용도", "순도", "정도", "제도", "한도", "태도", "의도", "인도", "양도", "명도", "과도", "속도", "강도", "밀도",
    "농도", "온도", "습도", "각도", "빈도", "경도", "점도", "시도", "진도", "신뢰도", "기여도", "지도",
    "차이", "사이", "길이", "높이", "넓이", "깊이", "아이", "경로", "회로", "통로", "진로", "미만", "사과",
    "속지주의", "원칙", "기술자", "자연인",
    "포함", "분할", "역할", "관할", "제한", "권한", "상한", "하한", "기한", "유한", "무한",
}


# ── PDF 읽기 ───────────────────────────────────────────────────────────

def 줄들(pdf):
    """PDF → [(쪽, 단, x0, x1, y, [(글자, 굵음, 빨강)])] 읽는 순서대로. 머리말(by 도쓰 …)과 그림은 빼고, 그림 자리는 표시."""
    doc = fitz.open(pdf)
    out = []
    for pno, page in enumerate(doc, 1):
        행 = []
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") == 1:                          # 그림
                x0, y0 = b["bbox"][0], b["bbox"][1]
                행.append((pno, int(x0 >= 가운데), x0, x0, y0, [("〔그림〕", False, False)]))
                continue
            for l in b.get("lines", []):
                spans = [(s["text"], bool(s["flags"] & 16), s["color"] == RED)
                         for s in l["spans"] if not s["font"].startswith("HCRDotum")]
                if not spans:
                    continue
                if not "".join(t for t, _, _ in spans).strip():
                    # 빈칸만 있는 줄 — 같은 높이에 글이 이어지면 앞 줄 끝의 띄어쓰기가 내려온 것, 아니면 빈 줄
                    행.append((pno, int(l["bbox"][0] >= 가운데), l["bbox"][0], l["bbox"][2], l["bbox"][1], []))
                    continue
                x0 = min(s["bbox"][0] for s in l["spans"] if s["text"].strip())
                단 = int(x0 >= 가운데)
                행.append((pno, 단, x0, l["bbox"][2], l["bbox"][1], spans))
        행.sort(key=lambda r: (r[1], round(r[4]), r[2]))
        out += 행
    return out


def 글자(spans):
    return "".join(t for t, _, _ in spans)


# ── 논리 줄 만들기 ─────────────────────────────────────────────────────

def 논리줄(행들, 자료판, 기록=None):
    """PDF 줄을 이어 붙여 [(단계, spans)] 로. 자료판(양쪽 맞춤 산문)은 줄이 단 끝까지 차면 잇는다."""
    out = []
    앞 = None              # (단, x1, 단계, 글자, y)
    빈칸 = None            # 빈칸만 있는 줄의 (단, y)
    for pno, 단, x0, x1, y, spans in 행들:
        if not spans:
            빈칸 = (pno, 단, round(y))
            continue
        t = 글자(spans)
        단계 = max(0, round((x0 - 단왼쪽[단]) / 10))
        첫 = t.lstrip()
        내려온빈칸 = 빈칸 is not None and 빈칸 == (pno, 단, round(y))
        빈줄 = 빈칸 is not None and not 내려온빈칸
        빈칸 = None
        if out and 앞 is not None and not 빈줄:
            p단, px1, p단계, pt = 앞
            끝 = 289 if p단 == 0 else 570
            두문자줄 = spans[0][1] and not spans[0][2] and 첫.startswith("(")
            if 자료판:
                앞두문자 = out[-1][1][0][1] and not out[-1][1][0][2] and pt.lstrip().startswith("(")
                새말 = _자료머리.match(첫) and pt.rstrip().endswith(("다", ".", ")", "”", "다."))
                잇기 = px1 >= 끝 - 14 and not 두문자줄 and not 앞두문자 and not 새말 and not 첫.startswith("<")
            else:
                잇기 = (not _목록머리.match(첫) and "〔그림〕" not in t
                       and not pt.rstrip().endswith((".", ")"))
                       and (내려온빈칸 or 단계 > p단계 and px1 >= 끝 - 50 or 단계 == p단계 and px1 >= 끝 - 25))
            if 잇기:
                s0 = out[-1][1]
                if 기록 is not None:
                    기록.append((pno, 글자(s0).rstrip(), 첫.rstrip()))
                띄움 = 내려온빈칸 or pt.endswith((" ", "　")) or t[:1] in " 　"
                if not 자료판 and px1 < 끝 - 8:
                    띄움 = True              # 암기장은 왼쪽 맞춤 — 단 끝까지 꽉 찬 줄만 낱말 중간에서 나뉜다
                while s0 and not s0[-1][0].strip():
                    s0.pop()
                if s0:
                    s0[-1] = (s0[-1][0].rstrip(), s0[-1][1], s0[-1][2])
                if 띄움:
                    s0.append((" ", False, False))
                첫조각 = True
                for tt, bb, rr in spans:
                    if 첫조각:
                        tt = tt.lstrip()
                        if not tt:
                            continue
                        첫조각 = False
                    s0.append((tt, bb, rr))
                앞 = (단, x1, p단계, t)
                continue
        out.append((단계, list(spans)))
        앞 = (단, x1, 단계, t)
    return out


# ── 빨간 글자 → 굵은 낱말 ──────────────────────────────────────────────

def 조사떼기(w):
    """낱말 → (몸, 꼬리). 조사가 겹치면(「하위개념으로까지」) 두 번까지 뗀다."""
    몸, 꼬리 = 한번떼기(w)
    if 꼬리:
        몸2, 꼬리2 = 한번떼기(몸)
        if 꼬리2 and len(몸2) >= 2:
            return 몸2, 꼬리2 + 꼬리
    return 몸, 꼬리


def 한번떼기(w):
    if w.endswith("적인") and len(w) > 2:
        return w[:-1], "인"
    for s in _조사:
        if len(w) > len(s) and w.endswith(s):
            cut = len(w) - len(s)
            if s == "도" and w[:-1].endswith(("효과", "확인", "규정", "결과")):
                return w[:cut], s        # 「효과도」 — 과도·인도·정도 가 걸쳐 있어도 조사
            if any(w.endswith(p) and len(w) - len(p) < cut for p in _조사아님) or \
               any(p in w and w.index(p) < cut < w.index(p) + len(p) for p in _조사아님):
                continue
            return w[:cut], w[cut:]
    return w, ""


def 굵게(spans, 두문자굵게=True):
    """spans → 마크다운 한 줄. 빨간 글자는 그 어절 끝까지(조사 뺌) 굵게, 검은 굵은 글씨(두문자)는 그대로 굵게."""
    # 빨간 글자 자리를 『』 로 표시한 글자열
    s = ""
    for t, b, r in spans:
        if r and len(t.strip()) > 1 and not t.strip().isdigit():
            # 빨간 글자 묶음(「전합」「MAIN 조치」「(충돌)」) — 강조라 그 묶음만 굵게
            lead = t[: len(t) - len(t.lstrip())]
            s += lead + "【" + t.strip() + "】" + t[len(t.rstrip()):]
        elif r and t.strip():
            lead = t[: len(t) - len(t.lstrip())]
            s += lead + "『" + t.strip() + "』" + t[len(t.rstrip()):]
        elif b and 두문자굵게 and t.strip():
            lead = t[: len(t) - len(t.lstrip())]
            s += lead + "【" + t.strip() + "】" + t[len(t.rstrip()):]
        else:
            s += t
    s = re.sub(r"【\s*】", "", s).replace("】【", "")
    # 빨간 글자에서 어절 끝까지
    out = []
    i = 0
    while i < len(s):
        if s[i] == "『":
            j = i
            w, 빨강끝, 안 = "", 0, False
            while j < len(s) and s[j] not in _경계 and s[j] != "【":
                if s[j] in "『』":
                    안 = s[j] == "『"
                else:
                    w += s[j]
                    if 안:
                        빨강끝 = len(w)
                j += 1
            k, 꼬리 = 조사떼기(w)
            if len(k) < 빨강끝:                 # 떼려는 꼬리에 빨간 글자가 있으면(「약리기전만으로」의 만) 그 뒤만 뗀다
                k, 꼬리 = w, ""
                for 끝말 in _조사:
                    if w.endswith(끝말) and len(w) - len(끝말) >= 빨강끝:
                        k, 꼬리 = w[: len(w) - len(끝말)], 끝말
                        break
            out.append("**" + k + "**" + 꼬리)
            i = j
            continue
        out.append(s[i])
        i += 1
    s = "".join(out)
    s = re.sub(r"【(.+?)】", lambda m: "**" + m.group(1) + "**", s)
    return s.replace("****", "")                   # 굵은 말 둘이 맞붙으면 하나로


def 이스케이프(t):
    t = t.replace("*", "\\*") if "**" not in t else re.sub(r"(?<!\*)\*(?!\*)", r"\\*", t)
    t = re.sub(r"^([+\-])(\s)", r"\\\1\2", t)
    t = re.sub(r"^(\d+)\.(\s)", r"\1\\.\2", t)
    return t


# ── 암기장 ─────────────────────────────────────────────────────────────

_머리 = re.compile(r"^-{4,}\s*(.+?)\s*-{4,}\s*$")
_논점 = re.compile(r"^<([^>]+)>\s*(.*)$")
_짧은꼬리 = re.compile(r"^(?:A|\*|\s|\([^()]{1,14}\)|\{[^}]*\})*$")
_번호 = re.compile(r"^(\d+)\.\s+(.*)$")


def 암기장md(줄):
    """논리 줄 → {장파일: [md 줄]}. 단계 0 의 `N.` 은 번호 목록, 단계 1 이상은 들여쓴 글머리 목록."""
    장들 = {}
    lines = None
    쌓기 = []              # 열린 목록 — (단계, 내용이 시작하는 칸)
    앞번호 = None          # 이어지는 번호 목록의 마지막 번호

    def 문단(t):
        nonlocal 쌓기, 앞번호
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(t)
        쌓기, 앞번호 = [], None

    for 단계, spans in 줄:
        raw = 글자(spans).strip()
        m = _머리.match(raw)
        if m:
            이름 = next(f for k, f in 장이름 if k in m.group(1))
            lines = 장들.setdefault(이름, [])
            제목 = m.group(1).strip()
            lines += [f"# 암기장 · {제목 if 제목.startswith(('제', '단')) else '제' + 제목}", ""]
            쌓기, 앞번호 = [], None
            continue
        if lines is None:
            continue
        if "〔그림〕" in raw:
            문단("<!-- 그림: 원본 PDF 에 그림이 있다 — 손으로 옮겨 적는다 -->")
            continue
        md = 굵게(spans).strip()
        m = _논점.match(md)
        if m and 단계 == 0:
            꼬리 = m.group(2).strip()
            짧다 = bool(_짧은꼬리.match(꼬리.replace("**", "")))
            문단(f"## <{m.group(1)}> {꼬리 if 짧다 else ''}".rstrip())
            lines.append("")
            if 짧다 or not 꼬리:
                continue
            md = 꼬리
        n = _번호.match(md)
        if 단계 == 0 and n and (int(n.group(1)) == 1 and 앞번호 is None
                                or 앞번호 is not None and int(n.group(1)) == 앞번호 + 1):
            if lines and lines[-1] != "" and 앞번호 is None:
                lines.append("")
            lines.append(md)
            쌓기, 앞번호 = [(0, len(n.group(1)) + 2)], int(n.group(1))
            continue
        md = 이스케이프(md)
        if 단계 == 0:
            문단(md)
            continue
        while 쌓기 and 쌓기[-1][0] >= 단계:
            쌓기.pop()
        칸 = 쌓기[-1][1] if 쌓기 else 0
        lines.append(" " * 칸 + "- " + md)
        쌓기.append((단계, 칸 + 2))
        if len(쌓기) == 1:
            앞번호 = None
    return 장들, None


# ── 자료 ───────────────────────────────────────────────────────────────

def 자료md(줄, 논점장):
    """논리 줄 → {장파일: [md 줄]}. 논점장: 정규화한 논점 이름 → 장파일 (암기장 순서)."""
    장들 = {}
    현재 = 장이름[0][1]
    lines = 장들.setdefault(현재, [])
    for _, spans in 줄:
        raw = 글자(spans).strip()
        m = _머리.match(raw)
        if m:                                       # 자료에도 장 띠가 있다 — 그것으로 나눈다
            현재 = next(f for k, f in 장이름 if k in m.group(1))
            lines = 장들.setdefault(현재, [])
            continue
        m = _논점.match(raw)
        if m and not spans[0][1]:
            키 = 정규(m.group(1))
            if 키 in 논점장:
                현재 = 논점장[키]
            lines = 장들.setdefault(현재, [])
            lines += ["", f"## <{m.group(1)}> {m.group(2)}".rstrip(), ""]
            continue
        md = 이스케이프(굵게(spans))
        lines += [md, ""]
    return 장들


def 정규(이름):
    s = re.sub(r"\s|判例|判|특허|를|의", "", 이름)
    return s


# 자료와 암기장에서 이름이 다른 논점
_별칭 = {"무효심판": "특허무효심판", "심결취소소송심리": "심결취소소송소송물및심리"}


def 쓰기(폴더, 장들, 머리, 덮어쓰기):
    폴더.mkdir(parents=True, exist_ok=True)
    for 이름, lines in 장들.items():
        p = 폴더 / f"{이름}.md"
        if p.exists() and not 덮어쓰기:
            sys.exit(f"이미 있다: {p} — 손으로 고친 판일 수 있다. 정말 다시 뽑으려면 --덮어쓰기")
        본문 = "\n".join(lines).strip("\n")
        본문 = re.sub(r"\n{3,}", "\n\n", 본문)
        if 본문.startswith("# "):
            첫, 나머지 = 본문.split("\n", 1)
        else:
            첫, 나머지 = f"# {머리} · {이름.replace('_', ' ')}", 본문
        p.write_text(첫 + "\n\n" + 안내[머리] + "\n" + 나머지.lstrip("\n") + "\n", encoding="utf-8", newline="\n")
        print(f"  {p.relative_to(특허법)}  {len(본문):,}자")


안내 = {
    "암기장": "22년 합격자 도쓰가 테마 특허법(옛 판)으로 만든 암기장을 옮긴 것이다. 장 순서는 도쓰 그대로.\n"
              "`〔26〕` 이 붙은 줄은 9판(2026) 기준으로 고친 것이고, 무엇을 왜 고쳤는지는 `작업/references/도쓰갱신.md`.\n\n"
              "<!-- 손으로 고친다. 첫 판은 작업/도구/도쓰변환.py 가 PDF 에서 옮겼다(2026-10-25). -->\n",
    "자료": "도쓰 암기장의 두문자마다 풀어 쓴 판시·문장이다. **굵은 말**이 두문자 글자로 시작하는 낱말이고,\n"
            "`빈칸채우기.py` 가 이것을 가려 연습판(`../빈칸채우기/`)을 뽑는다. `〔26〕` 은 9판 기준으로 고친 줄.\n\n"
            "<!-- 손으로 고친다. 첫 판은 작업/도구/도쓰변환.py 가 PDF 에서 옮겼다(2026-10-25). 굵은 말은 원본의 빨간 글자에서 잡았다. -->\n",
}


def 세기():
    for pdf, 폴더 in ((암기장PDF, 암기장), (자료PDF, 자료)):
        doc = fitz.open(pdf)
        두 = 빨 = 0
        for page in doc:
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l["spans"]:
                        if s["color"] == RED and s["flags"] & 16 and s["text"].strip():
                            빨 += len(s["text"].strip())
                        elif s["flags"] & 16 and s["text"].strip().startswith("("):
                            두 += 1
        md = "".join(p.read_text(encoding="utf-8") for p in sorted(폴더.glob("*.md")))
        md두 = len(re.findall(r"\*\*\([^*]+\)\*\*", md))
        md빨 = len(re.findall(r"\*\*(?!\()\S[^*]*?\*\*", md)) - md.count("**굵은 말**")
        print(f"{pdf.name}\n  PDF  두문자 조각 {두} · 빨간 글자 {빨}\n  md   굵은 두문자 {md두} · 굵은 말 {md빨}"
              "\n  (빨간 글자 하나가 낱말 하나 — 「2001」처럼 여러 글자 조각도 있어 꼭 같지는 않다. 맞춤은 빈칸채우기.py --검사)")


def main(argv):
    if "--세기" in argv:
        return 세기()
    if "--잇기" in argv:
        기록 = []
        논리줄(줄들(암기장PDF), 자료판=False, 기록=기록)
        for pno, 앞, 뒤 in 기록:
            print(f"p{pno}  …{앞[-30:]} ⏎ {뒤[:40]}")
        return
    덮어쓰기 = "--덮어쓰기" in argv
    줄 = 논리줄(줄들(암기장PDF), 자료판=False)
    장들, _ = 암기장md(줄)
    쓰기(암기장, 장들, "암기장", 덮어쓰기)
    # 암기장 논점 → 장
    논점장 = {}
    for 이름, lines in 장들.items():
        for ln in lines:
            m = re.match(r"^## <([^>]+)>", ln)
            if m:
                논점장.setdefault(정규(m.group(1)), 이름)
    for a, b in _별칭.items():
        if b in 논점장:
            논점장[a] = 논점장[b]
    줄 = 논리줄(줄들(자료PDF), 자료판=True)
    쓰기(자료, 자료md(줄, 논점장), "자료", 덮어쓰기)


if __name__ == "__main__":
    main(sys.argv[1:])
