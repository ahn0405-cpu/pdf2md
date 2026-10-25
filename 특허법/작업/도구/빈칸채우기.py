#!/usr/bin/env python3
"""도쓰 자료(`노트/자료/*.md`)의 두문자 풀이에서 굵은 말을 가린 연습판을 뽑는다.

자료는 두문자 줄 `**(약속의용/용시)**` 아래에 그 풀이 문장을 두고, 두문자 글자로 시작하는 낱말을 **굵게** 해 두었다
(원본 PDF 의 빨간 글자). 이 도구는 두문자는 그대로 보이고 굵은 말만 ❶(＿＿) 로 가린다 — 두문자가 실마리다.

- ＿ 하나가 한 글자. 띄어쓰기와 ‧ · 같은 기호는 빈칸 안에 그대로 둔다. 굵은 말 밖의 조사는 원래 보인다.
- 빈칸 번호는 두문자 하나마다 ❶ 부터. 정답은 논점 끝 `### 정답` 에 두문자별로.
- 민소법 빈칸채우기(`민소법/작업/도구/빈칸채우기.py`)와 같은 모양이지만, 거기는 암기노트의 `▸` 문장이 재료라 따로 둔다.

    python3 빈칸채우기.py              자료 전부 → 노트/빈칸채우기/
    python3 빈칸채우기.py 제6장         그 장만 (파일 이름 앞부분)
    python3 빈칸채우기.py --검사        두문자 글자 ↔ 굵은 말 머리글자 · 15자 넘는 굵은 말 · 굵은 말 없는 두문자
                                       (원본의 빨간 표시가 두문자와 다르면 두문자 줄에 `<!-- 원본대로: 이유 -->` — 넘긴다)

**뽑은 파일을 손으로 고치지 않는다** — 다시 뽑으면 덮어쓴다. 고칠 것은 자료에서 고친다.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from 경로 import 자료, 빈칸채우기, 상대

빈칸상한 = 15
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_논점 = re.compile(r"^## <([^>]+)>")


def 번호표(k):
    if k <= 10:
        return chr(0x2775 + k)          # ❶ … ❿
    if k <= 20:
        return chr(0x24EB + k - 11)     # ⓫ … ⓴
    return f"({k})"


def 두문자줄(l):
    """두문자 줄이면 두문자 글자들(괄호 안, / 와 빈칸 뺌)을, 아니면 None.
    줄의 굵은 말이 모두 `(…)` 이고 그 밖의 글이 짧으면(「전합判 **(특기/…)**」) 두문자 줄이다."""
    l = re.sub(r"<!--.*?-->", "", l)
    굵은 = _BOLD.findall(l)
    if not 굵은 or not all(re.fullmatch(r"\([^()]+\)(?:\s*\([^()]+\))*", g.strip()) for g in 굵은):
        return None
    if len(_BOLD.sub("", l).strip()) > 25:
        return None
    return "".join(re.sub(r"[()/\s]", "", g) for g in 굵은)


def 맞추기(글자들, 굵은말, 문단들=None):
    """두문자 글자를 굵은 말에 차례로 맞춘다 → 어긋난 곳 설명 목록(비면 맞음).
    굵은 말 하나는 머리글자로 한 글자를 먹고, 다른 방법이 없을 때만 안의 글자로 더 먹는다(「창작표현」 → 창·표)."""
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def 된다(i, j):                     # 글자 i… 를 굵은 말 j… 로 덮을 수 있나
        if j == len(굵은말):
            return i == len(글자들)
        w = 굵은말[j]
        if i >= len(글자들) or w[0] != 글자들[i]:
            return False
        if 된다(i + 1, j + 1):
            return True
        k, 먹은 = i + 1, 0
        for ch in w[1:]:                 # 안의 글자로 더 먹는 경우
            if k < len(글자들) and ch == 글자들[k]:
                k += 1
                if 된다(k, j + 1):
                    return True
        return False

    if 된다(0, 0):
        return []
    if 문단들 and len(문단들) > 1 and all(not 맞추기(글자들, d) for d in 문단들 if d):
        return []                        # 같은 두문자 아래 판시가 둘 — 문단마다 두문자 전체를 다시 쓴다
    # 어디서 어긋나는지 — 머리글자만으로 앞에서부터 대 본다
    for j, w in enumerate(굵은말):
        if j >= len(글자들):
            return [f"남는 굵은 말 「{'」「'.join(굵은말[j:])}」"]
        if w[0] != 글자들[j]:
            return [f"{j + 1}번째 굵은 말 「{w}」 ↔ 두문자 글자 「{글자들[j]}」 (두문자 {글자들} · 굵은 말 {len(굵은말)}개)"]
    return [f"두문자 「{글자들[len(굵은말):]}」 에 맞는 굵은 말이 없다"]


def 장쓰기(파일):
    """자료 한 장 → (빈칸채우기 글, 보고). 보고 = [(종류, 행, 내용)]."""
    L = 파일.read_text(encoding="utf-8").split("\n")
    제목 = re.sub(r"^#\s*자료\s*·\s*", "", L[0])
    w = [f"# 빈칸채우기 · {제목}", "",
         "도쓰 자료의 두문자 풀이에서 **굵은 말**을 가린 연습판입니다. 두문자를 실마리로 낱말을 떠올립니다.",
         "＿ 하나가 한 글자, 조사는 빈칸 밖에 그대로 두었습니다. 정답은 각 논점 끝에 있습니다.",
         "", "<!-- 빈칸채우기.py 가 자료에서 뽑은 것이다. 손으로 고치지 말고 자료를 고친 뒤 다시 뽑는다. -->", ""]
    보고, 답 = [], []
    지금 = None                # (두문자 원문, 글자들, 첫 행, [굵은 말], [[문단마다 굵은 말]])
    # 머리말(제목·안내·주석) 다음부터 — 단문처럼 논점 머리(## <…>) 없이 시작하는 장도 있다
    본문시작 = next((i + 1 for i, l in enumerate(L) if l.startswith("<!--") and l.rstrip().endswith("-->")), 1)

    def 두문자닫기():
        nonlocal 지금
        if 지금:
            원문, 글자들, 행, 굵은, 문단들 = 지금
            if "원본대로" in L[행 - 1]:
                pass                     # 원본의 빨간 표시가 두문자와 다른 것 — 두문자 줄에 이유를 달아 두었다
            elif not 굵은:
                보고.append(("굵은말없음", 행, 원문))
            else:
                for t in 맞추기(글자들, tuple(굵은), [tuple(d) for d in 문단들]):
                    보고.append(("두문자", 행, f"{원문}  {t}"))
                답.append((원문, 굵은))
        지금 = None

    def 정답쓰기():
        두문자닫기()
        if 답:
            w.extend(["", "### 정답", ""] +
                     [f"- {원문}　" + "　".join(f"{번호표(i)} {d}" for i, d in enumerate(굵은, 1)) for 원문, 굵은 in 답] + [""])
        답.clear()

    for k, l in enumerate(L[본문시작:], 본문시작 + 1):
        if _논점.match(l) or l.startswith("# "):
            정답쓰기()
            w.append(l)
            continue
        글자들 = 두문자줄(l)
        if 글자들 is not None:
            두문자닫기()
            지금 = (" ".join(g.strip() for g in _BOLD.findall(re.sub(r"<!--.*?-->", "", l))), 글자들, k, [], [])
            w.append(l)
            continue
        if 지금 is None or "**" not in l:
            w.append(l)
            continue
        굵은 = 지금[3]
        지금[4].append([m.group(1).strip() for m in _BOLD.finditer(l)])

        def 바꿈(m):
            d = m.group(1).strip()
            굵은.append(d)
            if len(re.sub(r"[\s‧·]", "", d)) > 빈칸상한:
                보고.append((f"{len(d)}자", k, d))
            return f"{번호표(len(굵은))}({re.sub(r'[가-힣A-Za-z0-9]', '＿', d)})"

        w.append(_BOLD.sub(바꿈, l))
    정답쓰기()
    return "\n".join(w).rstrip("\n") + "\n", 보고


def main():
    인자 = sys.argv[1:]
    모름 = [a for a in 인자 if a.startswith("-") and a != "--검사"]
    if 모름:
        sys.exit(f"모르는 옵션: {' '.join(모름)} (--검사 만 있다)")
    검사 = "--검사" in 인자
    고른 = [a for a in 인자 if not a.startswith("--")]
    파일들 = [p for p in sorted(자료.glob("*.md")) if not 고른 or any(p.name.startswith(g) for g in 고른)]
    if not 파일들:
        sys.exit(f"자료가 없다: {자료}")
    for 파일 in 파일들:
        글, 보고 = 장쓰기(파일)
        빈 = len(re.findall(r"[❶-❿⓫-⓴]\(|\(\d+\)\(", 글))
        if 검사:
            for 종류, 행, 내용 in 보고:
                print(f"  {상대(파일)}:{행}  {종류}  {내용}")
            print(f"{파일.stem}  빈칸 {빈}  ·  보고 {len(보고)}")
            continue
        빈칸채우기.mkdir(parents=True, exist_ok=True)
        out = 빈칸채우기 / 파일.name
        out.write_text(글, encoding="utf-8", newline="\n")
        print(f"{파일.stem:20}  빈칸 {빈:4}  → {상대(out)}")


if __name__ == "__main__":
    main()
