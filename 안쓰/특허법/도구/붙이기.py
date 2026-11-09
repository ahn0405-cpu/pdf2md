#!/usr/bin/env python3
"""회차 하나를 쓴 초고 두 개를 암기장·자료 끝에 붙인다.

긴 마크다운을 셸 히어독으로 붙이면 따옴표·백틱 때문에 깨진다 — 초고는 Write 도구로 파일에 쓰고 이걸로 붙인다.

    python 붙이기.py 10        안쓰/_work/박형준/초고/10_암기장.md · 10_자료.md
                               → [특허법] 안쓰 GS 암기장.md · [특허법] 안쓰 GS 자료.md 끝에

초고는 `## N회차 문제-k` 로 시작한다(앞에 빈 줄 하나). 붙인 뒤 `빈칸채우기.py --검사` → `빈칸채우기.py`.
"""
import sys
from pathlib import Path

여기 = Path(__file__).resolve().parent
폴더 = 여기.parent / "박형준GS"
초고 = 여기.parent.parent / "_work" / "박형준" / "초고"


def main(argv):
    n = f"{int(argv[0]):02d}"
    for 종류 in ("암기장", "자료"):
        src = 초고 / f"{n}_{종류}.md"
        dst = 폴더 / f"[특허법] 안쓰 GS {종류}.md"
        본 = dst.read_text(encoding="utf-8")
        if f"## {int(n)}회차 문제-" in 본:
            sys.exit(f"{dst.name} 에 이미 {int(n)}회차가 있다 — 두 번 붙이지 않는다")
        dst.write_text(본.rstrip("\n") + "\n\n" + src.read_text(encoding="utf-8").strip("\n") + "\n",
                       encoding="utf-8", newline="\n")
        print(f"{dst.name} + {src.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
