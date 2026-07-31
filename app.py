"""PDF -> Markdown 변환 웹앱 (Flask).

실행:
    pip install -r pdf2md/requirements.txt
    python pdf2md/app.py            # http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory

try:  # 패키지로도, 단독 스크립트로도 실행되게
    from . import converter
except ImportError:  # pragma: no cover
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import converter  # type: ignore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

MAX_CONTENT_MB = int(os.environ.get("PDF2MD_MAX_MB", "200"))
JOB_TTL_SECONDS = int(os.environ.get("PDF2MD_TTL", str(60 * 60)))
JOB_LIMIT = int(os.environ.get("PDF2MD_JOB_LIMIT", "200"))

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_MB * 1024 * 1024


# ---------------------------------------------------------------------------
# 변환 결과 임시 보관 (메모리, TTL)
# ---------------------------------------------------------------------------


@dataclass
class Job:
    id: str
    name: str            # 원본 파일명
    md_name: str         # 내려받을 .md 파일명
    result: converter.Result
    created: float = field(default_factory=time.time)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _gc() -> None:
    now = time.time()
    with _lock:
        stale = [jid for jid, job in _jobs.items() if now - job.created > JOB_TTL_SECONDS]
        for jid in stale:
            _jobs.pop(jid, None)
        while len(_jobs) > JOB_LIMIT:
            oldest = min(_jobs.values(), key=lambda j: j.created)
            _jobs.pop(oldest.id, None)


def _safe_name(name: str) -> str:
    name = os.path.basename(name or "document.pdf")
    name = re.sub(r"[\r\n\t]", "", name)
    return name or "document.pdf"


def _md_name(pdf_name: str) -> str:
    return re.sub(r"\.pdf$", "", _safe_name(pdf_name), flags=re.I) + ".md"


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------


@app.get("/")
def index() -> Response:
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:path>")
def static_files(path: str) -> Response:
    return send_from_directory(STATIC_DIR, path)


@app.get("/api/options")
def default_options() -> Response:
    return jsonify(converter.Options().to_dict())


@app.post("/api/convert")
def api_convert() -> Response:
    """PDF 한 개를 변환한다. 프런트에서 파일마다 한 번씩 호출한다."""
    _gc()
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"error": "파일이 없습니다."}), 400

    name = _safe_name(upload.filename or "document.pdf")
    data = upload.read()
    if not data:
        return jsonify({"error": "빈 파일입니다."}), 400
    if not data[:1024].lstrip().startswith(b"%PDF"):
        return jsonify({"error": "PDF 파일이 아닙니다."}), 400

    opts: dict[str, Any] = {}
    raw = request.form.get("options")
    if raw:
        import json

        try:
            opts = json.loads(raw)
        except ValueError:
            return jsonify({"error": "옵션 형식이 잘못되었습니다."}), 400

    started = time.time()
    try:
        result = converter.convert(data, name, opts)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover
        app.logger.exception("convert failed")
        return jsonify({"error": f"변환 중 오류: {exc}"}), 500

    job = Job(id=uuid.uuid4().hex, name=name, md_name=_md_name(name), result=result)
    with _lock:
        _jobs[job.id] = job

    return jsonify({
        "id": job.id,
        "name": name,
        "mdName": job.md_name,
        "markdown": result.markdown,
        "warnings": result.warnings,
        "stats": {**result.stats, "elapsed": round(time.time() - started, 2),
                  "assets": len(result.assets)},
        "assets": [a.name for a in result.assets],
    })


@app.get("/api/download/<job_id>")
def download_md(job_id: str) -> Response:
    job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "결과가 만료되었습니다. 다시 변환하세요."}), 404
    return Response(
        converter.markdown_bytes(job.result),
        content_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _attachment(job.md_name)},
    )


@app.get("/api/bundle/<job_id>")
def download_bundle(job_id: str) -> Response:
    """이미지가 있는 경우 .md + assets 를 zip 으로."""
    job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "결과가 만료되었습니다. 다시 변환하세요."}), 404
    blob = converter.make_zip(converter.convert_to_zip_entries(job.result, job.md_name))
    zip_name = re.sub(r"\.md$", "", job.md_name) + ".zip"
    return Response(blob, mimetype="application/zip",
                    headers={"Content-Disposition": _attachment(zip_name)})


@app.post("/api/bundle")
def download_all() -> Response:
    """여러 결과를 하나의 zip 으로 묶는다."""
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    jobs = [_jobs[i] for i in ids if i in _jobs]
    if not jobs:
        return jsonify({"error": "내려받을 결과가 없습니다."}), 404

    entries: list[tuple[str, bytes]] = []
    used: set[str] = set()
    for job in jobs:
        base = re.sub(r"\.md$", "", job.md_name)
        unique = base
        n = 2
        while f"{unique}.md" in used:
            unique = f"{base}-{n}"
            n += 1
        used.add(f"{unique}.md")

        markdown = job.result.markdown
        assets = [(a.name, a.data) for a in job.result.assets]
        # 이름이 겹쳐 바뀌었다면 이미지 폴더와 본문 참조도 함께 옮긴다
        if unique != base and job.result.asset_dir:
            old_dir = job.result.asset_dir
            new_dir = f"{unique}.assets"
            markdown = markdown.replace(f"({old_dir}/", f"({new_dir}/")
            assets = [(new_dir + name[len(old_dir):], data) for name, data in assets]

        entries.append((f"{unique}.md", markdown.encode("utf-8")))
        entries.extend(assets)

    blob = converter.make_zip(entries)
    return Response(blob, mimetype="application/zip",
                    headers={"Content-Disposition": _attachment("markdown.zip")})


@app.get("/api/asset/<job_id>/<path:asset_name>")
def get_asset(job_id: str, asset_name: str) -> Response:
    """미리보기에서 추출 이미지를 표시하기 위한 엔드포인트."""
    job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    for asset in job.result.assets:
        if asset.name == asset_name:
            return Response(asset.data, mimetype=asset.mime,
                            headers={"Cache-Control": "private, max-age=600"})
    return jsonify({"error": "not found"}), 404


@app.errorhandler(413)
def too_large(_exc) -> Response:
    return jsonify({"error": f"파일이 너무 큽니다 (최대 {MAX_CONTENT_MB}MB)."}), 413


def _attachment(filename: str) -> str:
    from urllib.parse import quote

    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF → Markdown 웹 변환기")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"  PDF → Markdown  http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
