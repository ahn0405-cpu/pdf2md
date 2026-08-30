"""두 소스 교차 검증 (§5.3, §5.5).

기본서와 사례집에 같은 두문자가 나온다. 한쪽이 깨져 있으면 여기서 드러난다.
실측 사례: 기본서 `[확객시전]` vs 사례집 `[확객시젠]` — 한 글자 차이다.

**어느 쪽이 옳은지 판정하지 않는다.** 양쪽 원문을 나란히 놓고 사람이 정한다(§2.2).
그래서 '거의 같은데 다른' 짝을 찾아 내는 것이 이 모듈의 핵심이다. 교집합만
보면 한 글자가 다른 순간 서로 다른 항목이 되어 조용히 지나가 버린다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from .patterns import Patterns
from .validate import md_files

_SIDE = re.compile(r"s[A-Z]-(\d{1,4})")
_PROBLEM = re.compile(r"^#{1,3}\s+([A-Z])-(\d+)\.", re.M)


def _collect(root: Path, pat: Patterns):
    counts: Counter = Counter()
    context: dict[str, list[str]] = {}
    sides: Counter = Counter()
    problems: set[str] = set()
    for path in md_files(root):
        text = path.read_text(encoding="utf-8")
        # mnemonic_spans 를 쓴다. 정규식만 돌리면 ③ 판례 제목 라벨('[일반]',
        # '[소권남용]', '[원칙]')이 두문자로 섞여 결정표가 못 쓰게 된다.
        for start, end, body in pat.mnemonic_spans(text):
            counts[body] += 1
            context.setdefault(body, []).append(
                f"{path.name}: …{text[max(0, start - 28):end + 28]}…"
                .replace("\n", "⏎"))
        for m in _SIDE.finditer(text):
            sides[m.group(0)] += 1
        for m in _PROBLEM.finditer(text):
            problems.add(f"{m.group(1)}-{m.group(2)}")
    return counts, context, sides, problems


def _work_dir(md_root: Path) -> Path | None:
    """이 결과물을 만든 중간 폴더. 쪽번호를 여기서 얻는다 (§P1-3).

    `run` 은 출력 폴더 이름(프로파일 이름)과 중간 폴더 이름(PDF 파일 이름)이
    다르다. 이름이 안 맞으면 baseline 의 원본 이름으로 찾는다.
    """
    base = md_root.parent / "_work"
    if not base.is_dir():
        return None
    direct = base / md_root.name
    if (direct / "03_blocks.jsonl").exists():
        return direct
    for cand in sorted(base.iterdir()):
        meta = cand / "baseline.json"
        if not (cand / "03_blocks.jsonl").exists() or not meta.exists():
            continue
        try:
            src = json.loads(meta.read_text(encoding="utf-8")).get("source", "")
        except Exception:
            continue
        if Path(src).stem == md_root.name or md_root.name in Path(src).stem:
            return cand
    return None


def _pages_of(md_root: Path, pat: Patterns) -> tuple[dict[str, list[int]], str | None]:
    """두문자마다 원본 쪽번호. (없으면 빈 표) + 원본 PDF 경로."""
    work = _work_dir(md_root)
    if work is None:
        return {}, None
    src = None
    meta = work / "baseline.json"
    if meta.exists():
        try:
            src = json.loads(meta.read_text(encoding="utf-8")).get("source_path")
        except Exception:
            src = None
    out: dict[str, list[int]] = {}
    blocks = work / "03_blocks.jsonl"
    if not blocks.exists():
        return out, src
    with open(blocks, encoding="utf-8") as fh:
        for row in fh:
            if not row.strip():
                continue
            b = json.loads(row)
            page = int(b.get("page") or 0)
            for body in b.get("mnemonics") or []:
                if page and page not in out.setdefault(body, []):
                    out[body].append(page)
    return out, src


def _distance(a: str, b: str) -> int:
    """레벤슈타인 거리. 길이가 짧아 단순 DP 로 충분하다."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def crosscheck(dir_a, dir_b, cfg: dict, label_a="기본서", label_b="사례집",
               reports_dir=None) -> tuple[str, int, str]:
    """(crosscheck.md, 불일치 건수, mnemonic_conflicts.md)"""
    pat = Patterns.build(cfg)
    a, ctx_a, side_a, prob_a = _collect(Path(dir_a), pat)
    b, ctx_b, side_b, prob_b = _collect(Path(dir_b), pat)
    pages_a, src_a = _pages_of(Path(dir_a), pat)
    pages_b, src_b = _pages_of(Path(dir_b), pat)

    both = sorted(set(a) & set(b))
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))

    # 한쪽에만 있는 것들 중 '거의 같은' 짝 — 여기가 진짜 위험한 지점이다
    pairs = []
    for x in only_a:
        for y in only_b:
            d = _distance(x, y)
            if 0 < d <= max(1, len(x) // 4) and abs(len(x) - len(y)) <= 1:
                pairs.append((x, y, d))
    pairs.sort(key=lambda t: (t[2], t[0]))

    L = ["# 두문자 교차 검증 (§5.3)", ""]
    L.append(f"- {label_a}: {len(a)}종 / {label_b}: {len(b)}종")
    L.append(f"- 양쪽 모두: {len(both)}종 (글자 단위 일치)")
    L.append(f"- **불일치 의심 짝: {len(pairs)}건**")
    L.append("")
    if pairs:
        L.append("## ⚠️ 불일치 의심 — 어느 쪽이 옳은지 사람이 판단할 것")
        L.append("")
        L.append("자동 교정하지 않았다. 양쪽 원문을 그대로 싣는다.")
        L.append("")
        for x, y, d in pairs:
            L.append(f"### `[{x}]` ({label_a}, {a[x]}회) ↔ `[{y}]` ({label_b}, {b[y]}회) "
                     f"— {d}글자 차이")
            L.append("")
            L.append(f"| 소스 | 표기 | 원문 |")
            L.append("|---|---|---|")
            L.append(f"| {label_a} | `[{x}]` | {ctx_a[x][0]} |")
            L.append(f"| {label_b} | `[{y}]` | {ctx_b[y][0]} |")
            L.append("")
    if both:
        L.append("## 양쪽 일치")
        L.append("")
        for m in both:
            L.append(f"- `[{m}]` — {label_a} {a[m]}회 / {label_b} {b[m]}회")
        L.append("")
    if only_a or only_b:
        L.append("## 한쪽에만 있는 두문자 (정상일 수 있다)")
        L.append("")
        for m in only_a:
            if not any(m == x for x, _, _ in pairs):
                L.append(f"- {label_a} 만: `[{m}]` ×{a[m]}")
        for m in only_b:
            if not any(m == y for _, y, _ in pairs):
                L.append(f"- {label_b} 만: `[{m}]` ×{b[m]}")
        L.append("")

    # §5.5 여백 마커 대조
    L.append("## 여백 마커 대조 (§5.5)")
    L.append("")
    L.append(f"- {label_a} 의 `sE-n` 옆번호: {len(side_a)}종 "
             f"({', '.join(sorted(side_a)[:12]) or '없음'})")
    L.append(f"- {label_b} 의 문제 번호: {len(prob_b)}종 "
             f"({', '.join(sorted(prob_b)[:12]) or '없음'})")
    L.append("")
    L.append("> 옆번호(`sE-8`)는 **강의교안 번호**로 사례집 문제 번호(`E-5`)와 다른 "
             "체계다(§4.3). 숫자가 안 맞는 것 자체는 오류가 아니다. 다만 "
             "`sE-81` 처럼 자릿수가 갑자기 커진 것은 병합 사고다.")
    L.append("")
    big = [s for s in side_a if int(_SIDE.match(s).group(1)) >= 100]
    if big:
        L.append(f"- ⚠️ 자릿수가 큰 옆번호: {', '.join(sorted(big))} — 병합 의심")
        L.append("")

    conflicts = _conflicts_report(
        pairs, a, b, ctx_a, ctx_b, pages_a, pages_b, src_a, src_b,
        only_a, only_b, label_a, label_b, cfg, reports_dir)
    return "\n".join(L) + "\n", len(pairs), conflicts


# ── §P1-3 사람이 표시할 결정표 ──────────────────────────────────
_DECISION_RX = re.compile(
    r"^-\s*\[(?P<mark>[ xX])\]\s*(?P<side>[AB])\s*:\s*`(?P<find>[^`]+)`"
    r"\s*→\s*`(?P<to>[^`]+)`", re.M)
_ID_RX = re.compile(r"^###\s+(?P<id>MC-\d{3})\b", re.M)


def _conflicts_report(pairs, a, b, ctx_a, ctx_b, pages_a, pages_b, src_a, src_b,
                      only_a, only_b, label_a, label_b, cfg, reports_dir) -> str:
    """§P1-3 — 두문자 불일치를 사람이 표시해 되먹일 수 있는 표로 낸다.

    프로그램은 어느 쪽이 옳은지 판정하지 않는다(§2.2). 대신 사람이 네모에
    표시만 하면 그 결정을 `config.yaml` 의 `corrections:` 로 옮겨 주는
    `convert apply-decisions` 를 붙여 둔다. 결정을 손으로 옮겨 적는 동안
    한 글자가 틀어지는 것이 이 문서에서 가장 무서운 사고다.
    """
    shots = _page_shots(pairs, only_a, only_b, pages_a, pages_b, src_a, src_b,
                        cfg, reports_dir)
    L = ["# 두문자 불일치 결정표 (§P1-3)", "",
         "네모 하나에만 `x` 를 넣고 저장한 뒤:", "",
         "```",
         "convert apply-decisions <이 파일>",
         "```", "",
         "표시한 대로 `config.yaml` 의 `corrections:` 에 줄이 들어간다. "
         "그다음 변환을 다시 돌리면 반영된다.", "",
         f"- A = {label_a} · B = {label_b}",
         "- 아무 데도 표시하지 않으면 그 짝은 건너뛴다 (판단 보류).", ""]
    if not pairs:
        L.append("불일치 의심 짝이 없다.")
        L.append("")
    for k, (x, y, d) in enumerate(pairs, 1):
        L.append(f"### MC-{k:03d} `[{x}]` ↔ `[{y}]` — {d}글자 차이")
        L.append("")
        L.append(f"| 소스 | 표기 | 횟수 | 쪽 | 원문 |")
        L.append("|---|---|---:|---|---|")
        L.append(f"| A {label_a} | `[{x}]` | {a[x]} | {_pp(pages_a.get(x))} "
                 f"| {ctx_a[x][0]} |")
        L.append(f"| B {label_b} | `[{y}]` | {b[y]} | {_pp(pages_b.get(y))} "
                 f"| {ctx_b[y][0]} |")
        L.append("")
        for name, path in shots.get(("A", x), []) + shots.get(("B", y), []):
            L.append(f"- 쪽 그림: `{path}` ({name})")
        L.append(f"- [ ] A: `{y}` → `{x}`   (옳은 쪽: A {label_a})")
        L.append(f"- [ ] B: `{x}` → `{y}`   (옳은 쪽: B {label_b})")
        L.append("- [ ] 둘 다 맞다 — 서로 다른 두문자다 (아무것도 안 한다)")
        L.append("")

    lone_a = [m for m in only_a if not any(m == x for x, _, _ in pairs)]
    lone_b = [m for m in only_b if not any(m == y for _, y, _ in pairs)]
    L.append("## 한쪽에만 있는 두문자")
    L.append("")
    L.append("짝이 없다고 틀린 것은 아니다. 한쪽 책에만 실린 논점이면 정상이다. "
             "쪽 그림을 열어 원문과 글자가 같은지만 본다.")
    L.append("")
    L.append("| 소스 | 두문자 | 횟수 | 쪽 | 쪽 그림 |")
    L.append("|---|---|---:|---|---|")
    for side, label, items, counts, pages in (("A", label_a, lone_a, a, pages_a),
                                              ("B", label_b, lone_b, b, pages_b)):
        for m in items:
            shot = shots.get((side, m), [])
            L.append(f"| {side} {label} | `[{m}]` | {counts[m]} | {_pp(pages.get(m))} "
                     f"| {shot[0][1] if shot else '-'} |")
    L.append("")
    return "\n".join(L) + "\n"


def _pp(pages) -> str:
    if not pages:
        return "-"
    pages = sorted(pages)
    head = ", ".join(str(p) for p in pages[:6])
    return head + (" …" if len(pages) > 6 else "")


def _page_shots(pairs, only_a, only_b, pages_a, pages_b, src_a, src_b,
                cfg, reports_dir) -> dict:
    """확인할 쪽을 그림으로 떠 둔다 (§P1-3).

    글자만 늘어놓으면 어느 쪽이 옳은지 끝내 알 수 없다. 종이를 봐야 한다.
    쪽수가 많으므로 상한을 둔다.
    """
    if reports_dir is None:
        return {}
    rc = cfg.get("report", {})
    limit = int(rc.get("max_page_images", 40))
    dpi = int(rc.get("page_image_dpi", 130))
    want: list[tuple[str, str, int, str]] = []      # (side, body, page, src)
    for x, y, _ in pairs:
        for side, body, table, src in (("A", x, pages_a, src_a), ("B", y, pages_b, src_b)):
            for p in sorted(table.get(body) or [])[:1]:
                want.append((side, body, p, src))
    for side, items, table, src in (("A", only_a, pages_a, src_a),
                                    ("B", only_b, pages_b, src_b)):
        for body in items:
            for p in sorted(table.get(body) or [])[:1]:
                want.append((side, body, p, src))
    seen: set = set()
    unique = []
    for w in want:
        if not w[3] or (w[0], w[1]) in seen:
            continue
        seen.add((w[0], w[1]))
        unique.append(w)
    want = unique[:limit]
    if not want:
        return {}
    out_dir = Path(reports_dir) / "mnemonic_pages"
    shots: dict = {}
    try:
        import pymupdf
    except ImportError:                            # pragma: no cover
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    by_src: dict[str, list] = {}
    for side, body, page, src in want:
        by_src.setdefault(src, []).append((side, body, page))
    for src, items in by_src.items():
        if not Path(src).exists():
            continue
        try:
            with pymupdf.open(src) as doc:
                for side, body, page in items:
                    if not (1 <= page <= doc.page_count):
                        continue
                    name = f"{Path(src).stem}_p{page:04d}.png"
                    path = out_dir / name
                    if not path.exists():
                        doc[page - 1].get_pixmap(dpi=dpi).save(str(path))
                    shots.setdefault((side, body), []).append(
                        (f"p.{page}", str(path)))
        except Exception:                          # pragma: no cover
            continue
    return shots


# ── 결정 되먹이기 ───────────────────────────────────────────────
def read_decisions(path) -> list[dict]:
    """결정표에서 사람이 표시한 줄만 뽑는다 (§P1-3).

    표시가 없는 짝은 건너뛴다. 프로그램이 대신 정하지 않는다.
    """
    text = Path(path).read_text(encoding="utf-8")
    out = []
    current = "?"
    for line in text.splitlines():
        mid = _ID_RX.match(line)
        if mid:
            current = mid.group("id")
            continue
        m = _DECISION_RX.match(line)
        if m and m.group("mark").lower() == "x":
            out.append({"id": current, "side": m.group("side"),
                        "find": m.group("find"), "to": m.group("to")})
    return out


def merge_corrections(config_path, decisions: list[dict]) -> tuple[int, int]:
    """결정을 config.yaml 의 corrections 로 옮긴다. (더한 수, 이미 있던 수)

    yaml 을 다시 써 내면 사람이 적어 둔 주석이 통째로 날아간다. 그래서
    `corrections:` 블록 끝에 줄만 이어 붙인다.
    """
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    added = dupes = 0
    lines = []
    for d in decisions:
        find, to = f"[{d['find']}]", f"[{d['to']}]"
        entry = ('  - {find: "%s", to: "%s", note: "%s 두문자 결정 (§P1-3)"}'
                 % (find, to, d["id"]))
        if f'find: "{find}"' in text or entry in "\n".join(lines):
            dupes += 1
            continue
        lines.append(entry)
        added += 1
    if not lines:
        return 0, dupes

    block = "\n".join(lines)
    rows = text.splitlines()
    head = next((i for i, r in enumerate(rows)
                 if re.match(r"^corrections:\s*$", r)), None)
    if head is None:
        text = text.rstrip("\n") + "\n\ncorrections:\n" + block + "\n"
    else:
        # 블록에 딸린 마지막 줄(들여쓴 줄) 뒤에 붙인다. 빈 줄·왼쪽 끝 주석은
        # 다음 항목의 머리말이므로 넘겨준다 — 그 앞에 끼워 넣어야 한다.
        last = head
        for i in range(head + 1, len(rows)):
            row = rows[i]
            if not row.strip():
                continue
            if row[0] in " \t":
                last = i
                continue
            break
        rows[last + 1:last + 1] = block.splitlines()
        text = "\n".join(rows) + ("\n" if text.endswith("\n") else "")
    path.write_text(text, encoding="utf-8")
    return added, dupes
