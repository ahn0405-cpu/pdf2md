"""명령줄에서 PDF -> Markdown 변환 (웹 UI 없이 일괄 처리할 때).

    python pdf2md/cli.py in/*.pdf -o out/
    python pdf2md/cli.py doc.pdf --images base64 --page-separator
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    from . import converter
except ImportError:  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import converter  # type: ignore


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PDF → Markdown 변환")
    p.add_argument("inputs", nargs="+", help="PDF 파일 경로")
    p.add_argument("-o", "--outdir", default=".", help="출력 폴더 (기본: 현재 폴더)")
    p.add_argument("--tables", default="markdown", choices=["markdown", "html", "text", "skip"])
    p.add_argument("--images", default="extract", choices=["extract", "base64", "skip"])
    p.add_argument("--page-separator", action="store_true")
    p.add_argument("--page-comment", action="store_true")
    p.add_argument("--front-matter", action="store_true")
    p.add_argument("--no-headings", action="store_true")
    p.add_argument("--no-lists", action="store_true")
    p.add_argument("--no-styles", action="store_true")
    p.add_argument("--no-columns", action="store_true")
    p.add_argument("--keep-header-footer", action="store_true")
    args = p.parse_args(argv)

    opt = converter.Options(
        detect_headings=not args.no_headings,
        detect_lists=not args.no_lists,
        inline_styles=not args.no_styles,
        columns=not args.no_columns,
        strip_header_footer=not args.keep_header_footer,
        tables=args.tables,
        images=args.images,
        page_separator=args.page_separator,
        page_comment=args.page_comment,
        front_matter=args.front_matter,
    )

    os.makedirs(args.outdir, exist_ok=True)
    failed = 0

    for path in args.inputs:
        name = os.path.basename(path)
        try:
            with open(path, "rb") as fh:
                result = converter.convert(fh.read(), name, opt)
        except Exception as exc:
            print(f"✕ {name}: {exc}", file=sys.stderr)
            failed += 1
            continue

        md_path = os.path.join(args.outdir, os.path.splitext(name)[0] + ".md")
        with open(md_path, "w", encoding="utf-8") as fh:
            fh.write(result.markdown)

        for asset in result.assets:
            dest = os.path.join(args.outdir, asset.name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(asset.data)

        s = result.stats
        print(f"✓ {md_path}  ({s['pages']}쪽, 제목 {s['headings']}, 표 {s['tables']}, 이미지 {s['images']})")
        for warn in result.warnings:
            print(f"  ⚠ {warn}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
