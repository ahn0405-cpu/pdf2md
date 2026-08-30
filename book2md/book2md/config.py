"""config.yaml 로드와 프로파일 병합."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        raise SystemExit(f"설정 파일이 없다: {p}")
    with open(p, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["_path"] = str(p)
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
