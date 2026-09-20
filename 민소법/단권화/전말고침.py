#!/usr/bin/env python3
"""「상황과 주장」 한 항목을 「상황」/「주장과 소 제기」 두 항목으로 갈아 끼운다.

줄바꿈 자리를 외워 두고 문자열로 찾으면 매번 어긋난다. 그러지 않고
블록을 **행 범위로 집어** 통째로 바꾼다. 찾는 열쇠는 블록 안의 짧은 토막이다.
박스 안(`>`)이면 들여쓰기 접두사를 그대로 물려받는다.
"""
import re


벗김 = lambda l: re.sub(r"^[>\s]*>", "", l) if l.lstrip().startswith(">") else l


def 고친다(path, 쌍):
    """쌍: [(열쇠, 새 본문), ...] — 열쇠는 그 블록에만 있는 토막."""
    L = open(path, encoding="utf-8").read().split("\n")
    for 열쇠, 새 in 쌍:
        자리 = None
        for i, l in enumerate(L):
            if not re.search(r"\*\*상황(과 주장)?\*\*", l):
                continue
            j = i + 1
            while j < len(L) and 벗김(L[j]).startswith("  ") and not re.match(r"\s*-\s\*\*", 벗김(L[j])):
                j += 1
            if 열쇠 in " ".join(x.strip() for x in L[i:j]):
                자리 = (i, j)
                break
        if 자리 is None:
            print("!! 못 찾음:", path, 열쇠[:30])
            continue
        i, j = 자리
        접두 = re.match(r"^([>\s]*>\s*)?", L[i]).group(1) or ""
        본문 = [접두 + x if x else 접두.rstrip() for x in 새.rstrip("\n").split("\n")]
        L[i:j] = 본문
    open(path, "w", encoding="utf-8").write("\n".join(L))
