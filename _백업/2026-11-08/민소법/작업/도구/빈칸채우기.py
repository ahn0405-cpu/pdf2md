#!/usr/bin/env python3
"""암기노트(`노트/암기노트/CH08_변론.md`)의 답안 문장에서 굵은 말을 가린 연습판을 뽑는다.

노트 구조(2026-10-20): 단권화(이해) · 목차집(기본서 요약) · **암기노트**(사례집을 보며 만든 답안 순서 +
압축 문장, 손으로 쓴다) · **빈칸채우기**(이 도구가 암기노트에서 뽑는다).

- 암기노트를 그대로 옮기고, 단계 아래 `▸` 문장의 `**굵은 말**` 만 ❶(＿＿) 로 바꾼다. 단계 줄의 굵은 표시는 강조라 그대로 둔다.
  (`▸` 줄은 단계 줄의 이어지는 줄이라 화면·인쇄에서는 단계 줄에 붙어 한 문단이 된다 — 2026-10-22 `>` 인용 상자에서 바꿈)
- 빈칸에는 굵은 말의 글자마다 ＿ 를 두되, 띄어쓰기와 조사·기능어(것·수·경우 …)는 그대로 둔다.
- 빈칸 번호는 `▸` 묶음(이어진 `▸` 줄)마다 ❶ 부터. 정답은 논점 끝 `## NNN 정답` 에 `{template} 자리` 와 함께.

    python3 빈칸채우기.py 08         그 장만
    python3 빈칸채우기.py            암기노트가 있는 장 전부
    python3 빈칸채우기.py --검사 08  문장 없는 단계 · 15자 넘는 굵은 말 · 기호가 든 굵은 말 · 확인 목록(<!-- 확인: … -->)

**뽑은 파일을 손으로 고치지 않는다** — 다시 뽑으면 덮어쓴다. 고칠 것은 암기노트에서 고친다.
"""
import re
import sys

from 경로 import 암기노트, 빈칸채우기, 장

빈칸상한 = 15
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_템플릿머리 = re.compile(r"^\*\*\{(.+?)\}\*\*")
_단계 = re.compile(r"^(\s*)(?:-\s*)?(?:(설문\s*\S+)$|(\d+)\.\s|\((\d+)\))")
_포섭 = re.compile(r"문제의 소재|사안해결|^\s*(?:-\s*)?\(\d+\)\s*사안\s*$|^\s*-\s*설문")


def 번호표(k):
    if k <= 10:
        return chr(0x2775 + k)          # ❶ … ❿
    if k <= 20:
        return chr(0x24EB + k - 11)     # ⓫ … ⓴
    return f"({k})"


def 진단자수(답):
    """15자 상한을 잴 때의 자수 — 진단.py · 검사.py 와 같은 규칙."""
    return len(re.sub(r"[`\[\]()·,/…\s>▸\n]", "", 답))


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


def 빈칸(글, 시작=0):
    """굵은 말을 ❶(＿＿) 로 바꾸고 정답 목록을 함께 돌려준다. 시작 = 이 묶음에서 앞 줄까지 쓴 번호."""
    정답 = []

    def 바꿈(m):
        답 = re.sub(r"\s+", " ", m.group(1)).strip()
        끝 = re.search(r"[.,]$", 답)                  # 「…아니다.」의 마침표는 빈칸 밖으로
        답 = 답.rstrip(".,")
        정답.append(답)
        return f"{번호표(시작 + len(정답))}({' '.join(칸(w) for w in 답.split(' '))})" + (끝.group(0) if 끝 else "")

    return _BOLD.sub(바꿈, 글), 정답


def 깊이(l):
    return len(l) - len(l.lstrip())


class 자리셈:
    """template 안 단계 줄마다 자리 이름(`2.(1)` · `설문2 3.`)."""

    def __init__(self):
        self.설문 = self.큰 = ""

    def 다음(self, l):
        m = _단계.match(l)
        if not m:
            return None
        if m.group(2):
            self.설문, self.큰 = m.group(2).replace(" ", "") + " ", ""
            return self.설문.strip()
        if m.group(3):
            self.큰 = m.group(3) + "."
            return self.설문 + self.큰
        return self.설문 + self.큰 + f"({m.group(4)})"


def 장쓰기(파일):
    """암기노트 한 장 → (빈칸채우기 글, 보고). 보고 = [(종류, 논점, 내용)]."""
    L = 파일.read_text(encoding="utf-8").split("\n")
    w = [f"# 빈칸채우기 · {re.sub(r'^#\s*(?:암기노트|템플릿)\s*·\s*', '', L[0])}", "",
         "암기노트의 답안 문장에서 **굵은 말**을 빈칸으로 가린 연습판입니다. ＿ 하나가 한 글자이고,",
         "띄어쓰기와 조사(을·를·에·의 …)·「것·수·경우」는 빈칸 안에 그대로 두었습니다. 정답은 각 논점 끝에 있습니다.",
         "", "<!-- 빈칸채우기.py 가 암기노트에서 뽑은 것이다. 손으로 고치지 말고 암기노트를 고친 뒤 다시 뽑는다. -->", ""]
    보고, 답 = [], []
    논점 = 짧은 = None
    단계줄 = []                          # 이 template 의 (줄 번호, 자리, 문장 있음)
    셈, 묶음번호, 지금자리, 문장있는틀 = 자리셈(), 0, "", False
    주석 = False

    def 정답쓰기():
        if 논점 and 답:
            w.extend(["", f"## {논점} 정답", ""] +
                     [f"- {이름}　" + "　".join(f"{번호표(i)} {d}" for i, d in enumerate(정답, 1)) for 이름, 정답 in 답] + [""])
        답.clear()

    def 틀닫기():
        if 문장있는틀:
            for i, (k, 자리, 있음) in enumerate(단계줄):
                잎 = i + 1 >= len(단계줄) or 깊이(L[단계줄[i + 1][0]]) <= 깊이(L[k])
                if 잎 and not 있음 and not _포섭.search(L[k]):
                    보고.append(("문장없음", 논점, f"{{{짧은}}} {자리}  {L[k].strip()[:40]}"))
        단계줄.clear()

    시작 = next((i for i, l in enumerate(L) if l.strip() == "---"), 0)   # 머리말(첫 --- 앞)은 새로 썼다
    for k, l in enumerate(L[시작:], 시작):
        s = l.strip()
        if 주석 or s.startswith("<!--"):
            for m in re.finditer(r"확인:\s*(.+?)\s*(?:-->|$)", s):       # 판단으로 메운 자리 — --검사 가 모아 보여 준다
                보고.append(("확인", 논점, m.group(1)))
            주석 = "-->" not in s
            continue
        if m := re.match(r"^# (\d{3})", l):
            틀닫기(); 정답쓰기()
            논점, 짧은, 문장있는틀 = m.group(1), None, False
            w.append(l)
            continue
        if m := _템플릿머리.match(s):
            틀닫기()
            짧은 = re.sub(r"\s*template$", "", m.group(1))
            셈, 문장있는틀, 지금자리 = 자리셈(), False, ""
            w.append(l)
            continue
        if s.startswith("▸"):
            if 짧은 is None:
                w.append(l)
                continue
            이어짐 = 묶음번호 > 0             # 같은 묶음의 다음 줄 — 번호를 이어 센다
            새, 정답 = 빈칸(l, 묶음번호)
            묶음번호 += len(정답)
            if 정답:
                if 이어짐 and 답 and 답[-1][0] == f"{{{짧은}}} {지금자리}":
                    답[-1][1].extend(정답)
                else:
                    답.append((f"{{{짧은}}} {지금자리}", list(정답)))
                for d in 정답:
                    if 진단자수(d) > 빈칸상한:
                        보고.append((f"{진단자수(d)}자", 논점, d))
                    if re.search(r"[×○→/]", d) or re.match(r"(?:그|위|이)\s", d):   # 기호·지시어는 굵은 범위 밖
                        보고.append(("굵게?", 논점, d))
            if 단계줄:
                단계줄[-1] = (단계줄[-1][0], 단계줄[-1][1], True)
            문장있는틀 = True
            w.append(새)
            continue
        묶음번호 = 0
        if 짧은 and s:
            자리 = 셈.다음(l)
            if 자리 is not None:
                지금자리 = 자리
                단계줄.append((k, 자리, False))
        elif 짧은 and not s:                # template 은 빈 줄에서 끝난다
            틀닫기()
            짧은 = None
        w.append(l)
    틀닫기(); 정답쓰기()
    return "\n".join(w).rstrip("\n") + "\n", 보고


def main():
    인자 = sys.argv[1:]
    모름 = [a for a in 인자 if a.startswith("-") and a != "--검사"]
    if 모름:
        sys.exit(f"모르는 옵션: {' '.join(모름)} (--검사 만 있다)")
    검사 = "--검사" in 인자
    고른 = [a.zfill(2) for a in 인자 if not a.startswith("--")]
    대상 = [(번, 이름) for 번, 이름, _, _ in 장 if not 고른 or 번 in 고른]
    합 = 0
    for 번, 이름 in 대상:
        파일 = next(iter(sorted(암기노트.glob(f"CH{번}_*.md"))), None)
        if not 파일:
            if 고른:
                print(f"CH{번}: 암기노트가 없다 ({암기노트})")
            continue
        글, 보고 = 장쓰기(파일)
        빈 = len(re.findall(r"[❶-❿⓫-⓴]\(", 글))
        합 += 빈
        if 검사:
            for 종류, 논점, 내용 in 보고:
                print(f"  {종류:6} {논점}  {내용}")
            print(f"CH{번} {이름}  빈칸 {빈}  ·  보고 {len(보고)}")
            continue
        빈칸채우기.mkdir(parents=True, exist_ok=True)
        out = 빈칸채우기 / 파일.name
        out.write_text(글, encoding="utf-8", newline="\n")
        print(f"CH{번} {이름:14}  빈칸 {빈:4}  → 빈칸채우기/{out.name}")


if __name__ == "__main__":
    main()
