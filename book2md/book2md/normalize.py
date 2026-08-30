"""정규화 (§4).

원칙 하나만 지킨다. **뜻을 바꾸는 손질은 하지 않는다.**
맞춤법 교정·문장 재구성·판시 문언 수정·한자 한글화는 어떤 경우에도 없다(§4.3).
여기서 하는 일은 OCR·추출이 망가뜨린 글자 모양을 되돌리는 것뿐이고,
되돌린 자리는 전부 기록에 남는다.

특히 괄호는 문서 전체에 일괄 치환하지 않는다. `[` 를 무조건 `(` 로 바꾸면
두문자 `[확객시전]` 이 통째로 깨진다. 그래서 사건번호에 실제로 붙은 괄호만
골라 고친다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .model import Page
from .patterns import Patterns

#: 줄 맨 앞의 로마자 절 번호. 앞에 강조 표시가 붙어 있을 수 있다.
#: 뒤에는 '.'(또는 공백)과 한글 제목이 와야 한다.
_ROMAN_HEAD = re.compile(
    r"^(?:[=*]{2})?\s*(?P<num>[IVXlN|Ⅰ-Ⅹ¡ν씨０-９0-9]{1,5})"
    r"(?:\s*[.,·]\s*|\s+)(?=[가-힣])")

#: 제N죄/제N좌 → 제N조 (조문번호 안에서만)
_ARTICLE_OCR = re.compile(r"제\s*(\d+)\s*[죄좌](?![가-힣])")

#: 'III.중복소제기' 처럼 번호 뒤 공백을 OCR 이 삼킨 것. 종이에는 있다.
#: 줄 맨 앞 + 번호 + 구분점 + 한글일 때만 넣는다.
_HEAD_SPACE = re.compile(
    r"^((?:[=*]{2})?\s*(?:[IVX]{1,5}|\d{1,2})\s*[.)])(?=[가-힣])")

#: '1 .문제점' 처럼 번호와 마침표 사이가 벌어진 것. 줄 앞에서만 고친다.
_ITEM_SPACE = re.compile(r"^(\s*(?:[=*]{2})?\s*[0-9IVXivx]{1,4})\s+([.)])")

_FULLWIDTH = {c: chr(ord(c) - 0xFEE0) for c in
              [chr(x) for x in range(0xFF01, 0xFF5F)]}
_FULLWIDTH["　"] = " "
_FULLWIDTH_ALNUM = {k: v for k, v in _FULLWIDTH.items() if v.isalnum()}


@dataclass
class Change:
    page: int
    kind: str          # bracket | space | article | date | noise | star | mnemonic
    before: str
    after: str
    context: str = ""


class Normalizer:
    def __init__(self, cfg: dict, pat: Patterns):
        self.cfg = cfg
        self.pat = pat
        n = cfg["normalize"]
        self.opens = set(n["open_brackets"])
        self.closes = set(n["close_brackets"])
        self.fullwidth_brackets = bool(n.get("fullwidth_brackets", True))
        self.fullwidth_alnum = bool(n.get("fullwidth_alnum", True))
        self.fullwidth_parens = bool(n.get("fullwidth_parens", True))
        self.mnemonic_pairs = [tuple(p) for p in n.get("mnemonic_brackets", [])]
        self.repair_unclosed = bool(
            cfg["preserve"]["mnemonic"].get("repair_unclosed", True))
        self.noise_chars = sorted(n.get("noise_chars", []), key=len, reverse=True)
        self.noise_tokens = set(n.get("noise_tokens", []))
        self.collapse = bool(n.get("collapse_spaces", True))
        self.fix_dates = bool(n.get("fix_dates", True))
        self.item_space = bool(n.get("item_number_space", True))
        self.head_space = bool(n.get("heading_number_space", True))
        self.roman = _roman_table(n.get("roman_heads", {}))
        self.article_ocr = bool(n.get("article_ocr", True))
        self.title_brackets = bool(n.get("repair_title_brackets", True))
        self.close_alt = "".join(c for c in self.closes if c not in "])}")
        self.case_sep = _case_sep_rx(cfg, n.get("case_inner_seps", []))
        self.date_hangul = n.get("date_trailing_hangul", "warn")
        self.stars = "".join(cfg["preserve"]["star"]["chars"])
        self.allowed = _allowed_set(cfg.get("noise_scan", {}))
        self.corrections = [
            (c["find"], c.get("to", ""), c.get("note", ""))
            for c in (cfg.get("corrections") or []) if c.get("find")
        ]

    # ── 페이지 단위 ──────────────────────────────────────────────
    def normalize_page(self, page: Page) -> list[Change]:
        changes: list[Change] = []
        for line in page.lines:
            before = line.text
            line.text = self.normalize_line(line.text, page.number, changes)
            if before.strip() and not line.text.strip():
                # 노이즈만으로 이루어진 줄이었다. 통째로 사라지므로 남긴다 (§P2-1)
                changes.append(Change(page.number, "drop", before.strip(), "",
                                      "정규화 뒤 빈 줄이 되어 버렸다"))
        page.lines = [l for l in page.lines if l.text.strip()]
        return changes

    def normalize_line(self, text: str, page_no: int, changes: list[Change]) -> str:
        text = unicodedata.normalize("NFC", text)

        if self.fullwidth_alnum:
            text = text.translate(str.maketrans(_FULLWIDTH_ALNUM))
            text = text.replace("　", " ")
        if self.fullwidth_brackets:
            text = text.replace("［", "[").replace("］", "]")
        if self.fullwidth_parens:
            text = text.replace("（", "(").replace("）", ")")

        text = self._corrections(text, page_no, changes)
        text = self._mnemonic_brackets(text, page_no, changes)
        text = self._title_brackets(text, page_no, changes)
        text = self._noise(text, page_no, changes)
        text = self._case_seps(text, page_no, changes)
        text = self._cases(text, page_no, changes)
        text = self._roman_head(text, page_no, changes)
        text = self._articles(text)
        if self.article_ocr:
            text = _ARTICLE_OCR.sub(lambda m: f"제{m.group(1)}조", text)
        if self.item_space:
            text = _ITEM_SPACE.sub(r"\1\2", text)
        if self.head_space:
            fixed = _HEAD_SPACE.sub(r"\1 ", text)
            if fixed != text:
                changes.append(Change(page_no, "space", text, fixed,
                                      "번호 뒤 공백 복원"))
                text = fixed
        if self.fix_dates:
            text = self._dates(text, page_no, changes)
        if self.collapse:
            text = re.sub(r"[ \t ]+", " ", text).strip()

        return text

    # ── 사람이 확정한 정정 ───────────────────────────────────────
    def _corrections(self, text: str, page_no: int, changes: list[Change]) -> str:
        """config.yaml 의 corrections 만 적용한다. 스스로 고치지 않는다.

        OCR 이 글자를 삼켜 버려 프로그램이 되살릴 수 없는 것들이 있다.
        무엇으로 되돌릴지는 원문을 본 사람만 안다.
        """
        for find, to, note in self.corrections:
            idx = text.find(find)
            while idx >= 0:
                changes.append(Change(page_no, "correction", find, to,
                                      _ctx(text, idx, idx + len(find)) +
                                      (f"  ({note})" if note else "")))
                text = text[:idx] + to + text[idx + len(find):]
                idx = text.find(find, idx + len(to))
        return text

    # ── 두문자 대괄호 복구 (§2.2) ─────────────────────────────────
    def _mnemonic_brackets(self, text: str, page_no: int, changes: list[Change]) -> str:
        """괄호만 되돌린다. 안쪽 글자는 손대지 않는다.

        OCR 은 여는 괄호와 닫는 괄호를 서로 다른 글자로 흘린다(`［…】`, `【…］`,
        `｛…】`). 짝이 안 맞아도 안쪽이 두문자 모양이면 대괄호로 되돌린다.
        닫는 괄호를 통째로 흘린 경우(`(1) 원칙 ［일나시 나소시`)도 되살린다.
        되살린 자리는 모두 기록에 남겨 사람이 확인할 수 있게 한다.
        """
        def repl(m: re.Match) -> str:
            body = m.group("body")
            mid = m.groupdict().get("mid") or ""
            if m.group("open") == "[" and m.group("close") == "]" and not mid:
                return m.group(0)
            if not self.pat.is_mnemonic_body(body):
                return m.group(0)
            fixed = f"[{body}]{mid}"
            changes.append(Change(page_no, "mnemonic", m.group(0), fixed,
                                  _ctx(text, m.start(), m.end())))
            return fixed

        text = self.pat.mnemonic_like.sub(repl, text)
        if self.repair_unclosed:
            m = self.pat.mnemonic_unclosed.search(text)
            if m and self.pat.is_mnemonic_body(m.group("body")):
                tail = m.group("tail") or ""
                fixed = text[:m.start()] + f"[{m.group('body')}]" + tail
                changes.append(Change(page_no, "mnemonic", m.group(0),
                                      f"[{m.group('body')}]" + tail,
                                      _ctx(text, m.start(), m.end())))
                text = fixed
        return text

    # ── 제목·각주의 대괄호 오인식 (§P2-2) ─────────────────────────
    def _title_brackets(self, text: str, page_no: int, changes: list[Change]) -> str:
        """두문자가 아닌 긴 제목의 대괄호를 되돌린다.

        'E-2. 」명시적 일부청구 중복소제기]' 는 여는 대괄호가 닫는 괄호 글자로
        흘러나온 것이다. 안쪽이 두문자가 아니라 두문자 복구가 못 잡는다.
        **한 줄 안에서 짝이 맞아떨어질 때만** 고친다 — 짝이 안 맞으면 무엇을
        고쳐야 할지 알 수 없고, 찍어서 고치면 원문이 훼손된다.
        """
        if not self.title_brackets or not self.close_alt:
            return text
        alt = self.close_alt

        # ① '[' 로 열고 이상한 글자로 닫은 것 → ']' 로
        opened = text.find("[")
        if opened >= 0 and "]" not in text[opened:]:
            for j in range(opened + 1, len(text)):
                if text[j] in alt:
                    fixed = text[:j] + "]" + text[j + 1:]
                    changes.append(Change(page_no, "bracket", text[j], "]",
                                          _ctx(text, j, j + 1)))
                    return fixed

        # ② 닫는 글자로 열고 ']' 로 닫은 것 → '[' 로
        closed = text.find("]")
        if closed > 0 and "[" not in text[:closed]:
            for j in range(closed):
                if text[j] in alt and j + 1 < len(text) and text[j + 1] not in " \t":
                    fixed = text[:j] + "[" + text[j + 1:]
                    changes.append(Change(page_no, "bracket", text[j], "[",
                                          _ctx(text, j, j + 1)))
                    return fixed
        return text

    # ── 사건번호 둘레 정리 (§2.1) ─────────────────────────────────
    def _case_seps(self, text: str, page_no: int, changes: list[Change]) -> str:
        """사건번호 안에 낀 콜론 따위를 지운다 (§P1-1).

        '96다:30113' 은 사건번호 정규식이 통째로 빗나간다. 부호와 일련번호
        사이에서만 지우므로 '판시: 30113' 같은 본문은 건드리지 않는다.
        """
        if not self.case_sep:
            return text

        def sub(m: re.Match) -> str:
            fixed = m.group("head") + m.group("serial")
            changes.append(Change(page_no, "case_sep", m.group(0), fixed,
                                  _ctx(text, m.start(), m.end())))
            return fixed

        return self.case_sep.sub(sub, text)

    def _cases(self, text: str, page_no: int, changes: list[Change]) -> str:
        """사건번호를 하나씩 훑으며 앞뒤 괄호·내부 공백·별표를 바로잡는다."""
        out, cursor = [], 0
        for m in self.pat.case_loose.finditer(text):
            out.append(text[cursor:m.start()])
            raw = m.group(0)
            fixed = f"{m.group('year')}{m.group('suffix')}{m.group('serial')}"
            if fixed != raw:
                changes.append(Change(page_no, "space", raw, fixed,
                                      _ctx(text, m.start(), m.end())))
            # 앞 괄호
            if out and out[-1]:
                prev = out[-1]
                j = len(prev) - 1
                while j >= 0 and prev[j] == " ":
                    j -= 1
                if j >= 0 and prev[j] in self.opens and prev[j] != "(":
                    changes.append(Change(page_no, "bracket", prev[j] + raw,
                                          "(" + fixed, _ctx(text, m.start(), m.end())))
                    out[-1] = prev[:j] + "(" + prev[j + 1:]
            out.append(fixed)
            cursor = m.end()

            # 별표: 사건번호 뒤 공백을 없애고 ASCII '*' 로 통일한다 (§2.3)
            tail = text[cursor:]
            sm = re.match(rf"(\s*)([{re.escape(self.stars)}])", tail)
            if sm:
                if sm.group(0) != "*":
                    changes.append(Change(page_no, "star", fixed + sm.group(0),
                                          fixed + "*", _ctx(text, m.start(), m.end())))
                out.append("*")
                cursor += sm.end()
                tail = text[cursor:]
            # 뒤 괄호
            cm = re.match(r"\s*(.)", tail)
            if cm and cm.group(1) in self.closes and cm.group(1) != ")":
                changes.append(Change(page_no, "bracket", fixed + cm.group(0),
                                      fixed + ")", _ctx(text, m.start(), m.end())))
                out.append(")")
                cursor += cm.end()
        out.append(text[cursor:])
        return "".join(out)

    # ── 로마자 절 번호 되살리기 (§P0-1) ──────────────────────────
    def _roman_head(self, text: str, page_no: int, changes: list[Change]) -> str:
        """줄 맨 앞의 로마자가 소문자 L 로 흘러나온 것을 되돌린다.

        'Ill. 중복소제기' 가 헤딩으로 안 잡히면 그 절 전체가 목차에서 사라진다.
        **줄 맨 앞 + 뒤에 '.' 또는 공백 + 한글 제목**일 때만 고친다. 문장 속
        'l' 을 건드리면 본문이 망가진다.
        """
        if not self.roman:
            return text
        m = _ROMAN_HEAD.match(text)
        if not m:
            return text
        raw = m.group("num")
        fixed = self.roman.get(raw)
        if not fixed or fixed == raw:
            return text
        out = text[:m.start("num")] + fixed + text[m.end("num"):]
        changes.append(Change(page_no, "roman", raw, fixed, _ctx(text, m.start("num"),
                                                                m.end("num"))))
        return out

    # ── 조문 공백 (§4.1) ─────────────────────────────────────────
    def _articles(self, text: str) -> str:
        return self.pat.article.sub(lambda m: f"제{m.group('num')}{m.group('unit')}", text)

    # ── 날짜 (§4.2) ──────────────────────────────────────────────
    def _dates(self, text: str, page_no: int, changes: list[Change]) -> str:
        out, cursor = [], 0
        for m in self.pat.date.finditer(text):
            out.append(text[cursor:m.start()])
            canon = f"{m.group('y')}. {int(m.group('m'))}. {int(m.group('d'))}."
            cursor = m.end()
            tail = text[cursor:]
            junk = ""
            while tail:
                ch = tail[0]
                if ch in self.noise_tokens or ch in "]°｣¤" or (
                        not ch.isspace() and ch not in self.allowed):
                    junk += ch
                    tail = tail[1:]
                    cursor += 1
                    continue
                break
            hangul_tail = ""
            if not m.group(0).rstrip().endswith(".") and tail[:1] and "가" <= tail[0] <= "힣":
                k = 0
                while k < len(tail) and "가" <= tail[k] <= "힣":
                    k += 1
                hangul_tail = tail[:k]
                if self.date_hangul == "strip":
                    cursor += k
            if junk or hangul_tail:
                # 기록에는 날짜와 바로 뒤 몇 글자만 남긴다. 뒤 문장을 통째로
                # 물고 오면 사람이 무엇이 바뀐 건지 못 알아본다.
                tail_shown = hangul_tail[:4]
                changes.append(Change(
                    page_no, "date", m.group(0) + junk + tail_shown,
                    canon if (self.date_hangul == "strip" or not hangul_tail)
                    else canon + tail_shown,
                    _ctx(text, m.start(), m.end())))
            elif canon != m.group(0):
                changes.append(Change(page_no, "date", m.group(0), canon,
                                      _ctx(text, m.start(), m.end())))
            out.append(canon)
        out.append(text[cursor:])
        return "".join(out)

    # ── 노이즈 (§4.1) ────────────────────────────────────────────
    def _noise(self, text: str, page_no: int, changes: list[Change]) -> str:
        for token in self.noise_chars:
            if token and token in text:
                idx = text.find(token)
                changes.append(Change(page_no, "noise", token, "",
                                      _ctx(text, idx, idx + len(token))))
                text = text.replace(token, "")
        for token in self.noise_tokens:
            pat = re.compile(rf"(?<=\s){re.escape(token)}(?=\s)")
            if pat.search(text):
                m = pat.search(text)
                changes.append(Change(page_no, "noise", token, "",
                                      _ctx(text, m.start(), m.end())))
                text = pat.sub("", text)
        return text

    # ── 잔여 노이즈 세기 (§5.6) ───────────────────────────────────
    def residual_noise(self, text: str) -> list[str]:
        """정규화하고도 남은, 법서에 나올 리 없는 글자들."""
        return [ch for ch in text if not ch.isspace() and ch not in self.allowed]


def _allowed_set(scan: dict) -> set:
    allowed = set(scan.get("allowed_chars", ""))
    for lo, hi in scan.get("allowed_ranges", []):
        for cp in range(int(lo), int(hi) + 1):
            allowed.add(chr(cp))
    return allowed


def _ctx(text: str, start: int, end: int, width: int = 30) -> str:
    """앞뒤 30자를 함께 보여 준다. 사람이 눈으로 확인할 수 있게(§5.1)."""
    left = text[max(0, start - width):start]
    right = text[end:end + width]
    return f"…{left}〖{text[start:end]}〗{right}…"


def _case_sep_rx(cfg: dict, seps) -> "re.Pattern | None":
    """연도+부호 뒤, 일련번호 앞에 낀 구분자만 잡는 정규식."""
    seps = [s for s in (seps or []) if s]
    if not seps:
        return None
    suffixes = sorted(cfg["preserve"]["case_suffixes"], key=len, reverse=True)
    alt = "|".join(re.escape(s) for s in suffixes)
    cls = "[" + re.escape("".join(seps)) + "]"
    return re.compile(
        rf"(?<![0-9A-Za-z])(?P<head>\d{{2,4}}[ \t]*(?:{alt}))[ \t]*{cls}[ \t]*"
        rf"(?P<serial>\d+)(?![0-9])")


def _roman_table(spec: dict) -> dict:
    """{오인식 글자: 바른 로마자} 표를 만든다."""
    table = {}
    for good, bad_list in (spec or {}).items():
        table[str(good)] = str(good)
        for bad in bad_list or []:
            table[str(bad)] = str(good)
    return table
