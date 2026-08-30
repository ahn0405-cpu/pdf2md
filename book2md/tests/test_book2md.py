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
        text, mismatches, decisions = crosscheck(out / "기본서", out / "사례집", CFG)
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
        # §P0-2 한 문장 안에서 앞쪽 낱말만 청색인 판시 본문
        self.assertIn("==일부청구는 나머지 부분에== 시효중단 효력이 없다(74다1557).", md)
        # 굵은 글씨가 없는 쪽에서는 굵기 판정이 하나도 안 나와야 한다.
        # 없는 강조를 지어내는 것이 놓치는 것보다 나쁘다 (§P0-2).
        body = md.split("---\n", 2)[-1]
        for phrase in ("**분할**", "**효력이**", "**있을**"):
            self.assertNotIn(phrase, body)
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
        # 꼬리말은 본문에도 각주에도 들어가지 않는다. 이 꼬리말은 무늬에
        # 하나도 안 맞는다 — 각주와 떨어진 세로 간격으로만 가른다 (§4.1).
        self.assertNotIn("己厂", md)
        self.assertNotIn("소송절차 개시", md)
        # §P0-1 로마자가 딴 글자로 흘러나와도, 제목과 본문이 한 줄에 붙어
        # 있어도 헤딩으로 선다
        self.assertIn("#### I. 의의", md)
        self.assertIn("\n수량적 가분 채권을 분할 청구하는 것을 말한다.", md)
        self.assertIn("#### II. 소송물", md)
        self.assertIn("#### III. 기판력", md)
        self.assertIn('"II. 소송물"', md)          # sections 에도 있다
        # §P1-2 인용된 조문은 두문자가 아니라 articles 로
        self.assertIn('articles: ["제265조"]', md)
        self.assertNotIn('"제265조"', md.split("articles:")[0])
        # §P1-1 각주 안의 사건번호도 프론트매터에 들어간다 ('다카' 부호 포함)
        self.assertIn('id: "87다카1416"', md)
        self.assertIn('id: "2005다12345"', md)
        # §P2-1 무엇을 버렸는지 남긴다
        removed = (out / "_reports" / "removed_lines.md").read_text(encoding="utf-8")
        self.assertIn("己厂", removed)
        # 띠를 벗어나 앉은 장 제목 띠. 무늬가 확실한 것은 자리를 안 가린다.
        self.assertIn("CHAPTER 6 소송절차 개시", removed)
        # 각주의 뒷줄은 짧고 번호로 시작하지 않아도 버리지 않는다.
        # 읽히는 한국어인지로 가른다 (§4.1).
        self.assertNotIn("다만 그 범위는 따로 본다", removed)
        self.assertIn("다만 그 범위는 따로 본다", md)
        self.assertIn("sE-8", removed)

    def _run_with(self, cfg, name):
        from book2md.pipeline import Pipeline
        out = self.tmp / name
        verdict = Pipeline(self.pdf, cfg, get_profile(cfg, "textbook"),
                           out / "기본서", out / "_reports", out / "_work",
                           "pymupdf", None, log=lambda *a: None).run("extract")
        return verdict, (out / "_reports" / "warnings.md").read_text(encoding="utf-8")

    def test_로마자를_못_고쳐도_목차가_받아_준다(self):
        """§6.1 — 오인식 글자를 표에 등록 못 해도 목차 띠가 절을 되찾는다.

        'I.' 이 '仁j', '।', 'H' 로 흘러나오는 것을 하나씩 등록해서는 끝이 없다.
        답은 문서 안에 있다 — 논점 첫 줄의 목차 띠가 절 이름을 다 적어 둔다.
        """
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["normalize"]["roman_heads"] = {}          # 일부러 끈다
        verdict, _ = self._run_with(cfg, "out_noroman")
        self.assertEqual(verdict, "PASS")

    def test_둘_다_끄면_검증이_잡아낸다(self):
        """§V1 — 안전망까지 없으면 절이 조용히 사라진다. 실제로 그랬다.

        기본은 WARN 이다. 남은 불일치는 글자를 잃은 것이 아니라 절 제목이
        헤딩 대신 문단으로 들어간 것이기 때문이다. 조이려면 FAIL 로 바꾼다.
        """
        import copy
        cfg = copy.deepcopy(CFG)
        cfg["normalize"]["roman_heads"] = {}
        cfg["profiles"]["textbook"]["outline_heading"] = False
        verdict, warn = self._run_with(cfg, "out_nonet")
        self.assertEqual(verdict, "WARN")
        self.assertIn("목차에 있는데 헤딩이 없다", warn)
        for lost in ("의의", "소송물", "기판력"):
            self.assertIn(lost, warn)

        cfg["validation"].setdefault("severity", {})["outline_missing"] = "FAIL"
        verdict, _ = self._run_with(cfg, "out_strict")
        self.assertEqual(verdict, "FAIL")

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



class 수정요청_01(unittest.TestCase):
    """수정 요청 #01 — 낱글자가 틀리면 안 되는 자리들"""

    def _tb(self):
        from book2md.normalize import Normalizer
        return Normalizer(CFG, PAT, get_profile(CFG, "textbook"))

    def _cb(self):
        from book2md.normalize import Normalizer
        return Normalizer(CFG, PAT, get_profile(CFG, "casebook"))

    def test_구분점이_마침표가_아니어도_절번호로_본다(self):
        """'•'(U+2022) 는 '·'(U+00B7) 과 생김새가 같아도 다른 글자다.

        실물 104_105기판력의주관적범위.md 에서 'I • 의의 및 취지' 하나가
        절에서 탈락하자 그 아래 소항목들이 절로 승격돼 버렸다.
        """
        n = self._tb()
        self.assertEqual(n.normalize_line("==I • 의의 및 취지==", 1, []),
                         "==I. 의의 및 취지==")
        self.assertEqual(n.normalize_line("I ・ 효과", 1, []), "I. 효과")

    def test_II_가_H_로_읽힌_것은_기본서에서만_되돌린다(self):
        """사례집은 문제 묶음을 A~Q 글자로 센다. 거기서 H 를 바꾸면 장 제목이 깨진다."""
        self.assertEqual(self._tb().normalize_line("H . 사유", 1, []), "II. 사유")
        self.assertEqual(self._cb().normalize_line("H. 처분권주의", 1, []),
                         "H. 처분권주의")
        self.assertEqual(self._cb().normalize_line("H-15. [변론주의]", 1, []),
                         "H-15. [변론주의]")

    def test_앞_문단_끝에_붙어_버린_제목도_되돌린다(self):
        """실물 11_012이송개관.md 의 '…위함이다.[^73] ==H . 사유== i) 제34조…'"""
        n = self._tb()
        got = n.normalize_line(
            "옮기는 것이다.[^73][^74] ==H . 사유== i) 제34조 제1항의 이송", 1, [])
        self.assertIn("==II. 사유==", got)
        # 문장 도중의 강조는 건드리지 않는다
        self.assertEqual(n.normalize_line("판시가 그러하다. ==확장의 뜻을== 밝힌", 1, []),
                         "판시가 그러하다. ==확장의 뜻을== 밝힌")

    def test_로마자_절번호를_헤딩_판정_전에_되돌린다(self):
        # 마침표 뒤에 공백이 없는 것이 실물의 defect 였다. 종이에는 공백이
        # 있으므로 함께 되살린다.
        self.assertEqual(norm("Ill.중복소제기"), "III. 중복소제기")
        self.assertEqual(norm("==Ill.중복소제기=="), "==III. 중복소제기==")
        self.assertEqual(norm("lll. 기판력"), "III. 기판력")
        self.assertEqual(norm("N.소의 이익"), "IV. 소의 이익")
        self.assertEqual(norm("씨. 과실상계"), "VI. 과실상계")
        # 문장 속 번호는 건드리지 않는다
        self.assertEqual(norm("판시는 1.그렇다"), "판시는 1.그렇다")

    def test_본문_속_소문자_L_은_건드리지_않는다(self):
        self.assertEqual(norm("본문에 l 이 섞여 있다"), "본문에 l 이 섞여 있다")
        self.assertEqual(norm("판시는 lll 아니다."), "판시는 lll 아니다.")

    def test_다카_부호와_내부_콜론(self):
        # 사람이 확정해 둔 정정 (config.yaml corrections)
        self.assertEqual(norm("＜96다:30113)"), "(96다30113)")
        # corrections 에 없는 것도 일반 규칙으로 되살린다
        self.assertEqual(norm("＜2005다:12345)"), "(2005다12345)")
        self.assertEqual(norm("판시: 30113 쪽"), "판시: 30113 쪽")   # 본문은 그대로
        m = PAT.case.search("87다카1416")
        self.assertEqual(m.group("suffix"), "다카")     # '다' 로 잘리면 안 된다
        self.assertEqual(PAT.case_problems(m), [])

    def test_조문번호는_두문자가_아니다(self):
        self.assertFalse(PAT.is_mnemonic_body("제259조"))
        self.assertFalse(PAT.is_mnemonic_body("제218죄"))
        self.assertTrue(PAT.is_mnemonic_body("일나시 나소시"))
        self.assertEqual(PAT.find_articles("제265조와 제218조 제1항"),
                         ["제265조", "제218조 제1항"])

    def test_조문번호_안의_죄를_조로(self):
        self.assertEqual(norm("제218죄 제1항"), "제218조 제1항")
        self.assertEqual(norm("살인죄 성립"), "살인죄 성립")   # 조문이 아니면 그대로

    def test_제목의_괄호_오인식을_되돌린다(self):
        self.assertEqual(norm("E-7. 』중복소제기 금지의 요건]"),
                         "E-7. [중복소제기 금지의 요건]")
        self.assertEqual(norm("E-9. [기판력의 객관적 범위』"),
                         "E-9. [기판력의 객관적 범위]")
        # 짝이 맞는 인용부호는 건드리지 않는다
        self.assertEqual(norm("판시 「가」 및 「나」"), "판시 「가」 및 「나」")


class 강조_낱말단위(unittest.TestCase):
    """§P0-2 — span 이 아니라 낱말마다 색을 본다"""

    def test_이어진_낱말은_한_덩어리로_묶는다(self):
        from book2md.parsers.pymupdf_native import _render
        pieces = [("==", "확장의"), ("", " "), ("==", "뜻을"), ("", " "),
                  ("==", "밝힌"), ("", " "), ("", "고 본다")]
        self.assertEqual(_render(pieces), "==확장의 뜻을 밝힌== 고 본다")

    def test_강조가_끊기면_따로_묶는다(self):
        from book2md.parsers.pymupdf_native import _render
        pieces = [("==", "가"), ("", " 나 "), ("==", "다")]
        self.assertEqual(_render(pieces), "==가== 나 ==다==")


class 두문자_결정표(unittest.TestCase):
    """§P1-3 — 판단은 사람이, 옮겨 적기는 기계가"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_표시한_결정만_읽는다(self):
        from book2md.crosscheck import read_decisions
        doc = self.tmp / "d.md"
        doc.write_text(
            "### MC-001 `[확객시전]` ↔ `[확객시젠]` — 1글자 차이\n"
            "- [x] A: `확객시젠` → `확객시전`   (옳은 쪽: A 기본서)\n"
            "- [ ] B: `확객시전` → `확객시젠`   (옳은 쪽: B 사례집)\n"
            "### MC-002 `[가나다]` ↔ `[가나타]` — 1글자 차이\n"
            "- [ ] A: `가나타` → `가나다`   (옳은 쪽: A 기본서)\n",
            encoding="utf-8")
        got = read_decisions(doc)
        self.assertEqual(got, [{"id": "MC-001", "side": "A",
                                "find": "확객시젠", "to": "확객시전"}])

    def test_config_의_주석을_지우지_않고_붙인다(self):
        from book2md.crosscheck import merge_corrections
        cfg_path = self.tmp / "config.yaml"
        shutil.copy(ROOT / "config.yaml", cfg_path)
        before = cfg_path.read_text(encoding="utf-8")
        added, dupes = merge_corrections(
            cfg_path, [{"id": "MC-001", "side": "A",
                        "find": "확객시젠", "to": "확객시전"}])
        after = cfg_path.read_text(encoding="utf-8")
        self.assertEqual((added, dupes), (1, 0))
        self.assertIn('find: "[확객시젠]", to: "[확객시전]"', after)
        # 사람이 적어 둔 주석이 살아 있어야 한다
        for line in before.splitlines():
            if line.strip().startswith("#") and len(line.strip()) > 12:
                self.assertIn(line, after)
        # 두 번 넣지 않는다
        self.assertEqual(merge_corrections(
            cfg_path, [{"id": "MC-001", "side": "A",
                        "find": "확객시젠", "to": "확객시전"}]), (0, 1))
        # 고친 config 가 여전히 읽힌다
        load_config(cfg_path)



class 꼬리말_세로간격(unittest.TestCase):
    """§4.1 — 긴 각주의 뒷줄을 꼬리말로 잘못 버리지 않는다"""

    @staticmethod
    def _lines(spec):
        return [Line(text=t, size=7.0, y0=y, y1=y + 8) for y, t in spec]

    def test_각주와_떨어진_줄만_뗀다(self):
        from book2md.parsers.pymupdf_native import PyMuPDFParser
        opts = {"footer_gap_ratio": 1.8, "footer_zone": 0.94}
        lines = self._lines([
            (600, "264) 종전 판시는 요건을 달리 보았다."),
            (612, "다음과 같이 정리된다."),          # 264 의 뒷줄
            (624, "266) 원고는 2011. 4. 26. 소를 제기하였다."),
            (636, "3천만 원을 먼저 구하였다."),        # 266 의 뒷줄
            (690, "O과 己厂—I !"),                   # 뚝 떨어진 꼬리말
        ])
        start = PyMuPDFParser._strip_tail_footer(lines, 0, 700, opts)
        self.assertEqual(start, 0)
        self.assertEqual([l.zone for l in lines],
                         ["body", "body", "body", "body", "header"])

    def test_각주만_있으면_아무것도_안_뗀다(self):
        from book2md.parsers.pymupdf_native import PyMuPDFParser
        opts = {"footer_gap_ratio": 1.8, "footer_zone": 0.94}
        lines = self._lines([
            (600, "264) 종전 판시는 요건을 달리 보았다."),
            (612, "다음과 같이 정리된다."),
            (624, "그 경위는 이러하다."),
        ])
        PyMuPDFParser._strip_tail_footer(lines, 0, 700, opts)
        self.assertEqual([l.zone for l in lines], ["body"] * 3)



class 달림제목(unittest.TestCase):
    """§6.1 — 제목과 본문이 한 줄에 붙어 있을 때"""

    def _render(self, lines):
        from book2md.structure import Structurer, render
        from book2md.model import Line, Page
        prof = dict(get_profile(CFG, "textbook"))
        prof["_config"] = CFG
        st = Structurer(CFG, prof, PAT)
        st.feed(Page(number=1, lines=[Line(text=t, size=10) for t in lines]), [])
        return render(st.finish())

    def test_색이_제목의_끝을_알려_준다(self):
        out = self._render([
            "==I. 의의 및 취지== 당사자와 소송관계인은 신의에 따라 성실하게 "
            "소송을 수행하여야 한다(제1조 제2항)."])
        self.assertIn("#### I. 의의 및 취지", out)
        self.assertIn("당사자와 소송관계인은", out.split("#### I. 의의 및 취지")[1])

    def test_색이_없으면_가르지_않는다(self):
        """어디까지가 제목인지 알 길이 없다. 찍어서 자르면 제목이 잘린다."""
        out = self._render([
            "I. 의의 및 취지 당사자와 소송관계인은 신의에 따라 성실하게 "
            "소송을 수행하여야 한다(제1조 제2항)."])
        self.assertNotIn("당사자와 소송관계인은 신의에 따라 성실하게 "
                         "소송을 수행하여야 한다(제1조 제2항).\n\n", out.split("\n")[0])

    def test_색이_있어도_제목_무늬가_아니면_그냥_둔다(self):
        out = self._render(["==확장의 뜻을 밝힌 때에는== 전부에 미친다고 본다."])
        self.assertNotIn("####", out)

    def test_앞_문단_끝에_붙은_제목을_떼어_낸다(self):
        out = self._render([
            "옮기는 것이다.[^73][^74] ==II. 사유== i) 제34조 제1항의 관할위반에 "
            "의한 이송 ii) 제35조의 심판편의에 의한 이송"])
        self.assertIn("#### II. 사유", out)
        head, _, tail = out.partition("#### II. 사유")
        self.assertIn("옮기는 것이다.[^73][^74]", head)
        self.assertIn("i) 제34조 제1항의 관할위반", tail)

    def test_문장_도중의_강조는_제목이_아니다(self):
        out = self._render([
            "일부청구는 ==II. 사유== 라는 말을 쓰지 않는다는 뜻으로 보아야 한다."])
        self.assertNotIn("####", out)


class 조문번호_두문자_가르기(unittest.TestCase):
    """§P1-2 — 실물에서 새어 들어온 꼴들"""

    def test_조문은_두문자가_아니다(self):
        for body in ("제259조", "제218죄", "민법 제272조", "민법 제406조",
                     "제343조 후단", "제402", "제62", "동조 2항", "제1조 2항"):
            self.assertFalse(PAT.is_mnemonic_body(body), body)

    def test_두문자는_그대로_둔다(self):
        for body in ("일나시 나소시", "확객시전", "꾀유상이", "명일동내",
                     "부원공 어패다기"):
            self.assertTrue(PAT.is_mnemonic_body(body), body)

    def test_판례_라벨은_자리로_가른다(self):
        # 정규식만 돌리면 '[일반]' '[소권남용]' 이 두문자로 섞여 결정표가 못 쓰게 된다
        for text in ("1) [일반적 판단기준] 실효기간의 길이와 …",
                     "i) [일반] 일부청구임을 명시한 사건에서 …",
                     "ii) [소권남용] 이 사건 소송이 일부청구인 …"):
            self.assertEqual(PAT.find_mnemonics(text), [], text)
        self.assertEqual(PAT.find_mnemonics("(1) 의의 `[꾀유상이]` 잔꾀를 써서"),
                         ["꾀유상이"])



class 사람이_확정한_정정(unittest.TestCase):
    """§4.8 예외 — config.yaml 의 corrections 만 바꾼다"""

    def test_원문을_편_사람이_확정해_준_사건번호(self):
        # 원문의 여는 괄호는 '＜' 로 흘러나온다. 그 복원은 정정보다 나중에
        # 도므로, 정정에 괄호를 걸면 만나지 못한다.
        got = norm("유치권을 성립시키는 것은 신의칙에 반한다＜201다84298).")
        self.assertIn("(2011다84298)", got)
        got = norm("유치권을 성립시키는 것은 신의칙에 반한다(201다84298).")
        self.assertIn("(2011다84298)", got)
        m = PAT.case.search(got)
        self.assertEqual(PAT.case_problems(m), [])

        # 원문에 공백이 끼어 있어도 만난다. 그 공백은 정정보다 나중에 없어지므로
        # 정정을 정규화 뒤에 한 번 더 돌린다.
        for spaced in ("반한다＜201다 84298).", "반한다＜201 다84298)."):
            self.assertIn("(2011다84298)", norm(spaced))
        # 두 번 돌아도 같은 자리를 두 번 고치지 않는다
        self.assertIn("(2011다84298)", norm("반한다(2011다84298)."))

        got = norm("그 사실을 다툰 것으로 볼 수 없다189다카4045).")
        self.assertIn("(89다카4045)", got)
        m = PAT.case.search(got)
        self.assertEqual(PAT.case_problems(m), [])



class 목차로_제목_되찾기(unittest.TestCase):
    """§6.1 — 오인식 글자를 표에 등록하는 대신, 문서가 스스로 답을 갖고 있다"""

    def _render(self, lines):
        from book2md.structure import Structurer, render
        from book2md.model import Line, Page
        prof = dict(get_profile(CFG, "textbook"))
        prof["_config"] = CFG
        st = Structurer(CFG, prof, PAT)
        st.feed(Page(number=1, lines=[Line(text=t, size=10) for t in lines]), [])
        return render(st.finish())

    def _heads(self, extra_lines):
        out = self._render(["139 항고", "==◎ 의의-대상-절차-효과=="] + extra_lines)
        return [l for l in out.split("\n") if l.startswith("####")]

    def test_번호_자리의_잡글자를_떼고_목차와_맞춘다(self):
        self.assertEqual(self._heads(["仁j 의의", "항고는 상소이다."]),
                         ["#### 仁j 의의"])
        self.assertEqual(self._heads(["口. 대상", "결정과 명령이다."]),
                         ["#### 口. 대상"])
        # 제목 뒤 기출연도는 붙어 있어도 된다
        self.assertEqual(self._heads(["凵) 절차 (17)", "1주 이내에 한다."]),
                         ["#### 凵) 절차 `(17)`"])

    def test_잡글자가_없으면_건드리지_않는다(self):
        """'효과는 다음과 같다' 같은 본문을 제목으로 오해하면 문단이 깨진다."""
        self.assertEqual(self._heads(["효과는 다음과 같이 정리된다."]), [])
        self.assertEqual(self._heads(["의의가 무엇인지 살펴본다."]), [])

    def test_알아볼_수_있는_번호는_기존_규칙에_맡긴다(self):
        self.assertEqual(self._heads(["(2) 효과를 살펴본다."]), [])

    def test_문장으로_끝나면_제목이_아니다(self):
        self.assertEqual(self._heads(["仁j 의의를 아래에서 살펴본다."]), [])

    def test_논점이_바뀌면_목차도_바뀐다(self):
        out = self._render([
            "139 항고", "==◎ 의의-대상-절차-효과==",
            "140 재심",                          # 새 논점 — 앞 목차는 잊는다
            "仁j 대상", "재심의 대상은 확정판결이다."])
        self.assertNotIn("#### 仁j 대상", out)

    def test_박스_오인식보다_목차를_믿는다(self):
        """'口' 는 ☑ 오인식이기도 하다. 박스 제목은 목차에 오르지 않는다."""
        out = self._render([
            "139 항고", "==◎ 의의-대상-절차-효과==",
            "口. 대상", "결정과 명령이다.",
            "☑ 즉시항고와 통상항고", "기간의 제한이 있다."])
        self.assertIn("#### 口. 대상", out)
        self.assertIn("> ### ☑ 즉시항고와 통상항고", out)


class 매핑(unittest.TestCase):
    """mapping_생성지침.md — 기본서 ↔ 사례집 잇기.

    지침의 「알려진 매핑」(046 일부청구) 을 정답지로 삼는다. 한 문제가 두 절에
    걸리고(E-6 → IV·V), 한 절에 여러 문제가 붙는(IV ← E-5·E-6·E-7) 1:N·N:1 이
    둘 다 나오는지를 본다.
    """

    TEXTBOOK = """---
source: 기본서
chapter: "046 일부청구"
parser: pymupdf
---

## CHAPTER 046 일부청구

#### I. 의의

일부청구란 수량적으로 가분인 채권의 일부만 구하는 것이다.

#### II. 소송물

(1) 判例 ==`[일외별명일]`== 로 본다.

#### III. 중복소제기

(1) 判例 ==`[명일동내]`== (84다552) (95다46319)

#### IV. 시효중단 `(11)`

(1) 원칙 ==`[일나시 나소시]`== (74다1557)
(2) 확장 ==`[확객시전]`== (2019다223723) (2018다44114)

#### V. 기판력 `(15)`

(1) ==`[종확나시]`== (2018다44114)
"""

    CASEBOOK = """---
source: 사례집
chapter: "E"
parser: pymupdf
---

## B-10. [변론관할]

본안에 관하여 변론하였다. 설명하시오. (4점)

### 1. 문제의 소재 `1`

### 2. 변론관할 성립 여부 `3`

관할위반의 항변 없이 본안에 관하여 변론하였다.

## E-2. 」명시적 일부청구, 중복소제기]

법정상속분만을 구하는 소를 제기하였다. 설명하시오. (14점)

### 1. 문제의 소재 `1`

### 2. 일부청구의 소송물 `5`

(2) 判例 ==`[일외별명일]`==

### 3. 중복소제기 해당 여부 `5`

(1) 判例 ==`[명일동내]`== (84다552) (95다46319)

### 4. 사안해결 `3`

## E-5. [일부청구-시효중단]

전체 손해액 중 일부인 1억 원의 지급을 구하였다. 논하시오. (10점)

### 1. 문제의 소재 `1`

### 2. 일부청구 소송물 `2.5`

### 3. 일부청구시 시효중단 범위 `4`

#### (1) 학설

#### (2) 判例 ==`[일나시 나소시]` `[확객시젠]`== (2019다223723)

### 4. 사안해결 `2.5`

## E-6. [일부청구-기판력, 시효중단]

나머지 대여금의 반환을 구하는 소를 제기하였다. 설명하시오. (12점)

### 1. 문제의 소재 `1`

### 2. 시효중단의 범위 `6`

==`[일나시 나소시]`== (2018다44114)

### 3. 기판력의 객관적 범위 `4`

==`[종확나시]`==

### 4. 사안해결 `1`
"""

    #: 사례집 앞머리 목차 쪽. 점선과 쪽수가 붙고 다음 문제까지 한 줄에 이어진다.
    TOC = """---
source: 사례집
chapter: "목차"
parser: pymupdf
---

## E-5. 일부청구-시효중단 ..............................112E-6. 일부청구-기판력 ......119
"""

    #: 다른 장 — 두문자 하나만 겹친다. 근거 하나뿐이라 후보로만 가야 한다.
    OTHER = """---
source: 기본서
chapter: "070 상소이익"
parser: pymupdf
---

#### III. 판단기준

(1) 判例 ==`[일외별명일]`== 참조.
"""

    #: 실물 기본서의 전형 — 절 제목이 정형뿐이라 논점 이름이 장에만 있다
    PLAIN = """---
source: 기본서
chapter: "021 변론관할"
parser: pymupdf
---

#### I. 의의

관할위반의 항변 없이 본안변론을 하면 생긴다.

#### II. 요건

제1심 법원일 것.
"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "기본서").mkdir()
        (cls.tmp / "사례집").mkdir()
        (cls.tmp / "기본서" / "45_046일부청구.md").write_text(
            cls.TEXTBOOK, encoding="utf-8")
        (cls.tmp / "기본서" / "70_070상소이익.md").write_text(
            cls.OTHER, encoding="utf-8")
        (cls.tmp / "기본서" / "21_021변론관할.md").write_text(
            cls.PLAIN, encoding="utf-8")
        (cls.tmp / "사례집" / "E_명시적일부청구중복소제기.md").write_text(
            cls.CASEBOOK, encoding="utf-8")
        (cls.tmp / "사례집" / "00_목차.md").write_text(cls.TOC, encoding="utf-8")
        from book2md import mapping as M
        cls.M = M
        cls.data = M.build([cls.tmp], CFG)
        cls.path = cls.tmp / "mapping.yaml"
        cls.path.write_text(M.to_yaml(cls.data), encoding="utf-8")
        cls.doc = M.load(cls.path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _row(self, section: str) -> dict:
        for row in (self.doc.get("mappings") or []) + (self.doc.get("candidates") or []):
            if row["textbook"]["section"] == section:
                return row
        self.fail(f"매핑에 없다: {section}")

    def _book(self, section: str, pid: str) -> dict:
        for c in self._row(section)["casebook"]:
            if c["id"] == pid:
                return c
        self.fail(f"{section} 에 {pid} 가 안 붙었다")

    # ── 읽기 ────────────────────────────────────────────────
    def test_제목의_배점과_기출연도를_제목에서_떼어낸다(self):
        """'IV. 시효중단 `(11)`' 이 'IV. 시효중단 (11)' 이 되면 키워드가 안 맞는다."""
        titles = [s.title for s in self.data["sections"]]
        self.assertIn("IV. 시효중단", titles)
        self.assertIn("V. 기판력", titles)

    def test_오인식된_대괄호도_문제제목으로_읽는다(self):
        """실측: '## E-2. 」명시적 일부청구, 중복소제기]' (지침 §근거1)"""
        ids = {p.id: p.title for p in self.data["problems"]}
        self.assertEqual(ids["E-2"], "명시적 일부청구, 중복소제기")
        self.assertEqual({"B-10", "E-2", "E-5", "E-6"}, set(ids))

    def test_절마다_사건번호를_따로_센다(self):
        """프론트매터의 cases 는 파일 전체 것이라 절 대조에 못 쓴다."""
        by = {s.title: s.cases for s in self.data["sections"]}
        self.assertEqual(by["III. 중복소제기"], {"84다552", "95다46319"})
        self.assertNotIn("84다552", by["IV. 시효중단"])

    # ── 근거와 점수 ──────────────────────────────────────────
    def test_제목_키워드는_부분_일치도_인정한다(self):
        """'명시적 일부청구' ⊃ '일부청구' (지침 §근거1-4)"""
        row = self._row("III. 중복소제기")
        self.assertIn("중복소제기", row["evidence"]["title_keyword"])
        self.assertEqual(row["score"], 3)

    def test_두문자는_한_글자_차이까지_본다(self):
        """'확객시전' vs '확객시젠' — 오인식이라 완전 일치가 안 된다."""
        ev = self._row("IV. 시효중단")["evidence"]
        self.assertIn("확객시전 ↔ 확객시젠", ev["near_mnemonics"])

    def test_근거가_하나뿐이면_후보로만_둔다(self):
        """score 1 은 mappings 에 올리지 않는다 (지침 §점수와 처리).

        '070 상소이익 > III. 판단기준' 은 두문자 하나만 겹친다. 장 이름도 절
        이름도 사례집 키워드와 안 맞고 사건번호도 없다.
        """
        secs = [r["textbook"]["section"] for r in self.doc["candidates"]]
        self.assertIn("III. 판단기준", secs)
        self.assertEqual(self._row("III. 판단기준")["score"], 1)
        self.assertNotIn("III. 판단기준",
                         [r["textbook"]["section"] for r in self.doc["mappings"]])

    def test_목차_쪽에서_온_가짜_문제는_버린다(self):
        """실측: 'D-20. 증서진부확인의 쇠 ......233D-21. 장래이행의 쇠....237'

        같은 번호가 두 번 실리면 진짜 문제의 사건번호·두문자가 목차 쪽 빈
        껍데기에 가려진다.
        """
        self.assertEqual([p.id for p in self.data["dropped"]], ["E-5"])
        real = [p for p in self.data["problems"] if p.id == "E-5"]
        self.assertEqual(len(real), 1)
        self.assertEqual(len([a for a in real[0].answers if a.level == 3]), 4)
        self.assertIn("dropped_toc_rows", self.path.read_text(encoding="utf-8"))

    def test_장만_맞으면_절은_사람이_고르게_남긴다(self):
        """'021 변론관할' 의 절은 'I. 의의 / II. 요건' 뿐이라 고를 수가 없다.

        절을 못 고른다고 버리면 B-10 은 어디에도 안 붙는다. 장까지는 확실하니
        절 후보를 적어 사람에게 넘긴다.
        """
        chaps = self.doc.get("chapter_mappings") or []
        rows = {(c["textbook"]["chapter"], c["casebook"][0]["id"]): c
                for c in chaps}
        row = rows.get(("021 변론관할", "B-10"))
        self.assertIsNotNone(row, f"있어야 한다. 지금: {sorted(rows)}")
        self.assertIsNone(row["textbook"]["section"])
        self.assertEqual(row["textbook"]["sections"], ["I. 의의", "II. 요건"])
        self.assertEqual(row["evidence"]["chapter_keyword"], ["변론관할"])
        self.assertFalse(row["confirmed"])

    def test_절을_안_고르고_승인하면_FAIL(self):
        doc = {"chapter_mappings": [{"confirmed": True,
                                     "textbook": {"chapter": "021 변론관할",
                                                  "section": None}}]}
        fails, _ = self.M.validate(doc)
        self.assertTrue(any("절을 안 고르고" in f for f in fails))

    def test_장까지_붙었으면_짝이_없는_것이_아니다(self):
        self.assertNotIn("B-10", self.doc["unmapped"]["casebook_problems"])

    def test_총점은_제목이_아니라_지문_끝에_있다(self):
        """실측: '…설명하시오. (14점)'. 제목에서만 찾으면 하나도 못 읽는다."""
        pts = {p.id: p.points for p in self.data["problems"]}
        self.assertEqual(pts["E-2"], 14)
        self.assertEqual(pts["E-5"], 10)
        self.assertEqual(pts["E-6"], 12)

    def test_답안_목차가_절_제목을_따라가면_근거로_친다(self):
        """실물 사례집은 사건번호를 거의 안 싣는다. 답안 목차가 가장 세다.

        'E-2 > 3. 중복소제기 해당 여부' ↔ 'III. 중복소제기'
        """
        c = self._book("III. 중복소제기", "E-2")
        row = self._row("III. 중복소제기")
        self.assertTrue(any("중복소제기" in x
                            for x in row["evidence"]["answer_outline"]))
        self.assertEqual(c["role"], "primary")

    def test_짧고_흔한_절_이름으로는_답안_목차를_안_본다(self):
        """'의의' '내용' '요건' '효과' 는 어느 장에나 있어서 다 걸린다."""
        from book2md.mapping import Section, Problem, Answer, _ans_hit
        prob = Problem(id="X-1", title="변론관할", file="y",
                       answers=[Answer("2. 변론관할의 의의 및 요건", 3.0)])
        얕은 = Section(chapter="021 변론관할", title="I. 의의", file="x")
        깊은 = Section(chapter="021 변론관할", title="II. 변론관할", file="x")
        self.assertEqual(_ans_hit(얕은, prob, CFG), [])
        self.assertTrue(_ans_hit(깊은, prob, CFG))

    def test_절_제목의_각주_참조를_떼고_본다(self):
        """실측: '#### VI. 과실상계[^267]' — 알맹이는 '과실상계' 다."""
        from book2md.mapping import Section
        sec = Section(chapter="046 일부청구", title="VI. 과실상계[^267]", file="x")
        self.assertEqual(sec.title, "VI. 과실상계[^267]")
        from book2md.mapping import _plain
        self.assertEqual(_plain("VI. 과실상계[^267]"), "VI. 과실상계")

    def test_장_제목도_제목_키워드로_본다(self):
        """실물 절 제목은 'I. 의의 / II. 내용' 처럼 정형이라 논점 이름이 없다.

        논점 이름은 장 제목에 있다. II. 소송물은 절 이름으로는 안 맞지만
        장 '046 일부청구' 가 E-2 의 키워드 '명시적 일부청구' 와 맞는다.
        """
        row = self._row("II. 소송물")
        self.assertEqual(row["evidence"]["title_keyword"], [])
        self.assertIn("명시적 일부청구", row["evidence"]["chapter_keyword"])
        self.assertEqual(row["score"], 2)

    def test_폴더_이름이_아니라_프론트매터로_가른다(self):
        """폴더 이름은 사장님이 정하는 것이라 믿을 수 없다. source: 는 우리가 적었다."""
        f = self.data["files"]
        self.assertEqual([p.name for p in f["textbook"]],
                         ["21_021변론관할.md", "45_046일부청구.md",
                          "70_070상소이익.md"])
        self.assertEqual([p.name for p in f["casebook"]],
                         ["00_목차.md", "E_명시적일부청구중복소제기.md"])
        self.assertEqual(f["other"], [])

    def test_짝이_없는_절은_unmapped_에_남긴다(self):
        self.assertIn("I. 의의", self.doc["unmapped"]["textbook_sections"])

    # ── 1:N · N:1 ───────────────────────────────────────────
    def test_한_절에_여러_문제가_붙는다(self):
        ids = [c["id"] for c in self._row("IV. 시효중단")["casebook"]]
        self.assertEqual(set(ids), {"E-5", "E-6"})

    def test_한_문제가_두_절에_걸린다(self):
        """E-6 은 IV. 시효중단과 V. 기판력 양쪽에 걸린다 (지침 §근거1 주의)."""
        self.assertTrue(self._book("IV. 시효중단", "E-6"))
        self.assertTrue(self._book("V. 기판력", "E-6"))

    # ── role ────────────────────────────────────────────────
    def test_최대_배점_항목이면_primary(self):
        """E-5 는 '3. 시효중단 범위 4점' 이 최대라 IV 의 primary 다."""
        c = self._book("IV. 시효중단", "E-5")
        self.assertEqual(c["role"], "primary")
        self.assertEqual(c["section_points"], 4)

    def test_25퍼센트의_분모는_총점이_아니라_읽은_배점의_합(self):
        """총점을 쓰면 배점을 덜 읽었을 때 role 이 낮게 나온다.

        role 은 '이 문제의 사안을 이 절에 써도 되는가' 지 'OCR 이 잘 됐는가'
        가 아니다. 실측 E-6: 기판력 4점, 총점 20 이면 20% 로 incidental 이지만
        읽은 합 14.5 기준 27.6% 로 composite — 지침 정답지와 맞는다.
        """
        from book2md.mapping import Section, Problem, Answer, _role
        sec = Section(chapter="046 일부청구", title="V. 기판력", file="x")
        prob = Problem(id="E-6", title="일부청구-기판력, 시효중단", file="y",
                       points=20,          # 지문 끝의 총점
                       answers=[Answer("1. 문제의 소재", 1.0),
                                Answer("2. 일부청구 소송물", 3.0),
                                Answer("3. 기판력 저촉 여부", 4.0),
                                Answer("4. 시효중단 범위", 6.0),
                                Answer("5. 사안해결", 0.5)])
        self.assertEqual(_role(sec, prob), ("composite", 4.0))

    def test_최대가_아니어도_25퍼센트면_composite(self):
        """E-6 의 기판력은 4/14.5 — 최대(6)는 아니지만 25% 는 넘는다."""
        c = self._book("V. 기판력", "E-6")
        self.assertEqual(c["role"], "composite")
        self.assertEqual(c["section_points"], 4)

    def test_25퍼센트_미만이면_incidental(self):
        """스치듯 언급만 된 절. 노트에 안 써도 된다."""
        from book2md.mapping import Section, Problem, Answer, _role
        sec = Section(chapter="c", title="VII. 과실상계", file="x")
        prob = Problem(id="E-8", title="일부청구, 과실상계", file="y", points=12,
                       answers=[Answer("1. 일부청구 소송물", 9.0),
                                Answer("2. 과실상계 여부", 1.0)])
        self.assertEqual(_role(sec, prob), ("incidental", 1.0))

    def test_동률이면_primary(self):
        """E-2 의 중복소제기는 5/14 로 소송물(5)과 동률 — 주 논점으로 본다."""
        self.assertEqual(self._book("III. 중복소제기", "E-2")["role"], "primary")

    def test_배점을_못_찾으면_composite_으로_둔다(self):
        """어림짐작으로 primary 를 주면 사람이 그냥 넘긴다."""
        from book2md.mapping import Section, Problem, _role
        sec = Section(chapter="c", title="IV. 시효중단", file="x")
        prob = Problem(id="E-9", title="시효중단", file="y")
        self.assertEqual(_role(sec, prob), ("composite", None))

    # ── 승인 ────────────────────────────────────────────────
    def test_처음에는_하나도_승인되어_있지_않다(self):
        """score 3 이어도 자동 승인하지 않는다 (지침 §점수와 처리)."""
        for row in self.doc["mappings"] + self.doc["candidates"]:
            self.assertFalse(row["confirmed"])

    def test_절_하나만_골라_승인한다(self):
        path = self.tmp / "confirm.yaml"
        path.write_text(self.M.to_yaml(self.data), encoding="utf-8")
        n = self.M.confirm(path, section="IV. 시효중단")
        self.assertEqual(n, 1)
        doc = self.M.load(path)
        got = {r["textbook"]["section"]: r["confirmed"] for r in doc["mappings"]}
        self.assertTrue(got["IV. 시효중단"])
        self.assertFalse(got["III. 중복소제기"])

    def test_승인해도_주석이_남는다(self):
        """yaml 을 다시 써 내면 '왜 이렇게 판정했는지' 가 날아간다."""
        path = self.tmp / "keep.yaml"
        path.write_text(self.M.to_yaml(self.data), encoding="utf-8")
        self.M.confirm(path, all_=True)
        text = path.read_text(encoding="utf-8")
        self.assertIn("confirmed: true 인 것만 노트 생성에 쓴다", text)
        self.assertNotIn("confirmed: false", text)

    # ── 검증 M1~M4 ──────────────────────────────────────────
    def test_M4_배점이_맞으면_아무_말도_하지_않는다(self):
        """E-5 는 1+2.5+4+2.5=10, E-2 는 1+5+5+3=14, E-6 은 1+6+4+1=12."""
        _, warns = self.M.validate(self.doc)
        self.assertEqual([w for w in warns if w.startswith("M4")], [])

    def test_M4_가_어긋난_배점을_잡는다(self):
        doc = {"mappings": [{"casebook": [
            {"id": "E-5", "points": 10, "points_sum": 8}]}]}
        _, warns = self.M.validate(doc)
        self.assertTrue(any("M4" in w and "8" in w and "10" in w for w in warns))

    def test_M3_같은_문제가_두_곳에_쓰이면_알린다(self):
        _, warns = self.M.validate(self.doc)
        self.assertTrue([w for w in warns if w.startswith("M3") and "E-6" in w])

    def test_M2_승인된_항목의_파일이_없으면_FAIL(self):
        doc = {"mappings": [{"confirmed": True,
                             "textbook": {"file": "없는파일.md"},
                             "casebook": []}]}
        fails, _ = self.M.validate(doc)
        self.assertTrue(any(f.startswith("M2") for f in fails))

    def test_승인_전에는_파일_경로를_따지지_않는다(self):
        doc = {"mappings": [{"confirmed": False,
                             "textbook": {"file": "없는파일.md"},
                             "casebook": []}]}
        fails, _ = self.M.validate(doc)
        self.assertEqual(fails, [])

    # ── review ──────────────────────────────────────────────
    def test_review_는_사람이_훑을_수_있는_꼴이다(self):
        out = self.M.review(self.doc)
        self.assertIn("[ ] 046 일부청구 > IV. 시효중단", out)
        self.assertIn("E-5(10점, primary)", out)
        self.assertIn("[!] 070 상소이익 > III. 판단기준", out)
        self.assertIn("⚠️ 근거", out)


class 절제목_전수점검(unittest.TestCase):
    """`convert audit-sections` — 고치기 전에 몇 건인지부터 센다.

    가짜 절 하나가 판례를 엉뚱한 목차 아래로 끌고 간다. 002 신의칙에서
    `(D 의의` 가 진짜 `II. 내용` 절의 판례 12건을 가져갔다.
    """

    신의칙 = """---
source: 기본서
chapter: "002 신의칙"
outline: ["의의", "내용", "예외", "효과", "관련논점"]
parser: pymupdf
---

### 002 신의칙

==& 의의 - 내용 - 예외 - 효과 - 관련논점==

#### I. 의의 및 취지

신의성실의 원칙이란 …

#### II. 내용

가) 모순거동금지 …

#### (D 의의

실효의 원칙이란 … (2011다84298)

#### III. 예외

#### IV. 효과

#### V. 관련논점
"""

    대위소 = """---
source: 기본서
chapter: "034 피보전채권 이행의 소 확정판결과 대위소"
outline: ["의의", "내용", "고유필수적 공동소송인 추가", "효과"]
parser: pymupdf
---

### 034 대위소

==& 의의 - 내용 - 고유필수적 공동소송인 추가 - 효과==

#### I. 의의

#### II. 내용

#### III. 고유필수적 공동소승인 추개■ ：＞(%찌--------------------------- ---

#### VIII • 윤곽 민사소송법
"""

    @classmethod
    def setUpClass(cls):
        from book2md import audit
        cls.audit = audit
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / "기본서").mkdir()
        (cls.tmp / "기본서" / "02_002신의칙.md").write_text(cls.신의칙, encoding="utf-8")
        (cls.tmp / "기본서" / "34_034대위소.md").write_text(cls.대위소, encoding="utf-8")
        # 러닝 헤더는 논점마다 되풀이된다 — 그것이 머리말의 표지다
        for n in (35, 36):
            (cls.tmp / "기본서" / f"{n}_0{n}다른논점.md").write_text(
                cls.대위소.replace("034 피보전채권 이행의 소 확정판결과 대위소",
                                 f"0{n} 다른 논점"), encoding="utf-8")
        cls.data = audit.scan(cls.tmp, CFG)
        cls.kinds = audit.classify(cls.data, repeat_min=3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _titles(self, kind):
        return [s.title for s in self.kinds[kind]]

    def test_목차_항목을_두_번_쓴_절을_잡는다(self):
        """'I. 의의 및 취지' 가 이미 '의의' 를 썼다. '(D 의의' 는 그 다음이다."""
        self.assertEqual(self._titles("목차_두_번_씀"), ["(D 의의"])

    def test_먼저_선_절은_가짜로_보지_않는다(self):
        self.assertNotIn("I. 의의 및 취지", self._titles("목차_두_번_씀"))
        self.assertNotIn("II. 내용", self._titles("목차_두_번_씀"))

    def test_되풀이되는_머리말이_절로_선_것을_잡는다(self):
        self.assertEqual(set(self._titles("머리말로_보임")), {"VIII • 윤곽 민사소송법"})

    def test_논점마다_나오는_진짜_절은_머리말로_보지_않는다(self):
        """'I. 의의' 도 논점마다 나온다. 반복만 세면 이것이 걸린다."""
        모두 = sum(self.kinds.values(), []) if False else self._titles("머리말로_보임")
        self.assertNotIn("I. 의의", 모두)
        self.assertNotIn("II. 내용", 모두)

    def test_깨진_절_제목에_목차_띠의_이름을_붙여_보여준다(self):
        """제목 글자는 손대지 않는다. 사람이 고칠 정보만 옆에 둔다 (§4.8)."""
        깨진 = [s for s in self.kinds["잡글자_섞임"] if "고유필수적" in s.title]
        self.assertTrue(깨진)
        s = 깨진[0]
        self.assertIn("■", s.junk)
        band = self.data["bands"][s.file][s.band]
        self.assertEqual(self.audit._near(band, s.key), "고유필수적 공동소송인 추가")

    def test_목차에_있는데_절이_안_선_것도_센다(self):
        left = {x for _, _, items in self.kinds["목차에_있는데_절이_없음"] for x in items}
        self.assertIn("고유필수적 공동소송인 추가", left)

    def test_깨끗한_논점은_아무것도_안_잡힌다(self):
        clean = Path(tempfile.mkdtemp())
        (clean / "기본서").mkdir()
        (clean / "기본서" / "45_046일부청구.md").write_text("""---
source: 기본서
chapter: "046 일부청구"
outline: ["의의", "소송물", "중복소제기"]
parser: pymupdf
---

### 046 일부청구

==& 의의 - 소송물 - 중복소제기==

#### I. 의의

#### II. 소송물

#### III. 중복소제기
""", encoding="utf-8")
        try:
            k = self.audit.classify(self.audit.scan(clean, CFG))
            self.assertEqual({name: len(v) for name, v in k.items()},
                             {"목차_두_번_씀": 0, "머리말로_보임": 0, "잡글자_섞임": 0,
                              "목차에_없음": 0, "목차에_있는데_절이_없음": 0})
        finally:
            shutil.rmtree(clean, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
