#!/usr/bin/env python3
"""GS OCR(gs_ocr.py 산물) → 회차별 OCR 원문 md. 교정 전 「원문」 기록이고, 노트(박형준GS/)를 쓸 재료다.

    python gs_초안.py 3          3회차
    python gs_초안.py 3 --보기   형광펜 종류를 {판 …} {조 …} {취 …} {사 …} 로 보여 준다(교정용, 파일은 안 씀)

- 쪽마다 `<!-- p.N -->`. 문제 쪽은 「N회차 · 문제-k」 머리와 지문·물음, 해설 쪽은 키워드 상자 줄 → 설문 → 번호 목차 → 본문.
- 살구(판례) 형광펜이 칠해진 낱말은 **굵게**. 노랑(번호 목차 머리)은 줄 앞 `#### `.
- 확실한 OCR 오류만 표로 고친다(法 · 判例 · 원문자 ①② · 「있디」 → 「있다」 · 「기능하」 → 「가능하」 · 「제2회」 → 「제2호」 …).
  나머지는 노트로 옮길 때 쪽 그림을 보고 고친다.
"""
import json
import re
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
특허법 = 여기.parent
작업 = 특허법.parent / "_work" / "박형준"
출력 = 특허법 / "OCR" / "박형준GS"

약칭 = {"판례": "판", "조문": "조", "취지": "취", "사안": "사"}

고침표 = [
    (r"[;:i7l1]?去", "法"),
    (r"(?:月|半|劣|判)[^\s가-힣()]{1,6}(?=[\s).,]|$)", "判例"),
    (r"判\{列|判列|判例\]", "判例"),
    (r"(항|조|호)\s*제(\d+)회", r"\1 제\2호"),
    (r"제(\d+)회(?=[).,\s]|$)", r"제\1호"),
    (r"([가-힣])디(?=[.(〈)\s]|$)", r"\1다"),
    (r"([가-힣])대(?=[i;7]?法|\(法)", r"\1다("),
    (r"불기능", "불가능"),
    (r"기능하", "가능하"),
    (r"등록 기능", "등록 가능"),
    (r"〈", "("),
    (r"〉", ">"),
    (r"\(0 ", "(i) "),
    (r"핀단", "판단"),
    (r"심핀", "심판"),
    (r"띠라[서세]", "따라서"),
    (r"(?<=[\s(])시안(?=[\s)]|$)", "사안"),
    (r"정당권리지", "정당권리자"),
    (r"기쁠", "기별"),
    (r"신정", "신청"),
    (r"기긴", "기간"),
    (r"\)\(", "X"),
    (r"(?<=\s)X(?=[를의는가이에])", "X"),
]
_원문자 = re.compile(r"[㉠-㉿]")          # ㉠～㉿ — OCR 이 ①② 를 이렇게 읽는다


def 고치기(t):
    for a, b in 고침표:
        t = re.sub(a, b, t)
    return t


def 원문자(lines):
    """줄 머리·문장 안의 ㉦㉣㉭ 류를 단락 안 순서대로 ①②③."""
    out, n = [], 0
    for t in lines:
        if not _원문자.search(t):
            if re.match(r"^(?:\d+\.|\(\d+\)|[ⅠⅡⅢⅣⅤⅰⅱⅲⅳⅴ]|####)", t):
                n = 0
            out.append(t)
            continue

        def 바꿈(m):
            nonlocal n
            n += 1
            return "①②③④⑤⑥⑦⑧⑨⑩"[min(n, 10) - 1]
        out.append(_원문자.sub(바꿈, t))
    return out


def 쪽읽기(no, 보기=False):
    d = json.loads((작업 / f"p{no:03d}.json").read_text(encoding="utf-8"))
    hl = json.loads((작업 / f"p{no:03d}.hl.json").read_text(encoding="utf-8"))["형광"]

    def 색(w):
        cx, cy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
        for r in hl:
            if r["x0"] - 2 <= cx <= r["x1"] + 2 and r["y0"] - 2 <= cy <= r["y1"] + 2:
                return r["색"]
        return None

    lines = []
    for l in d["lines"]:
        ws = l["words"]
        if not ws:
            continue
        if re.fullmatch(r"\d{1,3}", l["text"].strip()) and ws[0]["y"] > 2700:
            continue                                        # 쪽 번호
        조각, 앞색 = [], None
        머리 = False
        for w in ws:
            c = 색(w)
            if c in ("머리", "머리2"):
                머리 = True
                c = None
            if 보기:
                if c != 앞색:
                    if 앞색:
                        조각.append("}")
                    if c:
                        조각.append("{" + 약칭.get(c, c) + " ")
                조각.append(w["t"] + " ")
            else:
                if c == "판례" and 앞색 != "판례":
                    조각.append("**")
                elif c != "판례" and 앞색 == "판례":
                    if 조각:
                        조각[-1] = 조각[-1].rstrip()
                    조각.append("** ")
                조각.append(w["t"] + " ")
            앞색 = c
        if 앞색 and 보기:
            조각.append("}")
        if 앞색 == "판례" and not 보기:
            조각[-1] = 조각[-1].rstrip()
            조각.append("**")
        t = re.sub(r"\s+", " ", "".join(조각)).strip()
        t = re.sub(r"\*\*\s+", "**", t) if t.startswith("**") else t
        t = 고치기(t)
        lines.append(("#### " if 머리 else "") + t)
    return 원문자(lines)


def 회차쪽(회):
    """그 회차의 쪽 번호 목록 — 「N회차」 머리가 있는 문제 쪽부터 다음 회차 문제 쪽 전까지."""
    쪽들, 안 = [], False
    for p in sorted(작업.glob("p*.json")):
        if p.name.endswith(".hl.json"):
            continue
        no = int(p.stem[1:])
        d = json.loads(p.read_text(encoding="utf-8"))
        첫 = d["lines"][0]["text"] if d["lines"] else ""
        m = re.match(r"^\s*(\d+)\s*회차", 첫)
        if m:
            안 = int(m.group(1)) == 회
        if 안:
            쪽들.append(no)
    return 쪽들


def main(argv):
    회 = int(argv[0])
    보기 = "--보기" in argv
    쪽들 = 회차쪽(회)
    if not 쪽들:
        sys.exit(f"{회}회차 쪽을 못 찾았다 — gs_ocr.py 로 그 범위를 먼저 OCR 한다")
    out = [f"# 박형준 기초 GS · {회}회차 — OCR 원문", "",
           "Windows OCR 로 옮긴 **교정 전 원문**이다. 오타가 남아 있다 — 노트는 `../../박형준GS/`.",
           "**굵은 말** = 살구색(판례) 형광펜. `####` = 노란 번호 목차 머리.", "",
           f"<!-- gs_초안.py 2026-11-08 · 쪽 {쪽들[0]}～{쪽들[-1]} -->", ""]
    for no in 쪽들:
        out += [f"<!-- p.{no} -->", ""] + [x for t in 쪽읽기(no, 보기) for x in (t, "")]
    본문 = "\n".join(out)
    if 보기:
        print(본문)
        return
    출력.mkdir(parents=True, exist_ok=True)
    p = 출력 / f"{회:02d}회.md"
    p.write_text(re.sub(r"\n{3,}", "\n\n", 본문).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"{p}  쪽 {len(쪽들)}  {len(본문):,}자")


if __name__ == "__main__":
    main(sys.argv[1:])
