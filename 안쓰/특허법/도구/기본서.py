#!/usr/bin/env python3
"""준특허법(박형준 기본서) PDF → 장별 md + 줄 색인. 검색·인용용 원문을 한 번 만든다.

ABBYY 로 스캔한 PDF 라 숨은 OCR 글자층(글자마다 상자)이 있다. 굵기·색 정보는 없어서
**두음(굵은 첫 글자)** 은 쪽 그림(400dpi)에서 글자 상자마다 **획 굵기**(검은 화소 가로 연속 길이의 평균)를 재어 가린다:
같은 글자의 책 전체 중앙값보다 `문턱`(1.4)배 이상이고 `최소폭`(4.6px) 이상이면 굵음.
(잉크 농도는 글자 상자가 낱말 상자를 고르게 나눈 것이라 어긋나 쓸 수 없었다. 실측 p.21·p.33: 굵음 4.7～9.1 / 보통 2.7～4.5)

    python 기본서.py              md 와 색인을 만든다 (이미 있으면 멈춘다)
    python 기본서.py --덮어쓰기
    python 기본서.py --쪽 33      한 쪽만 화면에 (굵음 판정 확인용)

출력
    안쓰/특허법/OCR/준특허법/NN장_<제목>.md    절 `## 2.3.1 제목`, 쪽 `<!-- p.22 · pdf 33 -->`, 두음 낱말 **굵게**
    안쓰/_work/준특허법/줄.json            줄마다 {pdf, 쪽, 절, 글, 굵은자리} — 대응.py 가 쓴다
    안쓰/_work/준특허법/기준.json          글자별 획 굵기 중앙값(다시 쓸 때 재지 않음)

OCR 오타는 확실한 것만 고친다(원문자 표시 ®@G CD → ①②③ 순서, 判殊I → 判例, 댜 → 다, 숫자 사이 빈칸).
나머지(시성 → 사상 같은)는 쓸 때 쪽 그림을 보고 고친다.
"""
import json
import re
import statistics
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import fitz

fitz.TOOLS.mupdf_display_errors(False)

여기 = Path(__file__).resolve().parent
특허법 = 여기.parent
안쓰 = 특허법.parent
PDF = 특허법 / "원본" / "준특허법.pdf"
출력 = 특허법 / "OCR" / "준특허법"
작업 = 안쓰 / "_work" / "준특허법"

sys.path.insert(0, str(안쓰.parent / "도쓰"))
from 도쓰변환 import 굵게  # noqa: E402  빨간 글자 → 어절 끝까지(조사 뗌) 굵게 — 두음 글자를 「빨강」으로 넘긴다

DPI = 400
Z = DPI / 72
문턱 = 1.4
최소폭 = 4.6
검정 = bytes((1 if v < 140 else 0) for v in range(256))
_런 = re.compile(rb"+")
쪽끝 = 685             # 이보다 아래는 쪽 번호·머리말
앞부분 = 11            # pdf 1～11 쪽: 표지·머리말·차례

_한글 = re.compile(r"[가-힣]")
_표시 = re.compile(r"^(?:®|@）|@\)|@|©|G\)|G|CD|\(j\)|0\))\s*")
_머리 = re.compile(r"^(?:\d+(?:-\d+)?\.\s|\(\d+(?:-\d+)?\)|\d+\)|[①-⑳]|[IVX]+\.)")


# ── 글자 잉크 ──────────────────────────────────────────────────────────

def 쪽글자(page):
    """쪽 → [줄] , 줄 = {y, x0, x1, size, chars: [(글자, 획 굵기)]} . 쪽 끝(머리말)은 뺀다.
    재는 데 오래 걸려(쪽당 수 초) `_work/준특허법/쪽/p###.json` 에 남겨 두고 다시 쓴다."""
    캐시 = 작업 / "쪽" / f"p{page.number + 1:03d}.json"
    if 캐시.exists():
        return [dict(r, chars=[tuple(c) for c in r["chars"]]) for r in json.loads(캐시.read_text(encoding="utf-8"))]
    합 = _쪽글자(page)
    캐시.parent.mkdir(parents=True, exist_ok=True)
    캐시.write_text(json.dumps(합, ensure_ascii=False), encoding="utf-8", newline="\n")
    return 합


def _쪽글자(page):
    pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
    W, H, S = pix.width, pix.height, pix.samples.translate(검정)
    줄 = []
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            cs = [c for s in l["spans"] for c in s["chars"]]
            if not "".join(c["c"] for c in cs).strip():
                continue
            if l["bbox"][1] > 쪽끝:
                continue
            글 = []
            for c in cs:
                if not c["c"].strip():
                    글.append((c["c"], 0.0))
                    continue
                x0, y0, x1, y1 = (int(v * Z) for v in c["bbox"])
                x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
                런 = []
                for y in range(y0, y1):
                    런 += [m.end() - m.start() for m in _런.finditer(S[y * W + x0:y * W + x1])]
                런 = [r for r in 런 if r <= Z * 2.5]          # 긴 가로획은 빼고 세로획 굵기만
                글.append((c["c"], sum(런) / len(런) if 런 else 0.0))
            size = max(s["size"] for s in l["spans"])
            줄.append({"y": l["bbox"][1], "x0": l["bbox"][0], "x1": l["bbox"][2], "size": size, "chars": 글})
    줄.sort(key=lambda r: (round(r["y"] / 4), r["x0"]))
    # 같은 높이에 나란히 찍힌 조각은 한 줄로
    합 = []
    for r in 줄:
        if 합 and abs(합[-1]["y"] - r["y"]) < 4 and r["x0"] > 합[-1]["x1"] - 2:
            p = 합[-1]
            p["chars"] += [(" ", 0.0)] + r["chars"]
            p["x1"] = max(p["x1"], r["x1"])
            p["size"] = max(p["size"], r["size"])
        else:
            합.append(r)
    return 합


def 기준표(doc):
    p = 작업 / "기준.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    통 = defaultdict(list)
    for i in range(앞부분 + 9, doc.page_count, 9):
        for r in 쪽글자(doc[i]):
            for ch, v in r["chars"]:
                if v > 0:
                    통[ch].append(v)
    기준 = {ch: statistics.median(v) for ch, v in 통.items() if len(v) >= 5 and statistics.median(v) > 0}
    작업.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(기준, ensure_ascii=False), encoding="utf-8", newline="\n")
    return 기준


_번호머리 = re.compile(r"^\s*(?:\d+(?:\s*-\s*\d+)?\s*\.\s|\(\s*\d+(?:\s*-\s*\d+)?\s*\)|\d+\s*\))")


def 굵은자리(chars, 기준):
    """두음 글자 자리. 번호 머리 줄(`1.` `(1)` `1)` — 굵은 글꼴)과, 한글의 35% 넘게 굵은 줄은 두음이 아니다."""
    if _번호머리.match("".join(c for c, _ in chars)):
        return []
    한 = [i for i, (ch, _) in enumerate(chars) if _한글.match(ch)]
    자리 = [i for i in 한 if chars[i][0] in 기준 and chars[i][1] >= 최소폭
          and chars[i][1] / 기준[chars[i][0]] >= 문턱]
    if 한 and len(자리) > 0.35 * len(한):
        return []
    return 자리


# ── 차례 ───────────────────────────────────────────────────────────────

def 차례(doc):
    """pdf 5～11 쪽 → (장 [(번호, 제목)], 절 [(번호, 제목)])."""
    장, 절 = [], []
    대기 = None
    for i in range(4, 앞부분):
        for l in doc[i].get_text().split("\n"):
            l = l.strip()
            if not l:
                continue
            m = re.match(r"(?i)^chapter\s*(\d+)$", l)
            if m:
                대기 = int(m.group(1))
                continue
            if 대기 is not None:
                장.append((대기, l))
                대기 = None
                continue
            m = re.match(r"^(\d+\s*\.\s*\d+(?:\s*\.\s*\d+)?)\s*\.?\s*(\S.*?)\s*[✓*★J]?\s*$", l)
            if m:
                절.append((re.sub(r"\s", "", m.group(1)).rstrip("."), m.group(2).strip()))
    return 장, 절


def 정규(t):
    return re.sub(r"[\s✓*★·‧'‘’\"“”().,\-–—_]", "", t)


def 절찾기(제목, 절):
    k = 정규(제목)
    best, 점 = None, 0.0
    for 번호, t in 절:
        r = SequenceMatcher(None, k, 정규(t)).ratio()
        if r > 점:
            best, 점 = (번호, t), r
    return best if 점 >= 0.6 else None


# ── 고치기 ─────────────────────────────────────────────────────────────

def 고치기(t):
    t = re.sub(r"判[^\s例]{1,3}(?=[는의에이가를도은와])", "判例", t)
    t = t.replace("댜", "다")
    t = re.sub(r"(?<=\d) (?=\d)", "", t)
    t = re.sub(r"法\s*제", "法 제", t)
    return t


# ── 쪽 → md 줄 ─────────────────────────────────────────────────────────

def 쪽번호(page):
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if l["bbox"][1] > 쪽끝 and re.fullmatch(r"\d{1,3}", t):
                return int(t)
    return None


def 만들기(doc, 기준, 장목록, 절목록):
    장파일 = defaultdict(list)       # 장 번호 → md 줄
    색인 = []
    지금절 = ("", "")
    지금장 = 1
    for i in range(앞부분, doc.page_count):
        page = doc[i]
        줄 = 쪽글자(page)
        if not 줄:
            continue
        쪽 = (i + 1) - 앞부분                     # 책 쪽 = pdf 쪽 - 11 (p.10 = pdf 21, p.22 = pdf 33, p.240 = pdf 251 확인)
        첫 = 줄[0]
        첫글 = "".join(c for c, _ in 첫["chars"]).strip()
        if re.match(r"(?i)^chapte", 첫글):                 # 장 표지 — 절 목록만 있다
            continue
        out = 장파일[지금장]
        if 첫["y"] < 72 and 첫["x0"] > 100 and not 첫글.startswith("<"):
            찾 = 절찾기(re.sub(r"<[^>]*>?|田.*$", "", 첫글), 절목록)
            if 찾:
                지금절 = 찾
                지금장 = int(찾[0].split(".")[0])
                out = 장파일[지금장]
                out += ["", f"## {찾[0]} {찾[1]}", ""]
                줄 = 줄[1:]
        out.append(f"<!-- p.{쪽} · pdf {i + 1} -->")
        단락 = ""
        번호 = 0
        오른끝 = max((r["x1"] for r in 줄), default=0)

        def 내보내기():
            nonlocal 단락
            if 단락.strip():
                out.append(단락.strip())
                out.append("")
            단락 = ""

        for r in 줄:
            글 = "".join(c for c, _ in r["chars"])
            자리 = 굵은자리(r["chars"], 기준)
            spans = [(c, False, k in 자리) for k, (c, _) in enumerate(r["chars"])]
            md = 굵게(spans).strip()
            raw = 글.strip()
            m = _표시.match(md)
            if m:
                번호 += 1
                md = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"[min(번호, 15) - 1] + " " + md[m.end():]
            elif _머리.match(raw):
                번호 = 0
            md = 고치기(md)
            색인.append({"pdf": i + 1, "쪽": 쪽, "절": 지금절[0], "글": 고치기(raw),
                         "굵은자리": 자리})
            새단락 = bool(m) or bool(_머리.match(raw)) or r["size"] >= 9.5 or raw.startswith(("<", "判例", "대법원", "※"))
            if 새단락:
                내보내기()
            if 단락 and not 단락.endswith(" "):
                단락 += " "
            단락 += md
            if r["x1"] < 오른끝 - 40 or r["size"] >= 9.5:       # 줄이 짧게 끝났으면 단락 끝
                내보내기()
        내보내기()
    return 장파일, 색인


# 차례 OCR 이 깨뜨린 장 제목 (표지·차례 그림으로 확인, 2026-11-08)
장제목 = {1: "총설", 2: "특허를 받을 수 있는 권리 및 출원 절차", 3: "보상금청구권", 4: "특허권 및 침해",
         5: "실시권", 6: "특허심판제도", 7: "심결취소소송", 8: "PCT", 9: "특이 발명", 10: "특이 청구항"}


def 쓰기(장파일, 장목록, 덮어쓰기):
    출력.mkdir(parents=True, exist_ok=True)
    제목 = {**dict(장목록), **장제목}
    for n, lines in sorted(장파일.items()):
        이름 = re.sub(r"[\s/\\:*?\"<>|·]", "", 제목.get(n, f"{n}장"))
        p = 출력 / f"{n:02d}장_{이름}.md"
        if p.exists() and not 덮어쓰기:
            sys.exit(f"이미 있다: {p} — 손으로 고친 판일 수 있다. 다시 뽑으려면 --덮어쓰기")
        본문 = re.sub(r"\n{3,}", "\n\n", "\n".join(x.rstrip() for x in lines).strip("\n"))
        머리 = (f"# 준특허법 · Chapter {n} {제목.get(n, '')}\n\n"
              "박형준 「준 특허법」 기본서를 OCR 글자층에서 옮긴 **검색·인용용 원문**이다. 오타가 남아 있다 — 쓸 때 쪽 그림으로 고친다.\n"
              "**굵은 말** = 두음(굵은 첫 글자)으로 시작하는 낱말. `<!-- p.N -->` 은 책 쪽.\n\n"
              "<!-- 기본서.py 가 2026-11-08 만들었다. 손으로 고치기 시작하면 다시 돌리지 않는다. -->\n\n")
        p.write_text(머리 + 본문 + "\n", encoding="utf-8", newline="\n")
        print(f"  {p.name}  {len(본문):,}자")


def main(argv):
    doc = fitz.open(PDF)
    기준 = 기준표(doc)
    if "--쪽" in argv:
        n = int(argv[argv.index("--쪽") + 1])
        for r in 쪽글자(doc[n - 1]):
            자리 = 굵은자리(r["chars"], 기준)
            print(굵게([(c, False, k in 자리) for k, (c, _) in enumerate(r["chars"])]).strip())
        return
    장목록, 절목록 = 차례(doc)
    print(f"차례: 장 {len(장목록)} · 절 {len(절목록)}")
    장파일, 색인 = 만들기(doc, 기준, 장목록, 절목록)
    쓰기(장파일, 장목록, "--덮어쓰기" in argv)
    (작업 / "줄.json").write_text(json.dumps(색인, ensure_ascii=False), encoding="utf-8", newline="\n")
    print(f"색인 {len(색인):,}줄 → {작업 / '줄.json'}")


if __name__ == "__main__":
    main(sys.argv[1:])
