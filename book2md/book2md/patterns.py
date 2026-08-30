"""정규식 모음. 전부 config.yaml 값으로 만든다.

여기에 있는 네 가지가 §2 의 절대 보존 대상이다. 정규식을 고칠 일이 생기면
config.yaml 을 먼저 보고, 그래도 안 되면 여기를 고친 뒤 tests 를 돌린다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def _alt(items) -> str:
    """긴 것부터 맞추도록 정렬해 대안 패턴을 만든다 (재다 가 다 보다 먼저)."""
    return "|".join(re.escape(s) for s in sorted(items, key=len, reverse=True))


@dataclass
class Patterns:
    case: re.Pattern              # 사건번호
    case_loose: re.Pattern        # 공백이 낀 사건번호까지 (정규화 전 원문용)
    case_star: re.Pattern         # 사건번호 + 별표
    case_star_loose: re.Pattern   # 공백이 낀 것까지 (정규화 전 원문 대조용)
    mnemonic: re.Pattern          # 두문자 [일나시 나소시]
    mnemonic_like: re.Pattern     # 괄호 종류를 가리지 않는 두문자 모양
    date: re.Pattern              # 2011. 4. 26.
    article: re.Pattern           # 제 265 조
    footnote_ref: re.Pattern      # [^264]
    footnote_def: re.Pattern      # [^264]: 내용
    footnote_raw: re.Pattern      # 각주 영역의 '264 내용' / '264) 내용'
    star_chars: str
    known_suffixes: frozenset
    year_min: int
    year_max: int
    deny_words: tuple
    mnemonic_max_len: int
    label_at_line_start: bool
    mnemonic_unclosed: re.Pattern

    @classmethod
    def build(cls, cfg: dict) -> "Patterns":
        pre = cfg["preserve"]
        nrm = cfg["normalize"]
        suffixes = _alt(pre["case_suffixes"])
        stars = "".join(pre["star"]["chars"])
        star_cls = "[" + re.escape(stars) + "]"
        gap = int(pre["star"]["max_gap"])

        # 사건번호: 연도(2~4자리) + 부호 + 일련번호.
        # 앞뒤에 숫자·한글이 붙으면 사건번호가 아니다(제2019조, 2019다음 등).
        # 통화·수량 표기가 사건번호로 오인되는 것을 막는다.
        # '1,000만 원' 이 '1,000므1 원' 으로 흘러나오면 '000므1' 이 잡힌다.
        case = re.compile(
            rf"(?<![0-9A-Za-z,])(?P<year>\d{{2,4}})(?P<suffix>{suffixes})(?P<serial>\d+)"
            rf"(?![0-9])(?!호선|번지)(?!\s*(?:원|만|억|천|백|명|개|건|쪽|년|월|일)\b)"
            rf"(?!\s*원)"
        )
        # 원문에는 '91 다 43695' 처럼 공백이 낀다. 정규화가 이걸 붙인다.
        case_loose = re.compile(
            rf"(?<![0-9A-Za-z,])(?P<year>\d{{2,4}})\s*(?P<suffix>{suffixes})\s*(?P<serial>\d+)"
            rf"(?![0-9])(?!\s*원)"
        )
        # 별표 하나만 센다. 마크다운 굵게(`**`)가 사건번호 뒤에 오면
        # `91다43695**` 가 되어 별표로 오해된다. 원본에는 `**` 가 없으므로
        # 변환본 쪽만 부풀어 개수 대조가 통째로 어긋난다.
        case_star = re.compile(
            rf"(?<![0-9A-Za-z])\d{{2,4}}(?:{suffixes})\d+(?![0-9])\s{{0,{gap}}}"
            rf"(?<!\*){star_cls}(?!\*)"
        )

        # 원본(정규화 전)에는 '91 다43176*' 처럼 공백이 낀다. 엄격한 패턴으로
        # 원본을 세면 그만큼 적게 잡혀, 변환본이 늘어난 것처럼 보인다.
        case_star_loose = re.compile(
            rf"(?<![0-9A-Za-z,])\d{{2,4}}\s*(?:{suffixes})\s*\d+(?![0-9])"
            rf"\s{{0,{gap}}}(?<!\*){star_cls}(?!\*)"
        )

        mn = pre["mnemonic"]
        # 두문자 안에는 숫자가 섞이기도 한다([송완불2괴]). 다만 숫자만인 덩어리는
        # 두문자가 아니므로 한글이 한 자 이상 있어야 한다.
        tok = (rf"(?=[가-힣0-9]{{{mn['token_min']},{mn['token_max']}}})"
               rf"[가-힣0-9]*[가-힣][가-힣0-9]*")
        inner = rf"{tok}(?:\s{tok}){{0,{max(0, mn['max_tokens'] - 1)}}}"
        # [^264] 는 '^' 때문에 걸리지 않는다. [텍스트](주소) 는 뒤의 '(' 로 걸러낸다.
        # 전각 대괄호도 함께 받는다. 정규화 전 원문(진단·probe)에도 쓰이기 때문이다.
        mnemonic = re.compile(rf"[\[［](?P<body>{inner})[\]］](?![(:])")
        # OCR 은 여는 괄호와 닫는 괄호를 서로 다른 글자로 흘린다: ［…】, 【…］, ｛…】.
        # 그래서 짝을 맞추지 않고, 안쪽이 두문자 모양이면 받아들인다.
        opens = "".join(a for a, _ in nrm["mnemonic_brackets"]) + "[［"
        closes = "".join(b for _, b in nrm["mnemonic_brackets"]) + "]］"
        # 강조 표시가 두문자와 닫는 괄호 사이에 끼기도 한다: `[일외별명일==】`.
        # 색을 먼저 입히고 정규화가 나중에 돌기 때문이다. 표시는 살려 뒤로 옮긴다.
        mnemonic_like = re.compile(
            rf"(?P<open>[{re.escape(opens)}])(?P<body>{inner})"
            rf"(?P<mid>(?:==|\*\*)?)(?P<close>[{re.escape(closes)}])(?![(:])"
        )
        # 닫는 괄호를 통째로 흘린 경우: `(1) 원칙 ［일나시 나소시`(줄 끝).
        # 줄 끝에 강조 마크업(==, **)이 붙어 있을 수 있다. 파서가 색을 먼저
        # 입히고 그다음에 정규화가 돌기 때문이다.
        mnemonic_unclosed = re.compile(
            rf"(?P<open>[{re.escape(opens)}])(?P<body>{inner})\s*(?P<tail>(?:==|\*\*)?)\s*$"
        )

        date = re.compile(r"(?<!\d)(?P<y>\d{4})\.\s*(?P<m>\d{1,2})\.\s*(?P<d>\d{1,2})\.?")
        units = _alt(nrm["article_units"])
        article = re.compile(rf"제\s+(?P<num>\d+)\s*(?P<unit>{units})(?![가-힣])")

        fn = pre["footnote"]
        lo, hi = fn["number_min"], fn["number_max"]
        footnote_ref = re.compile(r"\[\^(?P<n>\d{1,4})\]")
        footnote_def = re.compile(r"^\[\^(?P<n>\d{1,4})\]:\s?(?P<body>.*)$")
        footnote_raw = re.compile(r"^(?P<n>\d{1,4})\s*[).\]]?\s+(?P<body>\S.*)$")

        return cls(
            case=case, case_loose=case_loose, case_star=case_star,
            case_star_loose=case_star_loose,
            mnemonic=mnemonic, mnemonic_like=mnemonic_like,
            date=date, article=article,
            footnote_ref=footnote_ref, footnote_def=footnote_def,
            footnote_raw=footnote_raw,
            star_chars=stars,
            known_suffixes=frozenset(pre["known_suffixes"]),
            year_min=int(pre["year_min"]), year_max=int(pre["year_max"]),
            deny_words=tuple(mn["deny_words"]),
            mnemonic_max_len=int(mn.get("max_total_len", 10)),
            label_at_line_start=bool(mn.get("label_at_line_start", True)),
            mnemonic_unclosed=mnemonic_unclosed,
        )

    # ── 두문자 판정 ──────────────────────────────────────────────
    def is_mnemonic_body(self, body: str) -> bool:
        """대괄호 안이 ② 두문자인지.

        ③ 판례 제목 라벨(`[청구확장 취지 명백히 표시]`)과 생김새가 같아서
        길이로 가른다. 라벨은 legend.case_label 이 따로 뽑으므로 여기서
        빼도 잃는 것이 없다. 경계값은 config.yaml 에서 조정한다.
        """
        if not body or not body.strip():
            return False
        if len(body) > self.mnemonic_max_len:
            return False
        return not any(w in body for w in self.deny_words)

    def mnemonic_spans(self, text: str) -> list[tuple[int, int, str]]:
        """두문자의 (시작, 끝, 안쪽글자). 줄 단위 자리를 함께 본다.

        ③ 판례 제목 라벨은 줄 맨 앞(목록 번호 뒤 포함)에 온다
        (`1) [청구확장 취지 명백히 표시]`). ② 두문자는 문장 가운데 온다
        (`(1) 원칙 [일나시 나소시]`). 길이만으로는 `[반복적 재심청구]` 같은
        8자짜리 라벨을 못 가르므로 자리를 함께 본다.
        """
        out = []
        offset = 0
        for line in text.split("\n"):
            for m in self.mnemonic.finditer(line):
                body = m.group("body")
                if not self.is_mnemonic_body(body):
                    continue
                if self.label_at_line_start and _looks_like_label(line, m.start(), m.end()):
                    continue
                out.append((offset + m.start(), offset + m.end(), body))
            offset += len(line) + 1
        return out

    def find_mnemonics(self, text: str) -> list[str]:
        return [body for _, _, body in self.mnemonic_spans(text)]

    # ── 사건번호 판정 (§5.1) ─────────────────────────────────────
    def find_cases(self, text: str) -> list[re.Match]:
        return list(self.case.finditer(text))

    def case_problems(self, m: re.Match) -> list[str]:
        """사건번호 하나를 검사해 위반 사유를 돌려준다. 빈 목록이면 정상."""
        bad = []
        year, suffix, serial = m.group("year"), m.group("suffix"), m.group("serial")
        if len(year) not in (2, 4):
            bad.append(f"연도 자릿수가 {len(year)}자리")
        if len(year) == 4 and not (self.year_min <= int(year) <= self.year_max):
            bad.append(f"연도 {year} 가 범위 밖")
        if suffix not in self.known_suffixes:
            bad.append(f"알 수 없는 부호 '{suffix}'")
        if not serial.isdigit() or serial.startswith("0"):
            bad.append(f"일련번호 '{serial}' 이 이상")
        return bad


_LIST_LEAD = re.compile(
    r"^\s*(?:[-•‣▪·]|\(?\s*\d{1,2}\s*[).]|[가-하]\s*[.)]|[①-⑳]|[ⅰ-ⅹIVXi]{1,4}\s*[).])?\s*$"
)


def _looks_like_label(line: str, start: int, end: int) -> bool:
    """③ 판례 제목 라벨인가.

    라벨은 줄 맨 앞에 서고, 목록 번호를 달거나 뒤에 설명이 이어진다.
        1) [청구확장 취지 명백히 표시] 확장의 뜻을 밝힌 때…
    두문자는 문장 가운데 오거나, 줄에 홀로 선다.
        (1) 원칙 [일나시 나소시] 로 본다.
        [확객시전]
    그래서 '맨 앞'만으로는 가르지 않고, 번호가 붙었는지·뒤에 말이 이어지는지를
    함께 본다.
    """
    head = line[:start]
    if not _LIST_LEAD.match(head):
        return False                      # 문장 가운데 = 두문자
    has_marker = bool(head.strip())
    has_tail = bool(line[end:].strip())
    return has_marker or has_tail
