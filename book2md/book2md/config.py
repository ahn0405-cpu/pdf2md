"""config.yaml 로드와 프로파일 병합.

설정은 **층으로 쌓는다.** 아래에 교재와 무관한 공통 규칙을, 위에 교재별
규칙을 얹는다.

    convert --config config.yaml --config config-민소법.yaml all …

교재를 여럿 동시에 변환하기 때문이다. 공통 규칙(사건번호 문법, 각주 판정,
두문자 판정, 검증 기준)은 한 곳에서 고쳐야 두 교재에 함께 반영된다. 반대로
사람이 확인한 정정과 책 제목은 교재를 넘어가면 **해를 끼친다** — 민소법
원문에서 확인한 정정 14개가 특허법 원문에 적용되면 안 된다.
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


def _merge(base: dict, over: dict) -> dict:
    """딕셔너리는 깊이 합치고, 목록과 낱값은 **갈아 끼운다.**

    목록을 이어 붙이면 위층에서 뺄 방법이 없어진다. 민소법 정정을 물려받은
    특허법 설정이 그것을 지우지 못하면 층을 나눈 뜻이 없다.
    """
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(paths=None) -> dict:
    """설정 파일 하나 또는 여럿을 순서대로 얹어 읽는다."""
    if paths is None or paths == []:
        items = [DEFAULT_CONFIG]
    elif isinstance(paths, (str, Path)):
        items = [x.strip() for x in str(paths).split(",") if x.strip()]
    else:
        items = list(paths)

    cfg: dict = {}
    used: list = []
    for item in items:
        p = Path(item)
        if not p.exists():
            raise SystemExit(f"설정 파일이 없다: {p}")
        with open(p, encoding="utf-8") as fh:
            layer = yaml.safe_load(fh) or {}
        if not isinstance(layer, dict):
            raise SystemExit(f"설정 파일이 딕셔너리가 아니다: {p}")
        cfg = _merge(cfg, layer)
        used.append(str(p))
    cfg["_path"] = used[-1]
    cfg["_paths"] = used
    return cfg


def profile(cfg: dict, name: str) -> dict:
    profiles = cfg.get("profiles", {})
    if name not in profiles:
        raise SystemExit(
            f"모르는 프로파일 '{name}'. 쓸 수 있는 것: {', '.join(sorted(profiles))}"
        )
    prof = copy.deepcopy(profiles[name])
    prof["name"] = name
    return prof
