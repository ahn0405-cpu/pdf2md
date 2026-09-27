#!/usr/bin/env python3
"""리포의 SKILL.md 를 업로드용 스킬 꾸러미(.zip)로 묶는다.

계정에 동기화된 스킬은 한번 올려 두면 리포와 **갈라진다.** 실제로 그렇게 되어
758줄에서 멈춘 판본이 참조 파일도 없이 남아 있었다. 그래서 묶는 일을
손으로 하지 않고 이 스크립트로 한다. SKILL.md 를 고쳤으면 다시 돌려 올린다.

꾸러미에 넣는 것은 **SKILL.md 가 실제로 참조하는 것**뿐이다.
스크립트는 넣지 않는다 — 리포의 `출력/`·`노트/` 를 읽어서 꾸러미 안에서는
동작하지 않는다. 꾸러미는 `작업/민소법-단권화.zip` 에 생긴다.

    python3 스킬묶기.py            묶고 검사한다
    python3 스킬묶기.py --검사      묶지 않고 무엇이 들어갈지만 본다
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

from 경로 import 작업 as HERE    # SKILL.md·references·samples 가 있는 곳
이름 = "민소법-단권화"
담을것 = [
    "SKILL.md",
    "references/소스결함.md",
    "references/확인목록.md",
    "samples/046_일부청구.md",
    "samples/암기노트_CH06_소송물.md",
]


def 앞머리(s):
    """frontmatter 의 name·description 을 꺼낸다. 없으면 업로드가 거부된다."""
    m = re.match(r"^---\n(.*?)\n---\n", s, re.S)
    if not m:
        return None, None, "frontmatter(--- 로 감싼 머리)가 없다"
    머리 = m.group(1)
    n = re.search(r"^name:\s*(.+)$", 머리, re.M)
    d = re.search(r"^description:\s*(.+)$", 머리, re.M)
    if not n:
        return None, None, "frontmatter 에 name 이 없다"
    if not d:
        return None, None, "frontmatter 에 description 이 없다"
    return n.group(1).strip(), d.group(1).strip(), None


def 본다():
    문제 = []
    s = (HERE / "SKILL.md").read_text(encoding="utf-8")
    name, desc, 흠 = 앞머리(s)
    if 흠:
        문제.append(흠)
    elif name != 이름:
        문제.append(f"frontmatter 의 name({name})이 꾸러미 이름({이름})과 다르다")
    elif len(desc) > 1024:
        문제.append(f"description 이 {len(desc)}자 — 1024자를 넘는다")

    크기 = 0
    for rel in 담을것:
        f = HERE / rel
        if not f.exists():
            문제.append(f"없는 파일: {rel}")
            continue
        크기 += f.stat().st_size

    # SKILL.md 가 가리키는데 꾸러미에 없는 참조가 있으면 올라가서 깨진다
    for ref in sorted(set(re.findall(r"(?:references|samples)/[^\s`·)）,]+", s))):
        if ref not in 담을것:
            문제.append(f"SKILL.md 가 가리키는데 꾸러미에 없다: {ref}")

    return name, desc, 크기, 문제


def 묶는다():
    name, desc, 크기, 문제 = 본다()
    print(f"이름  {name}")
    print(f"설명  {desc[:70]}…")
    print(f"크기  {크기/1024:.0f}KB  ({len(담을것)}개 파일)")
    for rel in 담을것:
        print(f"      {rel}")
    if 문제:
        print("\n✖ 묶지 않았다")
        for x in 문제:
            print("  -", x)
        return 1
    if "--검사" in sys.argv:
        print("\n✔ 문제 없음 (--검사 라 묶지 않았다)")
        return 0

    zip경로 = HERE / f"{이름}.zip"
    if zip경로.exists():
        zip경로.unlink()
    with zipfile.ZipFile(zip경로, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in 담을것:
            z.write(HERE / rel, f"{이름}/{rel}")   # 꾸러미 안에 스킬 이름 폴더를 둔다
    print(f"\n✔ {zip경로.name}  {zip경로.stat().st_size/1024:.0f}KB")
    with zipfile.ZipFile(zip경로) as z:
        assert z.testzip() is None
        for n in z.namelist():
            print("   ", n)
    return 0


if __name__ == "__main__":
    sys.exit(묶는다())
