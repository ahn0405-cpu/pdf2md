"""검증용 PDF 픽스처 생성기.

실물 교재를 대신해, 지침이 서술한 조판을 그대로 재현한 PDF 를 만든다.
  기본서: 1단 / 하단 각주 + 가로선 / 우측 여백 sE-8 / 청색 강조 / ☑ 박스 /
          위첨자 각주 참조 / 사건번호 별표 / 두문자 / 한자
  사례집: 문제 지문 박스 / 배점 / 학판검 / 두문자(한 글자 다름 — 교차검증용)

지침 §2.2 의 실측 사례(기본서 [확객시전] vs 사례집 [확객시젠])를 일부러 넣어
§5.3 교차검증이 실제로 잡아내는지 확인한다.

    python3 tests/make_fixtures.py [출력디렉토리]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
SYMBOL_FONT = "/usr/share/fonts/opentype/unifont/unifont_jp.otf"   # ☑ 글리프용
BLACK = (0, 0, 0)
BLUE = (0.12, 0.31, 0.63)        # 강조색 1종 (청색 계열)

BODY = 10.0
SMALL = 8.0
SUP = 6.5


class Sheet:
    """한 쪽을 위에서 아래로 채운다."""

    def __init__(self, doc, width=595, height=842, margin=60):
        self.page = doc.new_page(width=width, height=height)
        self.w, self.h, self.m = width, height, margin
        self.y = margin + 20
        self.page.insert_font(fontname="wqy", fontfile=FONT)
        self.page.insert_font(fontname="sym", fontfile=SYMBOL_FONT)

    def put(self, text, size=BODY, color=BLACK, x=None, dy=None, bold=False):
        x = self.m if x is None else x
        self.y += dy if dy is not None else size * 1.6
        self.page.insert_text((x, self.y), text, fontname="wqy", fontsize=size,
                              color=color, render_mode=2 if bold else 0,
                              border_width=0.35 if bold else 0)
        return self.y

    def put_runs(self, runs, size=BODY, x=None, dy=None):
        """[(글자, 색, 굵게), ...] 를 한 줄에 이어 붙인다."""
        x = self.m if x is None else x
        self.y += dy if dy is not None else size * 1.6
        cursor = x
        for text, color, bold in runs:
            self.page.insert_text((cursor, self.y), text, fontname="wqy",
                                  fontsize=size, color=color,
                                  render_mode=2 if bold else 0,
                                  border_width=0.35 if bold else 0)
            cursor += _width(text, size)
        return self.y

    def put_sup(self, base_runs, sup_text, size=BODY):
        """본문 끝에 위첨자 각주 번호를 올린다."""
        y = self.put_runs(base_runs, size=size)
        cursor = self.m + sum(_width(t, size) for t, _, _ in base_runs)
        self.page.insert_text((cursor, y - size * 0.35), sup_text, fontname="wqy",
                              fontsize=SUP, color=BLACK)

    def put_symbol(self, symbol, text, size=BODY):
        """☑ 처럼 본문 글꼴에 없는 기호는 다른 글꼴로 찍는다 (실제 교재와 같은 상황)."""
        self.y += size * 1.6
        self.page.insert_text((self.m, self.y), symbol, fontname="sym", fontsize=size)
        self.page.insert_text((self.m + size * 1.3, self.y), text, fontname="wqy",
                              fontsize=size, render_mode=2, border_width=0.35)
        return self.y

    def sidenote(self, text):
        """우측 여백의 강의교안 옆번호 (§4.3)."""
        self.page.insert_text((self.w - self.m - 26, self.y), text,
                              fontname="wqy", fontsize=SMALL, color=BLACK)

    def box(self, top, bottom):
        self.page.draw_rect(pymupdf.Rect(self.m - 6, top, self.w - self.m + 6, bottom),
                            color=(0.4, 0.4, 0.4), width=0.6)

    def footnotes(self, items):
        """페이지 하단: 가로 구분선 + 작은 글자 각주."""
        y = self.h - self.m - len(items) * (SMALL * 1.5) - 14
        self.page.draw_line(pymupdf.Point(self.m, y), pymupdf.Point(self.m + 170, y),
                            color=BLACK, width=0.7)
        y += 12
        for text in items:
            self.page.insert_text((self.m, y), text, fontname="wqy",
                                  fontsize=SMALL, color=BLACK)
            y += SMALL * 1.5

    def header(self, text):
        self.page.insert_text((self.m, self.m * 0.55), text, fontname="wqy",
                              fontsize=SMALL, color=(0.4, 0.4, 0.4))


def _width(text, size):
    font = pymupdf.Font(fontfile=FONT)
    return font.text_length(text, size)


def _place_ocr(page, x, y, shown, ocr, size):
    """OCR 레이어를 종이의 낱말 자리에 공백 글자 없이 놓는다.

    실물이 이 구조다. 공백 글자는 없고 낱말 사이가 벌어져만 있어서,
    글자 간격을 보지 않으면 '수량적가분채권을' 처럼 붙어 나온다.
    """
    words = shown.split(" ")
    flat = ocr.replace(" ", "")
    cursor = x
    taken = 0
    for w in words:
        n = len(w.replace(" ", ""))
        chunk = flat[taken:taken + n] if taken < len(flat) else ""
        taken += n
        if chunk:
            page.insert_text((cursor, y), chunk, fontname="wqy", fontsize=size,
                             render_mode=3)
        cursor += _width(w + " ", size)
    if taken < len(flat):
        page.insert_text((cursor, y), flat[taken:], fontname="wqy", fontsize=size,
                         render_mode=3)


# ── 기본서 ──────────────────────────────────────────────────────
def textbook(path: Path, filler_pages: int = 6):
    doc = pymupdf.open()

    s = Sheet(doc)
    s.header("제3편 제1심의 소송절차")
    s.put("제3편 소송의 개시", size=15, bold=True)
    s.put("CHAPTER 05 소송물", size=13, bold=True)
    s.put("제2절 소송물의 특정", size=11.5, bold=True)
    s.put("1. 소송물 개념", size=11, bold=True)
    s.put("소송물이란 심판의 대상이 되는 사항을 말한다. 甲이 乙에게 청구하는", size=BODY)
    s.put("권리관계가 그 내용이 된다.", size=BODY)
    doc_pages = [s]

    s = Sheet(doc)
    s.header("제3편 제1심의 소송절차")
    y = s.put("IV. 시효중단 (11)", size=11, bold=True)
    s.sidenote("sE-8")
    s.put("의의 - 내용 - 예외 - 효과 + 관련논점", size=SMALL, color=(0.35, 0.35, 0.35))
    s.put("1. 문제점", size=BODY, bold=True)
    s.put_sup([("일부청구의 경우 시효중단의 범위가 문제된다. 判例 는 이를", BLACK, False)], "264")
    s.put("나누어 본다.", size=BODY)
    s.put("2. 학설", size=BODY, bold=True)
    s.put("(1) 일부중단설은 소송물의 범위에서만 중단된다고 본다.", size=BODY)
    s.put("(2) 전부중단설은 채권 전부에 미친다고 본다.", size=BODY)
    s.put("3. 判例", size=BODY, bold=True)
    s.put_runs([("(1) 원칙 ", BLACK, False), ("[일나시 나소시]", BLUE, False),
                (" 로 본다. (74다1557)", BLACK, False)])
    s.put_runs([("1) [청구확장 취지 명백히 표시] ", BLACK, False),
                ("확장의 뜻을 밝힌 때", BLUE, False),
                (" 에는 전부에 미친다. (91다43695*)", BLACK, False)])
    s.put("2) [실제로 청구 확장] 뒤에 확장한 경우 (2019다223723)", size=BODY)
    s.put_sup([("3) [청구 일부를 명시적으로 제외] 제외한 부분 (2018다44114)", BLACK, False)], "266")
    s.put("4. 검토", size=BODY, bold=True)
    s.put_runs([("", BLACK, False), ("[확객시전]", BLUE, False),
                (" 이 타당하다. 제 265 조 참조.", BLACK, False)])
    top = s.y + 6
    s.put_symbol("☑", "실제로 청구취지 확장하지 않은 부분의 취급")
    s.put("1. 최고의 효력", size=BODY)
    s.put("2. 후소로 제기하는 경우 시효중단의 소급효", size=BODY)
    s.box(top, s.y + 6)
    s.footnotes([
        "264 종전 判例 는 요건을 달리 보았으나 최근 判例 는 요건을 추가하였다. 그 경위는",
        "다음과 같다. 즉 청구취지 확장의 시기를 기준으로 삼는다.",
        "266 원고는 2011. 4. 26. 손해배상청구의 소를 제기하였고, 1억 원 중 3천만 원을",
        "먼저 구하였다. 소멸시효는 2014. 4. 26. 완성된다.",
    ])
    doc_pages.append(s)

    s = Sheet(doc)
    s.header("제3편 제1심의 소송절차")
    s.put("V. 기판력 (15)(20)", size=11, bold=True)
    s.sidenote("sE-9")
    s.put("1. 의의", size=BODY, bold=True)
    s.put_runs([("확정판결의 ", BLACK, False), ("판단내용의 구속력", BLUE, False),
                (" 을 말한다. (2018다44114)", BLACK, False)])
    s.put("2. 判例", size=BODY, bold=True)
    s.put_sup([("(1) ", BLACK, False), ("[종확나시]", BLUE, False),
               (" 로 정리된다. (91다43695)", BLACK, False)], "268")
    s.footnotes(["268 기판력의 표준시에 관하여는 뒤에서 본다."])
    doc_pages.append(s)

    for k in range(filler_pages):
        s = Sheet(doc)
        s.header("제3편 제1심의 소송절차")
        s.put(f"{k + 3}. 관련 논점 {k + 1}", size=BODY, bold=True)
        for j in range(14):
            s.put(f"본문 {k + 1}-{j + 1}. 소송물의 범위에 관하여 甲과 乙 사이의 "
                  f"법률관계를 본다.", size=BODY)
        doc_pages.append(s)

    doc.save(str(path))
    doc.close()


# ── 사례집 ──────────────────────────────────────────────────────
def casebook(path: Path):
    doc = pymupdf.open()

    s = Sheet(doc)
    s.header("사례집 E. 소송물")
    s.put("E-5. [일부청구-시효중단]", size=13, bold=True)
    s.put("문제 (10점)", size=11, bold=True)
    top = s.y + 6
    s.put("불법행위로 피해를 입은 소비자들은 X를 상대로 손해배상청구의 소를", size=BODY)
    s.put("제기하면서 소장에 앞으로의 신체감정결과에 따라 청구금액을 확장할", size=BODY)
    s.put("뜻을 명시한 후, 전체 손해액 중 일부인 1억 원에 대해서 지급을 구한다고", size=BODY)
    s.put("기재하였다. 2011. 4. 26. 소를 제기하였다.", size=BODY)
    s.box(top, s.y + 6)
    s.put("답안", size=11, bold=True)
    s.put("1. 문제의 소재 — 일부청구 의의 (0.5)", size=BODY, bold=True)
    s.put("일부청구의 의의를 먼저 본다.", size=BODY)
    s.put("2. 일부청구 소송물 (2.5)", size=BODY, bold=True)
    s.put("(1) 학설", size=BODY)
    s.put_runs([("(2) 判例 ", BLACK, False), ("[일외별명일]", BLUE, False),
                (" (74다1557)", BLACK, False)])
    s.put("(3) 검토 및 사안", size=BODY)
    doc_pages = [s]

    s = Sheet(doc)
    s.header("사례집 E. 소송물")
    s.put("3. 일부청구시 시효중단 범위 (4)", size=BODY, bold=True)
    s.put("(1) [제265조]", size=BODY)
    s.put("(2) 학설", size=BODY)
    # 지침 §2.2 실측 사례: 사례집 쪽이 '확객시젠' 으로 한 글자 다르다
    s.put_runs([("(3) 判例 ", BLACK, False),
                ("[일나시 나소시] [확객시젠] [종확나시]", BLUE, False),
                (" (91다43695)", BLACK, False)])
    s.put("(4) 검토 및 사안", size=BODY)
    s.put("4. 사안해결 (0.5)", size=BODY, bold=True)
    s.put("사안에서는 청구취지 확장의 뜻을 명시하였으므로 전부에 미친다.", size=BODY)
    doc_pages.append(s)

    doc.save(str(path))
    doc.close()


# ── 스캔본 + OCR 텍스트 레이어 ────────────────────────────────────
# 실물 교재가 이 꼴이다. 종이를 찍은 그림 위에 OCR 글자가 보이지 않게 얹혀 있다.
#   · 글자 색은 전부 검정 → 강조색은 그림 픽셀에만 남는다 (§2.4)
#   · 여는 괄호가 ＜ 로 흘러나온다 (§2.1)
#   · 닫는 대괄호가 통째로 빠진다 (§2.2)
#   · 각주 참조가 위첨자가 아니라 'NNN)' 으로 떨어진다 (§2.5)
def scanned_textbook(path: Path):
    """(종이 모양, OCR 이 흘린 글자) 짝으로 스캔본을 짓는다.

    실물에서 확인된 것을 그대로 재현한다.
      · 낱말 사이 공백이 OCR 글자에 없다
      · 번호와 제목이 다른 줄로 떨어진다 ('3' / '.判例[일외별명일]')
      · 제목이 파란색이라 강조로 읽힌다
      · 여는 괄호가 ＜, 닫는 대괄호가 사라짐
      · 각주 참조가 'NNN)' 로 본문에 떨어짐
      · ☑ 가 '0' 으로 읽힘
      · 쪽 아래 꼬리말 '154•윤곽민사소송법'
    """
    W, H, M = 470, 700, 46
    B = BLACK
    # (y, x, 종이에 인쇄된 글자, 색, OCR 이 흘린 글자)
    rows = [
        (70,  M,      "046 일부청구", BLUE, "046일부청구"),
        (92,  M,      "& 의의 - 소송물 - 시효중단 - 기판력", BLUE,
                      "&의의-소송물-시효중단-기판력"),
        (118, M,      "I. 의의", B, "I.의의"),
        (140, M,      "수량적 가분 채권을 분할 청구하는 것을 말한다.", B,
                      "수량적가분채권을분할청구하는것을말한다."),
        (170, M,      "IV. 시효중단(11)", BLUE, "IV.시효중단(11)"),
        (196, M,      "1. 문제점", BLUE, "1.문제점"),
        (218, M + 14, "소제기시 시효중단의 효력이 있다(제265조).264)", B,
                      "소제기시시효중단의효력이있다(제265조).264)"),
        # 번호와 제목이 다른 줄로 떨어지는 자리
        (245, M,      "3", BLUE, "3"),
        (244, M + 15, ". 判例 [일나시 나소시]", BLUE, ".判例[일나시나소시"),
        (266, M + 14, "일부청구는 나머지 부분에 시효중단 효력이 없다(74다1557).", B,
                      "일부청구는나머지부분에시효중단효력이없다＜74다1557)."),
        (292, M,      "4", BLUE, "4"),
        (291, M + 15, ". 검토", BLUE, ".검토"),
        (313, M + 14, "확장의 뜻을 밝힌 때에는 전부에 미친다", BLUE,
                      "확장의뜻을밝힌때에는전부에미친다"),
        (330, M + 14, "고 본다(91다43695*). 명시적으로 제외265)하였다면 그렇다.", B,
                      "고본다＜91다43695*).명시적으로제외265)하였다면그렇다."),
        # ☑ 보너스 논점 박스
        (365, M,      "☑ 실제로 청구취지 확장하지 않은 부분의 취급", BLUE,
                      "0실제로청구취지확장하지않은부분의취급"),
        (388, M + 14, "1. 최고의 효력", B, "1.최고의효력"),
        (408, M + 14, "6월 내에 조치를 취할 수 있다(2019다223723).", B,
                      "6월내에조치를취할수있다＜2019다223723)."),
    ]
    foots = [
        (600, "264) 즉, 종전 판시에 요건을 추가한 것이다.", 7.2),
        (614, "265) 일부 소취하 등이 있을 수 있다.", 7.2),
    ]
    footer = (676, "154·윤곽민사소송법", 7.6)

    paper = pymupdf.open()
    page = paper.new_page(width=W, height=H)
    page.insert_font(fontname="wqy", fontfile=FONT)
    for y, x, shown, color, _ in rows:
        page.insert_text((x, y), shown, fontname="wqy", fontsize=9, color=color)
    page.insert_text((W - M - 24, 170), "sE-8", fontname="wqy", fontsize=7, color=B)
    for y, text, size in foots:
        page.insert_text((M, y), text, fontname="wqy", fontsize=size, color=B)
    page.insert_text((M, footer[0]), footer[1], fontname="wqy",
                     fontsize=footer[2], color=B)
    pix = page.get_pixmap(dpi=200)
    paper.close()

    scan = pymupdf.open()
    out = scan.new_page(width=W, height=H)
    out.insert_image(pymupdf.Rect(0, 0, W, H), pixmap=pix)
    out.insert_font(fontname="wqy", fontfile=FONT)
    for y, x, shown, _, ocr in rows:
        _place_ocr(out, x, y, shown, ocr, 9)
    out.insert_text((W - M - 24, 170), "sE-8", fontname="wqy", fontsize=7, render_mode=3)
    for y, text, size in foots:
        out.insert_text((M, y), text, fontname="wqy", fontsize=size, render_mode=3)
    out.insert_text((M, footer[0]), footer[1], fontname="wqy",
                    fontsize=footer[2], render_mode=3)
    scan.save(str(path))
    scan.close()


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")
    out.mkdir(parents=True, exist_ok=True)
    textbook(out / "기본서.pdf")
    casebook(out / "사례집.pdf")
    scanned_textbook(out / "스캔기본서.pdf")
    for p in sorted(out.glob("*.pdf")):
        print(f"{p}  {p.stat().st_size:,} bytes")
