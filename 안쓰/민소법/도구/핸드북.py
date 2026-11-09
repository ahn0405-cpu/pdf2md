#!/usr/bin/env python3
"""이창한 「2024 핸드북 진도별 민소법 기출문제」 PDF → 목차 + OCR 원문.

스캔 PDF 에 OCR 글자층이 있다(오타 있음). 이걸 읽어
    안쓰/민소법/핸드북/[민소법] 안쓰 핸드북 목차.md   차례 226사례 — 편별, 사례마다 기출 출처 · 시작 쪽 · ★ · 표준판례 수
    안쓰/민소법/OCR/핸드북/제N편.md                   사례마다 `## [사례 2-3-1] 제목 [출처]`, 쪽 `<!-- p.12 · pdf 14 -->`, 원문 줄
를 만든다. 목차는 「무엇부터 만들지」 고르는 지도이고, OCR 원문은 검색·인용용(교정 전).

    python 핸드북.py              둘 다 (이미 있으면 멈춘다)
    python 핸드북.py --덮어쓰기

강조 표시(머리말 p.3): ★ = 반드시 이해·암기, 판례번호 앞 * · [표준판례] = 표준판례, 高 = 고득점 요령.
출처: 理 변리사 · 行 행시 · 辯 변호사 · 院 법원행시 · 司 사시 · 法 법무사. ★·표준 수는 OCR 글자층으로 센 어림값이다.
차례 쪽의 노란 형광은 무시한다(사용자).
"""
import re
import sys
from collections import OrderedDict
from pathlib import Path

import fitz

fitz.TOOLS.mupdf_display_errors(False)

여기 = Path(__file__).resolve().parent
민소법 = 여기.parent
PDF = 민소법 / "원본" / "2024 핸드북 진도별 민소법 기출문제_OCR.pdf"
목차파일 = 민소법 / "핸드북" / "[민소법] 안쓰 핸드북 목차.md"
OCR폴더 = 민소법 / "OCR" / "핸드북"

차례쪽 = range(7, 12)        # pdf 8～12 (0부터)
본문첫 = 13                  # pdf 14 부터 본문
쪽차 = 2                     # 책 쪽 = pdf 쪽 - 2 (pdf 14 = p.12)
편이름 = {"2": "제2편 소송의 주체", "3": "제3편 제1심 소송절차", "4": "제4편 소송의 종료",
         "5": "제5편 병합소송", "6": "제6편 상소", "7": "제7편 재심"}
출처뜻 = {"理": "변리사", "行": "행시", "辯": "변호사", "院": "법원행시", "司": "사시", "法": "법무사"}

고침표 = [("사궤", "사례"), ("［", "["), ("］", "]"), ("，", ","), ("（", "("), ("）", ")")]


def 고치기(t):
    for a, b in 고침표:
        t = t.replace(a, b)
    return t


def 번호(b):
    b = b.strip("［］[] ")
    m = re.match(r"^(?:사\S?\s*)?([1-7]\s*-\s*\S.*)$", b)
    return re.sub(r"\s", "", m.group(1)) if m else None


def 정규(n):
    """사례 번호 비교용 — OCR 이 깨뜨린 괄호·글자를 정리."""
    return re.sub(r"[^0-9A-Za-z\-]", "", n.replace("到", "3").replace("이", "0").replace("l", "1"))


def 차례(doc):
    t = "\n".join(doc[i].get_text() for i in 차례쪽).replace("[", "［").replace("]", "］")
    t = t.replace("到", "3］").replace("］］", "］")      # OCR 이 「3]」 을 「到」 한 글자로 읽는다
    t = re.sub(r"\d+\s*I\s*차례|차례\s*■\s*\d+|제\s*\d\s*편\s*[^\n［]*", "\n", t)
    rows, cur = [], None
    for k in re.split(r"(［[^］\n]{1,20}］?)", t):
        if k.startswith("［"):
            n = 번호(k)
            if n:
                cur = {"번호": n, "제목": "", "출처": []}
                rows.append(cur)
            elif cur is not None:
                cur["출처"].append(re.sub(r"\s+", "", k.strip("［］ ")))
        elif cur is not None:
            s = re.sub(r"\s+", " ", k.replace("\n", " ")).strip(" /")
            if s:
                cur["제목"] = (cur["제목"] + " " + s).strip()
    for r in rows:
        r["제목"] = 고치기(r["제목"]).strip(" -")
    return rows


def 시작쪽(doc, rows):
    """본문에서 사례 머리 「[사례 2-3-1]」 가 있는 쪽 — 차례 번호와 맞춘다."""
    찾기 = {정규(r["번호"]): r for r in rows}
    for i in range(본문첫, doc.page_count):
        머리 = doc[i].get_text()[:400].replace("[", "［").replace("]", "］")
        for m in re.finditer(r"［\s*사\S?\s*([1-7]\s*-\s*[^］\n]{1,14})", 머리):
            k = 정규(m.group(1))
            r = 찾기.get(k) or 찾기.get(k.rstrip("A")) or next((찾기[x] for x in 찾기 if x.startswith(k) and len(x) - len(k) <= 1), None)
            if r and "pdf" not in r:
                r["pdf"] = i + 1
            break


def 세기(doc, rows):
    순 = sorted([r for r in rows if "pdf" in r], key=lambda r: r["pdf"])
    for k, r in enumerate(순):
        끝 = 순[k + 1]["pdf"] if k + 1 < len(순) else doc.page_count + 1
        t = "".join(doc[i - 1].get_text() for i in range(r["pdf"], max(r["pdf"] + 1, 끝)))
        r["끝"] = 끝 - 1
        r["★"] = t.count("★")
        r["표준"] = len(re.findall(r"표준\s*판례|\*\s*\d{2,4}\s*[.다나후마도두카]|\S\*(?=\s|$)", t))


def 목차쓰기(rows, 덮어쓰기):
    if 목차파일.exists() and not 덮어쓰기:
        sys.exit(f"이미 있다: {목차파일} — 다시 뽑으려면 --덮어쓰기")
    out = ["# [민소법] 안쓰 핸드북 목차", "",
           "이창한 「2024 핸드북 진도별 민소법 기출문제」 차례 — **무엇부터 만들지 고르는 지도**.",
           "기출: 理 변리사 · 行 행시 · 辯 변호사 · 院 법원행시 · 司 사시 · 法 법무사 (**理** 는 굵게).",
           "★ = 반드시 이해·암기, 표준 = 표준판례 표시(판례번호 앞 * · [표준판례]) — OCR 글자층으로 센 어림값.",
           "쪽 = 책 쪽(pdf 쪽 − 2). 노트를 만든 사례는 `노트` 칸에 ○.", "",
           "<!-- 도구/핸드북.py 가 2026-11-08 만들었다. 노트 칸 ○ 는 손으로 단다. -->", ""]
    편 = OrderedDict()
    for r in rows:
        편.setdefault(r["번호"][0], []).append(r)
    for k, rs in 편.items():
        out += [f"## {편이름.get(k, k)}", "", "| 사례 | 제목 | 기출 | 쪽 | ★ | 표준 | 노트 |", "|---|---|---|---|---|---|---|"]
        for r in rs:
            출처 = " ".join(f"**{x}**" if x.startswith("理") else x for x in r["출처"] if not x.startswith("사례"))
            쪽 = f"{r['pdf'] - 쪽차}" if "pdf" in r else "?"
            out.append(f"| {r['번호']} | {r['제목']} | {출처} | {쪽} | {r.get('★', '') or ''} | {r.get('표준', '') or ''} | |")
        out.append("")
    목차파일.parent.mkdir(parents=True, exist_ok=True)
    목차파일.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"{목차파일.name}  사례 {len(rows)} · 시작 쪽 찾음 {sum('pdf' in r for r in rows)}")


def 원문쓰기(doc, rows, 덮어쓰기):
    OCR폴더.mkdir(parents=True, exist_ok=True)
    시작 = {r["pdf"]: r for r in rows if "pdf" in r}
    편별 = OrderedDict()
    현재 = None
    for i in range(본문첫, doc.page_count):
        no = i + 1
        if no in 시작:
            현재 = 시작[no]
            출처 = " ".join(f"[{x}]" for x in 현재["출처"] if not x.startswith("사례"))
            편별.setdefault(현재["번호"][0], []).append(f"\n## [사례 {현재['번호']}] {현재['제목']} {출처}".rstrip())
        if 현재 is None:
            continue
        t = 고치기(doc[i].get_text()).strip()
        편별[현재["번호"][0]] += [f"\n<!-- p.{no - 쪽차} · pdf {no} -->\n", t]
    for k, lines in 편별.items():
        p = OCR폴더 / f"{편이름.get(k, k).replace(' ', '_')}.md"
        if p.exists() and not 덮어쓰기:
            sys.exit(f"이미 있다: {p}")
        머리 = (f"# 핸드북 OCR 원문 · {편이름.get(k, k)}\n\n이창한 「2024 핸드북 진도별 민소법 기출문제」의 OCR 글자층 — **교정 전 원문**(검색·인용용). "
              "노트는 `../../핸드북/`.\n\n<!-- 도구/핸드북.py 2026-11-08. 손으로 고치지 않는다. -->\n")
        p.write_text(머리 + "\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
        print(f"  {p.name}  {sum(len(x) for x in lines):,}자")


def main(argv):
    doc = fitz.open(PDF)
    rows = 차례(doc)
    시작쪽(doc, rows)
    세기(doc, rows)
    덮어쓰기 = "--덮어쓰기" in argv
    목차쓰기(rows, 덮어쓰기)
    원문쓰기(doc, rows, 덮어쓰기)


if __name__ == "__main__":
    main(sys.argv[1:])
