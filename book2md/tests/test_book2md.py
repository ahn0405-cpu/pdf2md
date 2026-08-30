"""회귀 테스트. 표준 unittest 만 쓴다 (§9 외부 의존 최소화).

    python3 -m unittest discover -s tests -v
    python3 tests/test_book2md.py

지키려는 것은 §2 의 네 가지다. 사건번호·두문자·별표·각주가 한 글자도 상하지
않는지, 그리고 파서를 갈아 끼워도 §4·§5 가 그대로 도는지를 본다.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from book2md.config import load_config, profile as get_profile   # noqa: E402
from book2md.footnotes import FootnoteCollector                  # noqa: E402
from book2md.model import Line, Page                             # noqa: E402
from book2md.normalize import Normalizer                         # noqa: E402
from book2md.patterns import Patterns                            # noqa: E402
from book2md.structure import Structurer, render                 # noqa: E402
from book2md.split import split, front_matter, filename                    # noqa: E402
from book2md.validate import validate                            # noqa: E402

CFG = load_config(ROOT / "config.yaml")
PAT = Patterns.build(CFG)


def norm(text: str) -> str:
    changes: list = []
    return Normalizer(CFG, PAT).normalize_line(text, 1, changes)


class 사건번호(unittest.TestCase):
    """§2.1"""

    def test_여는괄호_오인식을_되돌린다(self):
        self.assertEqual(norm("판례＜74다1557) 참조"), "판례(74다1557) 참조")
        self.assertEqual(norm("〈91다43695) 참조"), "(91다43695) 참조")
        self.assertEqual(norm("｛2019다223723｝"), "(2019다223723)")

    def test_내부_공백을_없앤다(self):
        self.assertEqual(norm("91 다 43695"), "91다43695")
        self.assertEqual(norm("2019 다 223723 판결"), "2019다223723 판결")

    def test_사건번호가_아닌_숫자는_건드리지_않는다(self):
        for text in ("제265조", "2011. 4. 26.", "1억 원", "전화 02-1234"):
            self.assertEqual(norm(text), norm(text))
            self.assertFalse(PAT.case.search(norm(text)), text)

    def test_형식_검사(self):
        m = PAT.case.search("74다1557")
        self.assertEqual(PAT.case_problems(m), [])
        m = PAT.case.search("74카1557")
        self.assertEqual(PAT.case_problems(m), [])
        m = PAT.case.search("74초1557")          # 알려진 부호 (§P1-1 로 추가)
        self.assertEqual(PAT.case_problems(m), [])
        m = PAT.case.search("74인1557")          # 알려진 목록에 없는 부호
        self.assertTrue(PAT.case_problems(m))
        m = PAT.case.search("1899다1557")        # 연도가 범위 밖
        self.assertTrue(PAT.case_problems(m))


class 두문자(unittest.TestCase):
    """§2.2 — 한 글자도 바뀌면 안 된다"""

    def test_전각_대괄호를_반각으로(self):
        self.assertEqual(norm("［일나시 나소시］"), "[일나시 나소시]")

    def test_중괄호_오인식을_되돌린다(self):
        self.assertEqual(norm("{확객시전}"), "[확객시전]")
        self.assertEqual(norm("【종확나시】"), "[종확나시]")

    def test_안쪽_글자는_절대_고치지_않는다(self):
        # 사례집의 '확객시젠' 을 기본서의 '확객시전' 으로 고치면 안 된다 (§4.6)
        self.assertEqual(norm("[확객시젠]"), "[확객시젠]")
        self.assertIn("확객시젠", PAT.find_mnemonics("[확객시젠]"))

    def test_판례_라벨은_두문자가_아니다(self):
        # ③ 라벨은 legend.case_label 이 따로 뽑는다 (§1.5)
        self.assertEqual(PAT.find_mnemonics("1) [청구확장 취지 명백히 표시] 이다"), [])
        self.assertEqual(PAT.find_mnemonics("[대법원 판결]"), [])
        self.assertEqual(PAT.find_mnemonics("각주[^264] 참조"), [])

    def test_진짜_두문자는_잡는다(self):
        self.assertEqual(PAT.find_mnemonics("원칙 [일나시 나소시] 로"), ["일나시 나소시"])
        self.assertEqual(PAT.find_mnemonics("[일외별명일]"), ["일외별명일"])


class 별표(unittest.TestCase):
    """§2.3 — 중요 판례 표시. 절대 지우지 않는다."""

    def test_별표를_사건번호에_붙인다(self):
        self.assertEqual(norm("2018다44114 ＊ 이다"), "2018다44114* 이다")
        self.assertEqual(norm("(91다43695*)"), "(91다43695*)")

    def test_별표_개수를_센다(self):
        text = "74다1557* 와 91다43695 와 2019다223723 *"
        self.assertEqual(len(PAT.case_star.findall(text)), 2)


class 각주(unittest.TestCase):
    """§2.5 — 버리지 않는다. 페이지를 넘어 이어지면 잇는다."""

    def _page(self, number, body, foot):
        lines = [Line(text=t, size=10.0) for t in body]
        lines += [Line(text=t, size=8.0, zone="footnote") for t in foot]
        return Page(number=number, lines=lines, kind="layout", body_size=10.0)

    def test_페이지를_넘어_이어지는_각주를_잇는다(self):
        col = FootnoteCollector(CFG, PAT)
        a = col.process(self._page(1, ["본문[^264] 이다"],
                                   ["264 종전 判例 는 요건을 달리 보았으나"]))
        b = col.process(self._page(2, ["다음 본문"], ["최근 判例 는 요건을 추가하였다."]))
        self.assertEqual(a[0].number, 264)
        self.assertEqual(b, [])
        self.assertIn("최근 判例 는 요건을 추가하였다.", a[0].text)

    def test_조문_번호를_각주_참조로_바꾸지_않는다(self):
        """'제38조 1항' 의 1 이 [^1] 이 되면 조문이 통째로 망가진다."""
        col = FootnoteCollector(CFG, PAT)
        page = self._page(
            1, ["이송결정의 구속력 [제38조 1항 및 2항]",
                "제1심 법원은 2020. 1. 16. 판결하였다.[^1]"],
            ["1) 각주 본문이다. 충분히 길게 적어 각주로 보이게 한다."])
        col.process(page)
        body = "\n".join(l.text for l in page.lines)
        self.assertIn("제38조 1항 및 2항", body)
        self.assertIn("제1심", body)
        self.assertNotIn("[^2]", body)

    def test_목록_번호를_각주_참조로_바꾸지_않는다(self):
        """'(1) 이송결정의 구속력' 이 '([^1] …' 이 되면 설문 번호가 통째로 망가진다."""
        col = FootnoteCollector(CFG, PAT)
        page = self._page(
            1, ["(1) 이송결정의 구속력 [제38조 1항]", "(2) 특별재판적 [제18조]"],
            ["1) 각주 본문이다. 충분히 길게 적어 각주로 보이게 한다.",
             "2) 또 다른 각주 본문이다. 충분히 길게 적는다."])
        col.process(page)
        body = "\n".join(l.text for l in page.lines)
        self.assertIn("(1) 이송결정의 구속력", body)
        self.assertIn("(2) 특별재판적", body)
        self.assertNotIn("[^", body)

    def test_괄호가_붙은_번호는_각주_참조로_본다(self):
        col = FootnoteCollector(CFG, PAT)
        page = self._page(
            1, ["판시한다(2019다223723).264)"],
            ["264) 즉, 최근 판시가 요건을 추가한 것이다. 충분히 길게 적는다."])
        col.process(page)
        self.assertIn("[^264]", page.lines[0].text)

    def test_각주는_본문에서_분리된다(self):
        col = FootnoteCollector(CFG, PAT)
        page = self._page(1, ["본문이다"], ["264 각주다"])
        col.process(page)
        self.assertEqual([l.text for l in page.lines], ["본문이다"])


class 정규화(unittest.TestCase):
    """§4"""

    def test_조문_공백(self):
        self.assertEqual(norm("제 265 조 제 1 항"), "제265조 제1항")

    def test_날짜_표준화(self):
        self.assertEqual(norm("2011.4.26 판결"), "2011. 4. 26. 판결")

    def test_날짜뒤_한글은_지우지_않고_기록만_한다(self):
        changes: list = []
        out = Normalizer(CFG, PAT).normalize_line("2011. 4. 26로", 1, changes)
        self.assertIn("로", out)                       # 한글은 지우지 않는다
        self.assertTrue(any(c.kind == "date" for c in changes))

    def test_노이즈_제거는_기록을_남긴다(self):
        changes: list = []
        out = Normalizer(CFG, PAT).normalize_line("甲이 ¤ 乙에게", 1, changes)
        self.assertNotIn("¤", out)
        self.assertTrue(any(c.kind == "noise" for c in changes))

    def test_한자는_그대로_둔다(self):
        self.assertEqual(norm("甲乙 判例"), "甲乙 判例")


class 구조화(unittest.TestCase):
    """§6"""

    def _run(self, profile_name, lines, sidenotes=()):
        """lines 는 실제 조판처럼 16pt 간격으로 세로에 늘어놓는다."""
        prof = get_profile(CFG, profile_name)
        st = Structurer(CFG, prof, PAT)
        rows = [Line(text=t, size=10.0, y0=100.0 + 16 * k, y1=110.0 + 16 * k)
                for k, t in enumerate(lines)]
        page = Page(number=1, lines=rows, kind="layout", sidenotes=list(sidenotes))
        st.feed(page, [])
        return st.finish()

    def test_기본서_헤딩과_기출연도와_옆번호(self):
        blocks = self._run("textbook",
                           ["제3편 소송의 개시", "CHAPTER 05 소송물",
                            "IV. 시효중단 (11)", "1. 문제점", "본문이다."],
                           sidenotes=[{"text": "sE-8", "y": 132.0}])
        md = render(blocks)
        self.assertIn("# 제3편 소송의 개시", md)
        self.assertIn("## CHAPTER 05 소송물", md)
        # 파서가 옆번호를 넘겨 주면(mode: keep) 세로 위치가 맞는 헤딩에 붙는다
        self.assertIn("#### IV. 시효중단 `(11)` `sE-8`", md)
        self.assertNotIn("제3편 소송의 개시 `sE-8`", md)
        # 파서가 옆번호를 넘겨 주면(mode: keep) 세로 위치가 맞는 헤딩에 붙는다.
        # 기본값은 drop 이라 파서가 아예 넘기지 않는다.
        self.assertIn("#### IV. 시효중단 `(11)` `sE-8`", md)
        self.assertNotIn("제3편 소송의 개시 `sE-8`", md)   # 편 제목이 가로채지 않는다
        self.assertIn("**1. 문제점**", md)
        heading = next(b for b in blocks if "시효중단" in b.text)
        self.assertEqual(heading.meta["exam_years"], [2011])

    def test_판례_라벨과_표준판례(self):
        blocks = self._run("textbook",
                           ["IV. 시효중단", "3. 判例",
                            "1) [청구확장 취지 명백히 표시] 그렇다. (91다43695*)"])
        cases = [c for b in blocks for c in b.cases]
        self.assertEqual(cases[0]["id"], "91다43695")
        self.assertEqual(cases[0]["label"], "청구확장 취지 명백히 표시")
        self.assertTrue(cases[0]["standard"])

    def test_보너스_박스(self):
        blocks = self._run("textbook",
                           ["IV. 시효중단", "4. 검토", "본문.",
                            "☑ 실제로 확장하지 않은 부분", "1. 최고의 효력"])
        md = render(blocks)
        self.assertIn("> ### ☑ 실제로 확장하지 않은 부분", md)
        self.assertIn("> 1. 최고의 효력", md)
        self.assertTrue(any(b.meta.get("bonus_topic") for b in blocks))

    def test_사례집_배점과_지문분리(self):
        blocks = self._run("casebook",
                           ["E-5. [일부청구-시효중단]", "문제 (10점)", "지문이다.",
                            "답안", "2. 일부청구 소송물 (2.5)", "(2) 判例 (74다1557)"])
        md = render(blocks)
        # 문제 번호 옆 대괄호는 논점 태그이지 두문자가 아니다 (§6.2)
        self.assertIn("## E-5. [일부청구-시효중단] `10점`", md)
        self.assertIn("> 지문이다.", md)
        self.assertIn("### 2. 일부청구 소송물 `2.5`", md)
        self.assertIn("(74다1557)", md)              # 배점 규칙이 사건번호를 안 먹는다

    def test_설문은_답안_목차로_잡지_않는다(self):
        blocks = self._run("casebook",
                           ["E-9. [관할]", "답안",
                            "(1) 이송결정이 적법한지 설명하시오 (12)",
                            "(1) 학설"])
        md = render(blocks)
        self.assertNotIn("#### (1) 이송결정이 적법한지", md)   # 설문
        self.assertIn("#### (1) 학설", md)                    # 답안 목차
        self.assertIn("## E-9. [관할]", md)                    # 태그는 백틱 없이

    def test_배점_규칙이_사건번호를_망가뜨리지_않는다(self):
        blocks = self._run("casebook", ["E-1. 시험", "(3) 判例 (2019다223723)"])
        self.assertIn("(2019다223723)", render(blocks))


class 정정(unittest.TestCase):
    """§4.8 의 예외 — 사람이 확정한 정정만 적용한다."""

    def test_적은_것만_바꾸고_기록을_남긴다(self):
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["corrections"] = [
            {"find": "仏018다210539", "to": "(2018다210539", "note": "괄호+연도 유실"}]
        norm = Normalizer(cfg, Patterns.build(cfg))
        changes: list = []
        out = norm.normalize_line("볼 수 없다仏018다210539).", 1, changes)
        self.assertIn("(2018다210539)", out)
        self.assertTrue(any(c.kind == "correction" for c in changes))

    def test_목록이_비면_아무것도_바꾸지_않는다(self):
        """적힌 것이 없으면 손대지 않는다. 스스로 고치는 길은 없다."""
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["corrections"] = []
        changes: list = []
        out = Normalizer(cfg, Patterns.build(cfg)).normalize_line(
            "볼 수 없다仏018다210539).", 1, changes)
        self.assertIn("仏018다210539", out)
        self.assertFalse(changes)

    def test_배포_설정에_적힌_정정이_실제로_돈다(self):
        """config.yaml 에 적어 둔 것들이 문법 오류 없이 적용되는지."""
        entries = CFG.get("corrections") or []
        self.assertTrue(entries, "배포 설정에 정정이 하나도 없다")
        norm = Normalizer(CFG, PAT)
        for e in entries:
            changes: list = []
            out = norm.normalize_line(f"판시 {e['find']}).", 1, changes)
            self.assertIn(e["to"], out)
            self.assertTrue(any(c.kind == "correction" for c in changes))


class 오검출(unittest.TestCase):
    """세는 대상이 틀리면 규칙이 맞아도 판정이 어긋난다."""

    def test_굵게_표시를_별표로_세지_않는다(self):
        # `**3. 判例 (74다1557)**` 의 ** 가 별표로 잡히면 개수 대조가 부풀어 오른다
        self.assertEqual(PAT.case_star.findall("**판시 (74다1557)**"), [])
        self.assertEqual(len(PAT.case_star.findall("(91다43695*) 와 2018다44114*")), 2)

    def test_통화_표기를_사건번호로_보지_않는다(self):
        # '1,000만 원' 이 '1,000므1 원' 으로 흘러나온다
        self.assertEqual(PAT.find_cases("대여금 1,000므1 원과"), [])
        self.assertEqual(PAT.find_cases("대여금이 7000므1 원이라고"), [])
        self.assertEqual([m.group(0) for m in PAT.case.finditer("판시 (2019다223723)")],
                         ["2019다223723"])

    def test_목차_줄은_제목이_아니다(self):
        prof = get_profile(CFG, "casebook")
        st = Structurer(CFG, prof, PAT)
        rows = ["D-1. [공유물분할의 쇠.....................188",
                "D-2. [토지경계확정의 소]......................190",
                "D-3. [실제 문제 제목]"]
        st.feed(Page(number=1, kind="layout",
                     lines=[Line(text=t, size=9.0, y0=100 + 16 * k, y1=110 + 16 * k)
                            for k, t in enumerate(rows)]), [])
        heads = [b for b in st.finish() if b.kind == "heading"]
        self.assertEqual(len(heads), 1)
        self.assertIn("D-3", heads[0].text)


class 분할(unittest.TestCase):
    """§6.3"""

    def test_장이_없으면_절_제목으로_파일을_나눈다(self):
        """이 교재는 장 제목이 꼬리말로만 있어 본문에 없다. 그래도 '머리1',
        '머리2' 가 아니라 논점 제목이 파일 이름이 되어야 한다."""
        prof = get_profile(CFG, "textbook")
        st = Structurer(CFG, prof, PAT)
        rows = ["046 일부청구", "I. 의의", "본문이다.",
                "047 소장의 필요적 기재사항", "I. 의의", "다른 본문이다."]
        st.feed(Page(number=1, kind="layout",
                     lines=[Line(text=t, size=9.0, y0=100 + 16 * k, y1=110 + 16 * k)
                            for k, t in enumerate(rows)]), [])
        parts = split(st.finish(), prof)
        names = [filename(p, prof) for p in parts]
        self.assertEqual(len(parts), 2)
        self.assertIn("046일부청구", names[0])
        self.assertNotIn("머리", " ".join(names))

    def test_학판검_세트를_가르지_않는다(self):
        """'N. 학설' 에서 자르면 학설·判例·검토가 다른 파일로 흩어진다.
        논점 번호가 붙은 제목이 있으면 그것만 경계로 삼는다."""
        prof = get_profile(CFG, "textbook")
        st = Structurer(CFG, prof, PAT)
        rows = ["046 일부청구", "IV. 시효중단", "1. 문제점", "본문이다.",
                "2. 학설", "가설이다.", "3. 判例", "판시 (74다1557).",
                "4. 검토", "검토다.", "047 소장", "I. 의의", "다른 본문."]
        st.feed(Page(number=1, kind="layout",
                     lines=[Line(text=t, size=9.0, y0=100 + 16 * k, y1=110 + 16 * k)
                            for k, t in enumerate(rows)]), [])
        parts = split(st.finish(), prof)
        names = [filename(p, prof) for p in parts]
        self.assertEqual(len(parts), 2)
        self.assertNotIn("학설", " ".join(names))
        body = parts[0].text()
        for word in ("학설", "判例", "검토"):
            self.assertIn(word, body)          # 한 파일 안에 함께 있다

    def test_장_단위로_나누고_프론트매터를_붙인다(self):
        prof = get_profile(CFG, "textbook")
        st = Structurer(CFG, prof, PAT)
        st.feed(Page(number=1, kind="layout", lines=[
            Line(text=t, size=10.0) for t in
            ["제3편 소송의 개시", "CHAPTER 05 소송물", "IV. 시효중단 (11)",
             "판시. (74다1557*) 이고 [확객시전] 이다.", "CHAPTER 06 당사자",
             "다른 장. (91다43695)"]]), [])
        parts = split(st.finish(), prof)
        self.assertEqual(len(parts), 2)
        fm = front_matter(parts[0], prof, "pymupdf", "PASS")
        self.assertIn('id: "74다1557"', fm)
        self.assertIn("standard: true", fm)
        self.assertIn("exam_years: [2011]", fm)
        self.assertIn('mnemonics: ["확객시전"]', fm)
        self.assertNotIn("91다43695", fm)


class 검증(unittest.TestCase):
    """§5"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, body, fm='---\nsource: 기본서\nparser: pymupdf\ncases:\n'):
        (self.dir / "a.md").write_text(fm + "---\n\n" + body, encoding="utf-8")

    def test_원본_별표는_한_줄_안의_공백까지만_센다(self):
        """원본에는 '91 다43176*' 처럼 공백이 낀다. 엄격 패턴으로 세면 변환본이
        늘어난 것처럼 보이고, 줄바꿈까지 허용하면 반대로 모자란 것처럼 보인다.
        정규화가 실제로 붙일 수 있는 범위(한 줄)와 자를 맞춘다."""
        raw = "판시 (91 다43176*) 와 (74다1557*) 이다."
        self.assertEqual(len(PAT.case_star_loose.findall(raw)), 2)
        self.assertEqual(len(PAT.case_star.findall(raw)), 1)
        # 줄을 넘어 끊긴 것은 세지 않는다 — 정규화가 못 붙인다
        self.assertEqual(PAT.case_star_loose.findall("판시 (91\n다43176*)"), [])

    def test_별표_개수_불일치는_FAIL(self):
        self._write("판시 (91다43695*) 이다.\n")
        res = validate(self.dir, CFG, {"stars": 2, "pages": 1})
        self.assertEqual(res.verdict, "FAIL")
        self.assertTrue(any("5.2" in f.check for f in res.findings))

    def test_옆번호가_본문에_새면_FAIL(self):
        # 좌표 분리가 어긋나면 옆번호가 본문 글자에 붙는다 (§4.3)
        self._write("#### IV. 시효중단 sE-81 문제점\n\n본문.\n")
        res = validate(self.dir, CFG, {"pages": 1})
        self.assertTrue(any("5.5" in f.check and f.level == "FAIL"
                            for f in res.findings))

    def test_헤딩에_붙인_옆번호는_통과(self):
        self._write("#### IV. 시효중단 `sE-8`\n\n본문.\n")
        res = validate(self.dir, CFG, {"pages": 1})
        self.assertEqual(res.counts["sidenote_merged"], 0)

    def test_각주_참조와_정의가_맞으면_통과(self):
        self._write("본문[^264] 이다.\n\n[^264]: 각주 내용.\n")
        res = validate(self.dir, CFG, {"pages": 1})
        self.assertEqual(res.counts["footnote_mismatch"], 0)

    def test_프론트매터의_사건번호_누락은_FAIL(self):
        (self.dir / "a.md").write_text(
            '---\nsource: 기본서\nparser: pymupdf\ncases:\n  - id: "74다1557"\n---\n\n'
            "판시 (91다43695) 이다.\n", encoding="utf-8")
        res = validate(self.dir, CFG, {"pages": 1})
        self.assertTrue(any("프론트매터" in f.check and f.level == "FAIL"
                            for f in res.findings))


class 파서교체(unittest.TestCase):
    """§3.2 — 파서가 바뀌어도 §4·§5 는 그대로 돈다"""

    def test_텍스트파서로도_같은_파이프라인이_돈다(self):
        from book2md.parsers import get_parser
        from book2md.pipeline import Pipeline
        tmp = Path(tempfile.mkdtemp())
        try:
            src = tmp / "src.txt"
            src.write_text(
                "제3편 소송의 개시\nCHAPTER 05 소송물\nIV. 시효중단 (11)\n"
                "1. 문제점\n판시[^264] 이다. ＜74다1557) 참조 [확객시전]\n"
                "264 각주 내용이다. 충분히 길게 적어 각주로 보이게 한다.\n",
                encoding="utf-8")
            prof = get_profile(CFG, "textbook")
            pipe = Pipeline(src, CFG, prof, tmp / "out", tmp / "_reports",
                            tmp / "_work", "textfile", None, log=lambda *a: None)
            verdict = pipe.run("extract")
            md = "\n".join(p.read_text(encoding="utf-8")
                           for p in (tmp / "out").glob("*.md"))
            self.assertIn("(74다1557)", md)          # §4 정규화가 그대로 돌았다
            self.assertIn("`[확객시전]`", md)
            self.assertIn("[^264]", md)
            self.assertIn(verdict, ("PASS", "WARN", "FAIL"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class 종단(unittest.TestCase):
    """픽스처 PDF → 진단 → 변환 → 검증 → 교차검증"""

    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf  # noqa: F401
        except Exception:
            raise unittest.SkipTest("PyMuPDF 없음")
        cls.tmp = Path(tempfile.mkdtemp())
        sys.path.insert(0, str(ROOT / "tests"))
        import make_fixtures
        cls.fix = cls.tmp / "fixtures"
        cls.fix.mkdir(parents=True)
        if not Path(make_fixtures.FONT).exists():
            raise unittest.SkipTest("한글 글꼴 없음")
        make_fixtures.textbook(cls.fix / "기본서.pdf")
        make_fixtures.casebook(cls.fix / "사례집.pdf")
        make_fixtures.scanned_textbook(cls.fix / "스캔기본서.pdf")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", "/nonexistent"), ignore_errors=True)

    def test_진단이_지침_4개_항목을_판정한다(self):
        from book2md import diagnose
        d = diagnose.run(str(self.fix / "기본서.pdf"), CFG, layout_range=range(1, 4))
        self.assertTrue(d["text_layer"])                 # 1) 텍스트 레이어
        self.assertEqual(d["columns"], 1)                # 2) 단 구성
        self.assertTrue(d["footnote"]["rule_found"])     #    각주 구분선
        self.assertGreater(d["hanja_in_sample"], 0)      #    한자
        self.assertEqual(d["cases"]["bad_open_brackets"], [])
        self.assertTrue(d["color"]["span_rgb_available"])   # 3) 색상
        self.assertEqual(d["color"]["distinct_colors"], 1)
        self.assertTrue(d["sidenote"]["found"])          # 4) 옆번호
        self.assertEqual(d["sidenote"]["merged_suspect"], [])

    def test_변환_결과가_지침_요구를_지킨다(self):
        from book2md.pipeline import Pipeline
        out = self.tmp / "output"
        for name, profile_name in (("기본서", "textbook"), ("사례집", "casebook")):
            prof = get_profile(CFG, profile_name)
            Pipeline(self.fix / f"{name}.pdf", CFG, prof, out / name,
                     out / "_reports", out / "_work" / name, "pymupdf",
                     None, log=lambda *a: None).run("extract")
        book = (out / "기본서").glob("*.md").__next__().read_text(encoding="utf-8")
        self.assertIn("(91다43695*)", book)                    # ④ 별표 보존
        self.assertIn("standard: true", book)                  #    → 프론트매터
        self.assertIn("`[확객시전]`", book)                     # ② 두문자
        self.assertIn("`(11)`", book)                          # ⑨ 기출연도
        self.assertNotIn("sE-8", book)                         # ⑩ 옆번호는 버린다
        self.assertIn("> ### ☑", book)                         # ⑧
        self.assertIn("[^264]:", book)                         # ⑥ 각주 정의
        self.assertIn("[^264]", book.split("[^264]:")[0])      #    본문 참조
        self.assertIn('label: "청구확장 취지 명백히 표시"', book)  # ③
        self.assertIn("==", book)                              # ⑤ 색상 강조
        case = (out / "사례집").glob("*.md").__next__().read_text(encoding="utf-8")
        self.assertIn("`10점`", case)
        self.assertIn("`2.5`", case)
        self.assertIn("> 불법행위로", case)                      # 지문 분리

        from book2md.crosscheck import crosscheck
        text, mismatches = crosscheck(out / "기본서", out / "사례집", CFG)
        self.assertEqual(mismatches, 1)                        # 확객시전 vs 확객시젠
        self.assertIn("확객시젠", text)
        self.assertIn("확객시전", text)


class 되풀이꼬리말(unittest.TestCase):
    """쪽마다 되풀이되는 꼬리말이 장 제목으로 둔갑하지 않아야 한다 (§4.1)."""

    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf  # noqa: F401
        except Exception:
            raise unittest.SkipTest("PyMuPDF 없음")
        sys.path.insert(0, str(ROOT / "tests"))
        import make_fixtures
        if not Path(make_fixtures.FONT).exists():
            raise unittest.SkipTest("한글 글꼴 없음")
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf = cls.tmp / "여러쪽.pdf"
        make_fixtures.scanned_book(cls.pdf, pages=6)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", "/nonexistent"), ignore_errors=True)

    def _convert(self, out_name, pages=None):
        from book2md.pipeline import Pipeline
        out = self.tmp / out_name
        prof = get_profile(CFG, "textbook")
        Pipeline(self.pdf, CFG, prof, out / "기본서", out / "_reports",
                 out / "_work", "pymupdf", pages, log=lambda *a: None).run("extract")
        return "\n".join(p.read_text(encoding="utf-8")
                          for p in sorted((out / "기본서").glob("*.md")))

    def test_꼬리말이_본문에도_제목에도_없다(self):
        md = self._convert("full")
        self.assertNotIn("윤곽 민사소송법", md)
        self.assertNotIn("CHAPTER 05", md)
        self.assertIn("### 040 논점 1", md)
        self.assertIn("(70다1000)", md)

    def test_쪽_범위를_잘라도_꼬리말을_찾는다(self):
        """범위 안에 한 번밖에 없는 장 꼬리말도 빠져야 한다.

        머리말·꼬리말은 책 전체의 성질이므로 문서 전체에서 찾는다.
        """
        md = self._convert("partial", pages=range(4, 6))    # 마지막 두 쪽
        self.assertNotIn("CHAPTER 06", md)
        self.assertNotIn("윤곽 민사소송법", md)
        self.assertIn("### 044 논점 5", md)


class 한번에(unittest.TestCase):
    """convert all — 폴더 안 PDF 를 진단→변환→검증→교차검증까지 (§8)."""

    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf  # noqa: F401
        except Exception:
            raise unittest.SkipTest("PyMuPDF 없음")
        sys.path.insert(0, str(ROOT / "tests"))
        import make_fixtures
        if not Path(make_fixtures.FONT).exists():
            raise unittest.SkipTest("한글 글꼴 없음")
        cls.tmp = Path(tempfile.mkdtemp())
        cls.src = cls.tmp / "src"
        cls.src.mkdir()
        make_fixtures.scanned_book(cls.src / "기본서.pdf", pages=4)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", "/nonexistent"), ignore_errors=True)

    def test_폴더째_돌리고_파일별_리포트를_남긴다(self):
        from book2md.cli import main
        out = self.tmp / "out"
        code = main(["--config", str(ROOT / "config.yaml"), "all",
                     str(self.src), "--out", str(out)])
        self.assertIn(code, (0, 1))          # FAIL 이면 1, 아니면 0
        reports = out / "_reports"
        # 파일마다 이름 붙인 사본이 남아야 여러 소스를 견줄 수 있다
        for name in ("validation-기본서.md", "warnings-기본서.md",
                     "caselist-기본서.txt", "mnemonics-기본서.txt",
                     "diagnosis-기본서.md"):
            self.assertTrue((reports / name).exists(), name)
        md = "\n".join(p.read_text(encoding="utf-8")
                        for p in (out / "기본서").glob("*.md"))
        self.assertIn("### 040 논점 1", md)
        self.assertNotIn("윤곽 민사소송법", md)      # 꼬리말은 빠진다


class 스캔본(unittest.TestCase):
    """실물 교재의 꼴: 종이 그림 + OCR 텍스트 레이어.

    글자 색이 전부 검정이라 강조색은 그림에만 남고(§2.4), 여는 괄호가 `＜` 로,
    닫는 대괄호는 통째로, 각주 참조는 `NNN)` 로 흘러나온다.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import pymupdf  # noqa: F401
        except Exception:
            raise unittest.SkipTest("PyMuPDF 없음")
        sys.path.insert(0, str(ROOT / "tests"))
        import make_fixtures
        if not Path(make_fixtures.FONT).exists():
            raise unittest.SkipTest("한글 글꼴 없음")
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pdf = cls.tmp / "스캔기본서.pdf"
        make_fixtures.scanned_textbook(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmp", "/nonexistent"), ignore_errors=True)

    def test_진단이_스캔본임을_알아채고_그림에서_색을_찾는다(self):
        from book2md import diagnose
        d = diagnose.run(str(self.pdf), CFG, sample=1, layout_pages=1)
        self.assertTrue(d["images"]["scanned_with_text_layer"])
        self.assertEqual(d["color"]["colored_spans"], 0)      # 글자 색은 전부 검정
        self.assertEqual(d["color"]["source"], "image")
        self.assertGreater(d["color"]["image_colored_spans"], 0)   # 그림에는 있다

    def test_변환이_네_가지를_모두_지킨다(self):
        from book2md.pipeline import Pipeline
        out = self.tmp / "out"
        prof = get_profile(CFG, "textbook")
        verdict = Pipeline(self.pdf, CFG, prof, out / "기본서", out / "_reports",
                           out / "_work", "pymupdf", None,
                           log=lambda *a: None).run("extract")
        md = next((out / "기본서").glob("*.md")).read_text(encoding="utf-8")
        self.assertEqual(verdict, "PASS")
        # §2.1 ＜ → ( 복원, 별표 보존
        self.assertIn("(74다1557)", md)
        self.assertIn("(91다43695*)", md)
        self.assertIn("standard: true", md)
        # §2.2 빠진 닫는 괄호 복구 + 자리로 두문자 판정
        self.assertIn("`[일나시 나소시]`", md)
        # §2.4 그림 픽셀에서 읽은 강조색
        self.assertIn("==확장의 뜻을 밝힌 때에는 전부에 미친다==", md)
        # §2.5 'NNN)' 꼴 각주: 정의와 본문 참조가 모두 살아 있다
        self.assertIn("[^264]:", md)
        self.assertIn("[^265]", md.split("[^264]:")[0])
        # 낱말 사이 공백 복원 — 없으면 뒤 처리가 못 읽는다
        self.assertIn("수량적 가분 채권을 분할 청구하는 것을 말한다.", md)
        # 제목이 색을 입고 있어도 헤딩으로 잡힌다
        self.assertIn("### 046 일부청구", md)
        self.assertIn("#### IV. 시효중단 `(11)`", md)
        # ⑩ 옆번호는 좌표로 떼어 내되 남기지 않는다 (legend.sidenote.mode: drop).
        # 떼어 내는 일 자체는 계속 한다 — 안 하면 본문 글자에 들러붙는다.
        self.assertNotIn("sE-8", md)
        # 번호와 제목이 다른 조각으로 떨어진 것을 한 줄로
        self.assertIn("**3. 判例", md)
        self.assertIn("**4. 검토**", md)
        # ⑧ ☑ 가 '0' 으로 읽혀도 박스로
        self.assertIn("> ### ☑ 실제로 청구취지 확장하지 않은 부분의 취급", md)
        self.assertIn("bonus_topics:", md)
        # ① 논점 윤곽 띠
        self.assertIn('outline: ["의의", "소송물", "시효중단", "기판력"]', md)
        # 꼬리말은 본문에도 각주에도 들어가지 않는다
        self.assertNotIn("윤곽민사소송법", md)

    def test_지난_결과물을_지우고_쓴다(self):
        """옛 파일이 남으면 검증이 같은 내용을 두 번 세어 별표가 2배가 된다."""
        from book2md.pipeline import Pipeline
        out = self.tmp / "out3"
        prof = get_profile(CFG, "textbook")

        def run():
            return Pipeline(self.pdf, CFG, prof, out / "기본서", out / "_reports",
                            out / "_work", "pymupdf", None,
                            log=lambda *a: None).run("extract")

        run()
        stale = out / "기본서" / "99_지난실행.md"
        stale.write_text("---\nsource: 기본서\nparser: pymupdf\n---\n\n"
                         "판시 (91다43695*) 이다.\n", encoding="utf-8")
        hand = out / "기본서" / "손으로_쓴_메모.md"
        hand.write_text("사람이 둔 파일. 프론트매터가 없다.\n", encoding="utf-8")
        self.assertEqual(run(), "PASS")
        self.assertFalse(stale.exists())       # 우리가 만든 옛 파일은 지운다
        self.assertTrue(hand.exists())         # 사람이 둔 파일은 건드리지 않는다

    def test_두문자_복구가_기록에_남는다(self):
        """괄호만 되돌리고 안쪽 글자는 손대지 않았음을 사람이 볼 수 있어야 한다."""
        import json
        from book2md.pipeline import Pipeline
        out = self.tmp / "out2"
        prof = get_profile(CFG, "textbook")
        pipe = Pipeline(self.pdf, CFG, prof, out / "기본서", out / "_reports",
                        out / "_work", "pymupdf", None, log=lambda *a: None)
        pipe.run("extract")
        rows = [json.loads(l) for l in pipe.changes.read_text(encoding="utf-8").splitlines()]
        kinds = {r["kind"] for r in rows}
        self.assertIn("bracket", kinds)            # ＜ → (
        self.assertIn("mnemonic", kinds)           # 닫는 대괄호 복구
        for r in rows:
            if r["kind"] == "mnemonic":
                self.assertIn("일나시 나소시", r["after"])   # 안쪽 글자 그대로


if __name__ == "__main__":
    unittest.main(verbosity=2)
